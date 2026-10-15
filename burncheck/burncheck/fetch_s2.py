"""Download Sentinel-2 L2A for a small area from the AWS Open Data bucket
(sentinel-cogs, Element 84). Free, no login.

    python -m burncheck fetch-s2 --bbox 37.30 -0.70 37.34 -0.66 --start 2023-01-01 --end 2024-12-31 --out scenes/

Only the window over --bbox is read from each cloud-optimised GeoTIFF, so a
few km2 over two years costs tens of megabytes. Each scene becomes one
multi-band GeoTIFF (bands named blue, green, red, nir, swir1, swir2 + SCL)
that burncheck reads directly. Copied from tools/timeprofile. Needs rasterio.
"""

import datetime as dt
import json
import os
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np

from .mgrs import mgrs_tiles
S2_BANDS = {"blue": "B02", "green": "B03", "red": "B04", "nir": "B08", "swir1": "B11", "swir2": "B12"}

BUCKET = "https://sentinel-cogs.s3.us-west-2.amazonaws.com"
PREFIX = "sentinel-s2-l2a-cogs"
DEFAULT_BANDS = ["blue", "green", "red", "nir", "swir1", "swir2"]
GDAL_ENV = dict(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif",
                GDAL_HTTP_MAX_RETRY="4", GDAL_HTTP_RETRY_DELAY="2", AWS_NO_SIGN_REQUEST="YES")
SCENE_RE = re.compile(r"/(S2[ABCD])_(\d{2}[A-Z]{3})_(\d{8})_(\d+)_L2A/$")


def _get(url, tries=4):
    for k in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return r.read()
        except Exception:
            if k == tries - 1:
                raise
            time.sleep(2 ** k)


