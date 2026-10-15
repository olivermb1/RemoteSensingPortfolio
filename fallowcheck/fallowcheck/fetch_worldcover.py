"""ESA WorldCover 2021 (10 m land cover) clipped to a bounding box, from the free AWS bucket.

    python -m fallowcheck fetch-worldcover --bbox 33.38 14.20 33.50 14.32 --out data/worldcover.tif

Class 40 is cropland. Needs rasterio.
"""

import math

WC_BUCKET = "https://esa-worldcover.s3.eu-central-1.amazonaws.com"


def tiles(bbox, year=2021):
    w, s, e, n = bbox
    v = "v200" if year == 2021 else "v100"
    out = []
    for lat in range(math.floor(s / 3) * 3, math.ceil(n / 3) * 3, 3):
        for lon in range(math.floor(w / 3) * 3, math.ceil(e / 3) * 3, 3):
            t = f"{'N' if lat >= 0 else 'S'}{abs(lat):02d}{'E' if lon >= 0 else 'W'}{abs(lon):03d}"
            out.append(f"{WC_BUCKET}/{v}/{year}/map/ESA_WorldCover_10m_{year}_{v}_{t}_Map.tif")
    return out


def fetch_worldcover(bbox, out, year=2021, log=print):
    import rasterio
    from rasterio.merge import merge
    srcs = []
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", AWS_NO_SIGN_REQUEST="YES"):
        for u in tiles(bbox, year):
            srcs.append(rasterio.open("/vsicurl/" + u))
        arr, tr = merge(srcs, bounds=bbox)
        prof = srcs[0].profile
        for s in srcs:
            s.close()
    prof.update(height=arr.shape[1], width=arr.shape[2], transform=tr, compress="deflate", tiled=False)
    prof.pop("blockxsize", None)
    prof.pop("blockysize", None)
    with rasterio.open(out, "w", **prof) as d:
        d.write(arr)
    log(f"WorldCover {year} -> {out} ({arr.shape[2]} x {arr.shape[1]})")
    return out
