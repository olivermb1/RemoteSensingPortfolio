"""Download NASA HLS v2.0 (Landsat L30 + Sentinel-2 S30) for a small area.

    python -m timeprofile fetch-hls --bbox 37.30 -0.70 37.34 -0.66 --start 2023-01-01 --end 2024-12-31 --out hls/

Needs a free NASA Earthdata login (urs.earthdata.nasa.gov) in ~/.netrc and the
`earthaccess` package. Reads only the window over --bbox of the bands needed
(blue, green, red, nir, swir1, swir2) plus Fmask, and keeps the HLS file
names, so the folder goes straight into `timeprofile extract`. Adapted from
Composite Check's fetcher. Untested here: NASA servers are not reachable from
the sandbox this was written in.
"""

import os
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

from .catalog import HLS_RE
from .sensors import HLS_BANDS

SHORT_NAMES = {"L30": "HLSL30", "S30": "HLSS30"}
GDAL_ENV = dict(GDAL_HTTP_COOKIEFILE=os.path.expanduser("~/.timeprofile_cookies.txt"),
                GDAL_HTTP_COOKIEJAR=os.path.expanduser("~/.timeprofile_cookies.txt"),
                GDAL_HTTP_NETRC="YES", GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
                CPL_VSIL_CURL_ALLOWED_EXTENSIONS="TIF", GDAL_HTTP_MAX_RETRY="4", GDAL_HTTP_RETRY_DELAY="2")
NEED = ["blue", "green", "red", "nir", "swir1", "swir2"]


def clip_one(url, bbox, dest):
    import rasterio
    from rasterio.warp import transform_bounds
    from rasterio.windows import Window, from_bounds

    if os.path.exists(dest):
        return "skip"
    with rasterio.Env(**GDAL_ENV), rasterio.open(url) as src:
        b = transform_bounds("EPSG:4326", src.crs, *bbox)
        win = from_bounds(*b, transform=src.transform).round_offsets().round_lengths()
        try:
            win = win.intersection(Window(0, 0, src.width, src.height))
        except Exception:
            return "outside"
        data = src.read(1, window=win)
        prof = src.profile.copy()
        prof.update(driver="GTiff", width=int(win.width), height=int(win.height),
                    transform=src.window_transform(win), compress="deflate", tiled=False)
        for k in ("blockxsize", "blockysize", "interleave"):
            prof.pop(k, None)
    with rasterio.open(dest + ".part", "w", **prof) as dst:
        dst.write(data, 1)
    os.replace(dest + ".part", dest)
    return "ok"


def fetch(bbox, start, end, out_dir, products=("L30", "S30"), tile=None, max_cloud=None, workers=8, log=print):
    import earthaccess

    earthaccess.login(persist=True)
    kw = dict(short_name=[SHORT_NAMES[p] for p in products], version="2.0", bounding_box=tuple(bbox),
              temporal=(str(start), str(end)), count=-1)
    if max_cloud is not None:
        kw["cloud_cover"] = (0, max_cloud)
    gran = {}
    for g in earthaccess.search_data(**kw):
        for url in g.data_links(access="external"):
            m = HLS_RE.search(os.path.basename(url))
            if not m:
                continue
            prod = m["prod"].upper()
            need = {HLS_BANDS[prod][b] for b in NEED} | {"Fmask"}
            if m["band"] in need:
                gid = os.path.basename(url)[: m.start("band") - 1]
                gran.setdefault(gid, {"_tile": m["tile"]})[m["band"]] = url
    if not gran:
        raise SystemExit("no HLS granules found for that area and period")
    tiles = Counter(f["_tile"] for f in gran.values())
    tile = (tile or tiles.most_common(1)[0][0]).lstrip("T")
    if len(tiles) > 1:
        log(f"granules from tiles {dict(tiles)}; using {tile} (choose with --tile)")
    jobs = []
    for gid, files in gran.items():
        if files["_tile"] != tile:
            continue
        os.makedirs(os.path.join(out_dir, gid), exist_ok=True)
        for band, url in files.items():
            if band != "_tile":
                jobs.append((url, os.path.join(out_dir, gid, os.path.basename(url))))
    log(f"{sum(1 for g in gran.values() if g['_tile'] == tile)} granules on tile {tile}, {len(jobs)} files")
    status, failed, t0 = Counter(), [], time.time()
    with ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(clip_one, url, bbox, dest): url for url, dest in jobs}
        for i, f in enumerate(as_completed(futs), 1):
            try:
                status[f.result()] += 1
            except Exception as e:
                failed.append((futs[f], repr(e)))
            if i % 50 == 0 or i == len(jobs):
                log(f"  {i}/{len(jobs)} files, {time.time() - t0:.0f} s")
    if failed:
        log(f"{len(failed)} files failed, e.g. {failed[0][0]}: {failed[0][1]}")
        if any("401" in e or "403" in e for _, e in failed):
            log("authorisation failed: check ~/.netrc has machine urs.earthdata.nasa.gov")
    log(f"done: {dict(status)} -> {out_dir}")
    return status
