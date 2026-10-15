"""Build demo/files/: a folder of small HLS files with the problems people
really hit, for `python -m hlsdoctor files demo/files`.

Real pixels come from two public sources that need no login:
  - an HLS S30 band from NASA OPERA's public input bucket (northern tile T10TCT)
  - the southern-hemisphere HLS L30 Fmask in ../qamaskbuilder/demo/data (T19JHN)
Each is cut to a small window, keeping NASA's metadata and CRS as they are.
"""

import os
import shutil
import sys

import rasterio
from rasterio.windows import Window

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "files")
S30 = ("https://opera-pst-rs-pop1.s3.us-west-2.amazonaws.com/inputs/HLS_S30/"
       "HLS.S30.T10TCT.2021345T191811.v2.0-r1/HLS.S30.T10TCT.2021345T191811.v2.0.{band}.tif")
FMASK = os.path.join(HERE, "..", "..", "qamaskbuilder", "demo", "data",
                     "HLS.L30.T19JHN.2024279T141847.v2.0.Fmask.tif")


def crop(src_path, dest, size=256, cog=True, drop_nodata=False, env=None):
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", **(env or {})), rasterio.open(src_path) as s:
        w = Window(1024, 1024, size, size)
        data = s.read(window=w)
        prof = s.profile.copy()
        prof.update(width=size, height=size, transform=s.window_transform(w), compress="deflate")
        if cog:
            prof.update(tiled=True, blockxsize=128, blockysize=128)
        else:
            prof.update(tiled=False)
            for k in ("blockxsize", "blockysize"):
                prof.pop(k, None)
        if drop_nodata:
            prof["nodata"] = None
        tags, scales, offsets = s.tags(), s.scales, s.offsets
    with rasterio.open(dest, "w", **prof) as d:
        d.write(data)
        d.update_tags(**tags)
        d.scales, d.offsets = scales, offsets
        if cog:
            d.build_overviews([2, 4], rasterio.enums.Resampling.nearest)


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT)
    j = lambda n: os.path.join(OUT, n)
    print("cutting real files ...", file=sys.stderr)
    good = j("HLS.S30.T10TCT.2021345T191811.v2.0.B8A.tif")
    crop("/vsicurl/" + S30.format(band="B8A"), good)                         # fine, apart from no EPSG code
    crop("/vsicurl/" + S30.format(band="B04"), j("HLS.S30.T10TCT.2021345T191811.v2.0.B04.tif"),
         cog=False, drop_nodata=True)                                       # re-saved copy that lost no-data
    if os.path.exists(FMASK):
        crop(FMASK, j("HLS.L30.T19JHN.2024279T141847.v2.0.Fmask.tif"))    # southern CRS label
        crop(FMASK, j("HLS.L30.T19JHM.2024279T141847.v2.0.Fmask.tif"))    # same date on a neighbouring tile (renamed copy)
    else:
        print(f"skipped the southern Fmask: {FMASK} not found", file=sys.stderr)
    # What failed downloads leave behind
    with open(j("HLS.S30.T10TCT.2021345T191811.v2.0.B03.tif"), "w") as f:   # the login page, saved as .tif
        f.write("<!DOCTYPE html>\n<html><head><title>Earthdata Login</title></head>"
                "<body><form action=\"/login\">Username Password</form></body></html>\n")
    with open(j("HLS.L30.T19JHN.2024279T141847.v2.0.B05.tif"), "w") as f:   # S3 refusal, saved as .tif
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<Error><Code>AccessDenied</Code>'
                "<Message>Access Denied</Message></Error>")
    with open(good, "rb") as f:                                             # download cut off part way
        part = f.read()[: 6000]
    with open(j("HLS.S30.T10TCT.2021345T191811.v2.0.B02.tif"), "wb") as f:
        f.write(part)
    open(j("HLS.S30.T10TCT.2021345T191811.v2.0.B11.tif"), "w").close()      # empty
    shutil.copy(good, j("HLS.S30.T10TCT.2021345T191811.v1.5.B8A.tif"))     # old version name
    for n in sorted(os.listdir(OUT)):
        if n.endswith(".aux.xml"):
            os.remove(j(n))
    print("\n".join(f"{os.path.getsize(j(n)):>8}  {n}" for n in sorted(os.listdir(OUT))))


if __name__ == "__main__":
    main()