def list_scenes(tile, start, end):
    """[(scene_id, date, base_url)] on one MGRS tile between start and end (dates)."""
    zone, band, sq = tile[:2].lstrip("0"), tile[2], tile[3:]
    out = {}
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        url = f"{BUCKET}/?list-type=2&delimiter=/&prefix={PREFIX}/{zone}/{band}/{sq}/{y}/{m}/"
        xml = _get(url).decode()
        for p in re.findall(r"<Prefix>([^<]+)</Prefix>", xml):
            mm = SCENE_RE.search(p)
            if not mm:
                continue
            d = dt.datetime.strptime(mm[3], "%Y%m%d").date()
            if start <= d <= end:
                key = (mm[1], d)  # keep the latest reprocessing (_1_ over _0_)
                if key not in out or int(mm[4]) > out[key][0]:
                    out[key] = (int(mm[4]), p.rstrip("/").split("/")[-1], d, f"{BUCKET}/{p}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return sorted([v[1:] for v in out.values()], key=lambda t: (t[1], t[0]))


def fetch_one(scene_id, base, bbox, out_dir, bands=DEFAULT_BANDS, res=10, max_cloud=100.0, min_clear=5.0):
    """Write <out_dir>/<scene_id>.tif. Returns 'ok', 'skip', 'cloudy', 'empty' or 'outside'."""
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.warp import transform_bounds
    from rasterio.windows import Window, from_bounds

    dest = os.path.join(out_dir, scene_id + ".tif")
    if os.path.exists(dest):
        return "skip"
    item = json.loads(_get(f"{base}{scene_id}.json"))
    props = item.get("properties", {})
    if props.get("eo:cloud_cover", 0) > max_cloud:
        return "cloudy"
    # Element 84 sets boa_offset_applied=True when it has ALREADY removed the +1000 DN offset that
    # ESA adds from processing baseline 04.00; those files need no offset (despite raster:bands
    # still listing -0.1). Checked on 37MCV Jan 2024: dark pixels sit near DN 370, impossible with the offset in.
    applied = props.get("earthsearch:boa_offset_applied")
    baseline = float(props.get("s2:processing_baseline", "0") or 0)
    offset = -0.1 if (applied is False and baseline >= 4) else 0.0
    ref_code = "B04" if res == 10 else "B8A"
    with rasterio.Env(**GDAL_ENV):
        with rasterio.open(f"/vsicurl/{base}{ref_code}.tif") as ref:
            b = transform_bounds("EPSG:4326", ref.crs, *bbox)
            win = from_bounds(*b, transform=ref.transform).round_offsets().round_lengths()
            try:
                win = win.intersection(Window(0, 0, ref.width, ref.height))
            except Exception:
                return "outside"
            if win.width < 1 or win.height < 1:
                return "outside"
            bounds = rasterio.windows.bounds(win, ref.transform)
            h, w = int(win.height), int(win.width)
            prof = dict(driver="GTiff", width=w, height=h, count=len(bands) + 1, dtype="uint16", nodata=0,
                        crs=ref.crs, transform=ref.window_transform(win), compress="deflate", predictor=2)

        def read(code, resampling):
            with rasterio.open(f"/vsicurl/{base}{code}.tif") as src:
                wsrc = from_bounds(*bounds, transform=src.transform)
                return src.read(1, window=wsrc, out_shape=(h, w), resampling=resampling, boundless=True, fill_value=0)

        scl = read("SCL", Resampling.nearest)
        valid = scl > 0
        if not valid.any():
            return "empty"
        clear = np.isin(scl, [2, 4, 5, 6, 7]).sum() / valid.sum() * 100
        if clear < min_clear:
            return "cloudy"
        stack = []
        if offset:
            # Some items say the offset is still in the DN when it is not (seen on S2C, Dec 2024):
            # with the offset in, clear land never has blue DN below 1000.
            blue = read("B02", Resampling.nearest)
            if np.mean(blue[np.isin(scl, [4, 5])] < 1000) > 0.05:
                offset = 0.0
        for name in bands:
            code = S2_BANDS[name]
            native = 10 if code in ("B02", "B03", "B04", "B08") else 20
            stack.append(read(code, Resampling.average if native < res else Resampling.nearest))
    tmp = dest + ".part"
    with rasterio.open(tmp, "w", **prof) as dst:
        for i, arr in enumerate(stack + [scl], 1):
            dst.write(arr.astype("uint16"), i)
            dst.set_band_description(i, (bands + ["SCL"])[i - 1])
        dst.update_tags(TP_SENSOR=scene_id[:3], TP_DATE=scene_id.split("_")[2], TP_TILE=scene_id.split("_")[1],
                        TP_SCALE="0.0001", TP_OFFSET=str(offset), TP_CLOUD_TILE=str(props.get("eo:cloud_cover")),
                        TP_CLEAR_AOI=f"{clear:.1f}", TP_SOURCE=base)
    os.replace(tmp, dest)
    return "ok"


def fetch(bbox, start, end, out_dir, bands=DEFAULT_BANDS, res=10, tiles=None, max_cloud=100.0, min_clear=5.0,
          workers=8, log=print):
    start = dt.date.fromisoformat(start) if isinstance(start, str) else start
    end = dt.date.fromisoformat(end) if isinstance(end, str) else end
    os.makedirs(out_dir, exist_ok=True)
    tiles = tiles or mgrs_tiles(bbox)
    log(f"tiles: {', '.join(tiles)}")
    scenes = []
    for t in tiles:
        found = list_scenes(t, start, end)
        log(f"  {t}: {len(found)} scenes {start} to {end}")
        scenes += found
    status, failed, t0 = {}, [], time.time()
    with ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(fetch_one, sid, base, bbox, out_dir, bands, res, max_cloud, min_clear): sid
                for sid, _, base in scenes}
        for i, f in enumerate(as_completed(futs), 1):
            try:
                s = f.result()
                status[s] = status.get(s, 0) + 1
            except Exception as e:
                failed.append((futs[f], repr(e)))
            if i % 20 == 0 or i == len(futs):
                log(f"  {i}/{len(futs)} scenes, {time.time() - t0:.0f} s")
    if failed:
        log(f"{len(failed)} scenes failed, e.g. {failed[0][0]}: {failed[0][1]}")
    log(f"done: {status} -> {out_dir}")
    return status
