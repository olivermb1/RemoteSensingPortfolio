"""Find ECOSTRESS tiled LST granules for an area and dates, download the layers
needed for the check, and look up each scene's geolocation flag.

Searching uses NASA CMR (no login). Downloads and reading the L1B GEO
metadata need a free Earthdata login: ~/.netrc
(machine urs.earthdata.nasa.gov login USER password PASS) or EARTHDATA_TOKEN.
The flag is read from CMR granule attributes when present; otherwise from the
L1B GEO file itself, opened remotely with earthaccess + h5py so only the
metadata is transferred, not the whole file.

Untested against the live services: CMR and LP DAAC were unreachable from the
sandbox this was written in.
"""

import csv
import json
import os

from . import flags, names

CMR = "https://cmr.earthdata.nasa.gov/search/granules.umm_json"
LSTE = ("ECO_L2T_LSTE", "002")
GEO = ("ECO_L1B_GEO", "002")
LAYERS = ("LST", "cloud", "water")


def _session():
    import requests
    s = requests.Session()
    tok = os.environ.get("EARTHDATA_TOKEN")
    if tok:
        s.headers["Authorization"] = f"Bearer {tok}"
    return s


def search(short_name, version, bbox, start, end, session=None, log=print):
    s = session or _session()
    params = {"short_name": short_name, "version": version, "bounding_box": ",".join(map(str, bbox)),
              "temporal": f"{start}T00:00:00Z,{end}T23:59:59Z", "page_size": 2000}
    items, headers = [], {}
    while True:
        r = s.get(CMR, params=params, headers=headers, timeout=120)
        r.raise_for_status()
        got = r.json().get("items", [])
        items += got
        after = r.headers.get("CMR-Search-After")
        if not after or len(got) < params["page_size"]:
            break
        headers = {"CMR-Search-After": after}
    log(f"{short_name}.{version}: {len(items)} granules")
    return [it["umm"] for it in items]


def _urls(umm):
    return [u["URL"] for u in umm.get("RelatedUrls", []) if u.get("Type") in ("GET DATA", "GET DATA VIA DIRECT ACCESS")
            and u["URL"].startswith("https")]


def geo_flag_from_file(url, log=print):
    """Read the fields from a remote L1B GEO .h5 with earthaccess (range reads)."""
    try:
        import earthaccess
        import h5py  # noqa: F401
    except ImportError:
        log("  install earthaccess and h5py to read flags from L1B GEO files")
        return None
    earthaccess.login(strategy="environment" if os.environ.get("EARTHDATA_TOKEN") else "netrc")
    fs = earthaccess.get_fsspec_https_session()
    with fs.open(url, "rb", block_size=2 ** 20) as fh:
        return flags.from_hdf5(fh)  # h5py reads only the blocks it needs


def fetch(bbox, start, end, dest, tiles=None, layers=LAYERS, list_only=False, read_geo=True, log=print):
    s = _session()
    os.makedirs(dest, exist_ok=True)
    lste = search(*LSTE, bbox, start, end, s, log)
    if tiles:
        lste = [u for u in lste if (names.parse(u["GranuleUR"]) or {}).get("tile") in tiles]
    keys = {}
    for u in lste:
        info = names.parse(u["GranuleUR"])
        if info:
            keys.setdefault(names.scene_key(info), []).append(u)
    log(f"{len(lste)} tiled granules from {len(keys)} scenes")
    geo = {names.scene_key(names.parse(u["GranuleUR"])): u for u in search(*GEO, bbox, start, end, s, log)
           if names.parse(u["GranuleUR"])}
    rows = []
    for key, grans in keys.items():
        g = geo.get(key)
        rec = flags.from_umm(g) if g else None
        if rec is None:
            for u in grans:
                rec = rec or flags.from_umm(u, "CMR tiled granule metadata")
        if rec is None and g and read_geo and not list_only:
            url = next((x for x in _urls(g) if x.endswith(".h5")), None)
            if url:
                log(f"  reading flag from {os.path.basename(url)}")
                try:
                    rec = geo_flag_from_file(url, log)
                except Exception as e:  # network, auth
                    log(f"  could not read {url}: {e}")
        rows.append({"orbit": key[0], "scene": key[1],
                     "GeolocationAccuracyQA": rec["geo_qa"] if rec else "",
                     "OrbitCorrectionPerformed": rec["orbit_corrected"] if rec else "",
                     "FieldOfViewObstruction": rec["fov_obstruction"] if rec else "",
                     "source": rec["source"] if rec else "not found",
                     "tiles": " ".join(sorted({names.parse(u["GranuleUR"])["tile"] for u in grans}))})
        if list_only:
            continue
        for u in grans:
            with open(os.path.join(dest, u["GranuleUR"] + ".json"), "w") as f:
                json.dump(u, f)
            for url in _urls(u):
                info = names.parse(url)
                if not info or info.get("layer") not in layers:
                    continue
                out = os.path.join(dest, os.path.basename(url))
                if os.path.exists(out):
                    continue
                log(f"  downloading {os.path.basename(url)}")
                r = s.get(url, timeout=300, stream=True)
                r.raise_for_status()
                with open(out + ".part", "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
                os.replace(out + ".part", out)
    path = os.path.join(dest, "geo_flags.csv")
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, ["orbit", "scene", "GeolocationAccuracyQA", "OrbitCorrectionPerformed",
                               "FieldOfViewObstruction", "source", "tiles"])
        w.writeheader()
        w.writerows(rows)
    log(f"flags for {len(rows)} scenes in {path}")
    return rows
