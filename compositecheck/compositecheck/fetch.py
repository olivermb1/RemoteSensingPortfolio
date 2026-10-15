"""Download NASA HLS v2.0 granules for an area, cut to the area.

    python -m compositecheck.fetch --bbox W S E N --start 2024-01-01 --end 2024-06-30 --out hls/

Needs a free NASA Earthdata login (urs.earthdata.nasa.gov) and the
`earthaccess` package. Only the six bands Composite Check uses plus Fmask are
read, and only the window over --bbox, straight from the cloud-optimised
GeoTIFFs, so a small area costs megabytes rather than gigabytes. Files keep
their HLS names, so the folder can be passed straight to `python -m compositecheck`.
"""

import argparse
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

from .catalog import HLS_RE
from .sensors import HLS_BANDS

SHORT_NAMES = {"L30": "HLSL30", "S30": "HLSS30"}

GDAL_ENV = dict(
    GDAL_HTTP_COOKIEFILE=os.path.expanduser("~/.compositecheck_cookies.txt"),
    GDAL_HTTP_COOKIEJAR=os.path.expanduser("~/.compositecheck_cookies.txt"),
    GDAL_HTTP_NETRC="YES",
    GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
    CPL_VSIL_CURL_ALLOWED_EXTENSIONS="TIF",
    GDAL_HTTP_MAX_RETRY="4",
    GDAL_HTTP_RETRY_DELAY="2",
)


def search(bbox, start, end, products=("L30", "S30"), max_cloud=None):
    """Granules over bbox (W, S, E, N degrees) between start and end, both products."""
    import earthaccess

    kw = dict(short_name=[SHORT_NAMES[p] for p in products], version="2.0",
              bounding_box=tuple(bbox), temporal=(start, end), count=-1)
    if max_cloud is not None:
        kw["cloud_cover"] = (0, max_cloud)
    return earthaccess.search_data(**kw)


def granule_files(granule):
    """{granule_id: {band: url}} for the bands Composite Check needs, plus Fmask."""
    out = {}
    for url in granule.data_links(access="external"):
        m = HLS_RE.search(os.path.basename(url))
        if not m:
            continue
        need = set(HLS_BANDS[m["prod"]]) | {"Fmask"}
        if m["band"] in need:
            gid = os.path.basename(url)[: m.start("band") - 1]
            out.setdefault(gid, {"_tile": m["tile"]})[m["band"]] = url
    return out


def clip_one(url, bbox, dest):
    """Read the bbox window of one remote band and write it to dest. Returns
    'ok', 'skip' (already there) or 'outside' (no overlap)."""
    import rasterio
    import rasterio.errors
    from rasterio.warp import transform_bounds
    from rasterio.windows import from_bounds

    if os.path.exists(dest):
        return "skip"
    with rasterio.Env(**GDAL_ENV), rasterio.open(url) as src:
        b = transform_bounds("EPSG:4326", src.crs, *bbox)
        win = from_bounds(*b, transform=src.transform).round_offsets().round_lengths()
        try:
            win = win.intersection(rasterio.windows.Window(0, 0, src.width, src.height))
        except rasterio.errors.WindowError:  # no overlap at all
            return "outside"
        if win.width < 1 or win.height < 1:
            return "outside"
        data = src.read(1, window=win)
        prof = src.profile.copy()
        prof.update(driver="GTiff", width=int(win.width), height=int(win.height),
                    transform=src.window_transform(win), compress="deflate", tiled=False)
        for k in ("blockxsize", "blockysize", "interleave"):
            prof.pop(k, None)
    tmp = dest + ".part"
    with rasterio.open(tmp, "w", **prof) as dst:
        dst.write(data, 1)
    os.replace(tmp, dest)
    return "ok"


def fetch(bbox, start, end, out, products=("L30", "S30"), tile=None, max_cloud=None, workers=8, log=print):
    """Search, choose one MGRS tile, and clip every needed band into out/<granule>/.
    Returns the list of granule ids written."""
    import earthaccess

    earthaccess.login(persist=True)  # ~/.netrc, which GDAL then uses
    results = search(bbox, start, end, products, max_cloud)
    gran = {}
    for g in results:
        gran.update(granule_files(g))
    if not gran:
        raise SystemExit("no HLS granules found for that area and period")

    # An area near a tile edge returns granules from neighbouring MGRS tiles,
    # which would double-count dates. Keep one tile: the one asked for, or the most common.
    tiles = Counter(f["_tile"] for f in gran.values())
    tile = tile or tiles.most_common(1)[0][0]
    if len(tiles) > 1:
        log(f"granules from tiles {dict(tiles)}; using {tile} (choose with --tile)")
    gran = {gid: f for gid, f in gran.items() if f["_tile"] == tile}
    complete = {gid: f for gid, f in gran.items()
                if all(b in f for b in HLS_BANDS[gid.split(".")[1]] + ["Fmask"])}
    if len(complete) < len(gran):
        log(f"{len(gran) - len(complete)} granules lack a needed band and were skipped")
    log(f"{len(complete)} granules ({sum(g.split('.')[1] == 'L30' for g in complete)} Landsat, "
        f"{sum(g.split('.')[1] == 'S30' for g in complete)} Sentinel-2) on tile {tile}")

    jobs = []
    for gid, files in complete.items():
        os.makedirs(os.path.join(out, gid), exist_ok=True)
        for band, url in files.items():
            if band != "_tile":
                jobs.append((gid, url, os.path.join(out, gid, os.path.basename(url))))
    status, failed, t0 = Counter(), [], time.time()
    with ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(clip_one, url, bbox, dest): (gid, url) for gid, url, dest in jobs}
        for i, f in enumerate(as_completed(futs), 1):
            try:
                status[f.result()] += 1
            except Exception as e:  # keep going; report at the end
                failed.append((futs[f], repr(e)))
            if i % 50 == 0 or i == len(jobs):
                log(f"  {i}/{len(jobs)} files, {time.time() - t0:.0f} s")
    if failed:
        log(f"{len(failed)} files failed, e.g. {failed[0][0][1]}: {failed[0][1]}")
        if any("401" in e or "403" in e for _, e in failed):
            log("authorisation failed: check your Earthdata login and that ~/.netrc has urs.earthdata.nasa.gov")
    log(f"done: {dict(status)} -> {out}")
    return sorted(complete)


def main(argv=None):
    p = argparse.ArgumentParser(prog="compositecheck.fetch", description=__doc__.split("\n\n")[0])
    p.add_argument("--bbox", type=float, nargs=4, metavar=("W", "S", "E", "N"), required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--products", default="L30,S30", help="L30, S30 or both (default)")
    p.add_argument("--tile", help="MGRS tile to keep, e.g. T36MZE (default: the most common)")
    p.add_argument("--max-cloud", type=float, help="skip granules with more than this %% cloud")
    p.add_argument("--workers", type=int, default=8)
    a = p.parse_args(argv)
    fetch(a.bbox, a.start, a.end, a.out, tuple(x.strip() for x in a.products.split(",")),
          a.tile, a.max_cloud, a.workers, log=lambda s: print(s, file=sys.stderr))


if __name__ == "__main__":
    main()
