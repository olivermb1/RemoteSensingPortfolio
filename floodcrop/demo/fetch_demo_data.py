"""Fetch the demo data for the Kano Plains (Kisumu County, Kenya) flood of
late April / early May 2024.

Everything comes from public, no-login AWS buckets:
  * Sentinel-1 RTC gamma0 (VV, VH, MASK), Digital Earth Africa  s3://deafrica-sentinel-1
  * DE Africa cropland mask 2019 (eastern Africa, 10 m)         s3://deafrica-services
  * DE Africa WOfS all-time water frequency (Landsat, 30 m)     s3://deafrica-services
  * ESA WorldCover 2021 v200 (10 m)                             s3://esa-worldcover
  * Overture Maps admin areas (Kenya counties and sub-counties) s3://overturemaps-us-west-2

Sentinel-1 RTC stands in for NASA OPERA DSWx-S1 (LP DAAC/PO.DAAC were not
reachable from the build sandbox). Run `fetch.py dswx` on a machine with an
Earthdata login to use the real OPERA product instead.

Usage:  python demo/fetch_demo_data.py [--out demo/data]
Needs rasterio and pyarrow (pyarrow only for the boundaries).
"""
import argparse
import json
import os
import sys

import numpy as np
import rasterio
from rasterio.merge import merge
from rasterio.warp import transform_bounds
from rasterio.windows import from_bounds

AOI = (34.70, -0.42, 35.20, -0.05)  # lon/lat: Kano Plains, Nyando floodplain, Winam Gulf shore
S1 = "https://deafrica-sentinel-1.s3.af-south-1.amazonaws.com/s1_rtc"
S1_SCENES = {  # date: product id (ascending, relative orbit 130, 12-day repeat)
    "2024-02-24": "066072",
    "2024-03-07": "06666D",
    "2024-04-24": "06811A",
    "2024-05-06": "068803",
}
S1_TILES = ["S01E034", "S01E035"]
DEA = "https://deafrica-services.s3.af-south-1.amazonaws.com"
DEA_TILES = ["x215y076", "x216y076"]
WC = "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_S03E033_Map.tif"
S2 = "https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/36/M/YE"
S2_SCENES = ["S2B_36MYE_20240210_0_L2A", "S2A_36MYE_20240215_0_L2A",   # dry-season baseline
             "S2B_36MYE_20240430_0_L2A", "S2B_36MYE_20240510_0_L2A"]   # flood
S2_BANDS = ["B02", "B03", "B04", "B8A", "B11", "B12"]  # HLS S30 order: blue green red nir swir1 swir2
OVERTURE = "overturemaps-us-west-2/release/2026-09-23.1/theme=divisions/type=division_area/"


def _env():
    ca = "/root/.ccr/ca-bundle.crt"
    kw = dict(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif")
    if os.path.exists(ca) and not os.environ.get("CURL_CA_BUNDLE"):
        kw["CURL_CA_BUNDLE"] = ca
    return rasterio.Env(**kw)


def clip_mosaic(urls, out, bounds_ll=AOI, dtype=None):
    """Window-read each COG over the AOI and mosaic them (first valid wins)."""
    if os.path.exists(out):
        print("exists", out)
        return
    srcs = [rasterio.open("/vsicurl/" + u) for u in urls]
    b = transform_bounds("EPSG:4326", srcs[0].crs, *bounds_ll, densify_pts=21)
    arr, tr = merge(srcs, bounds=b)
    prof = srcs[0].profile.copy()
    prof.update(driver="GTiff", height=arr.shape[1], width=arr.shape[2], transform=tr,
                compress="deflate", tiled=True, blockxsize=256, blockysize=256)
    prof.pop("photometric", None)
    if dtype:
        arr = arr.astype(dtype)
        prof["dtype"] = dtype
    with rasterio.open(out, "w", **prof) as dst:
        dst.write(arr)
    for s in srcs:
        s.close()
    print("wrote", out, arr.shape)


def fetch_s1(out):
    os.makedirs(os.path.join(out, "s1"), exist_ok=True)
    for date, pid in S1_SCENES.items():
        y, m, d = date.split("-")
        for band in ("VV", "VH", "MASK"):
            urls = [f"{S1}/{t}/{y}/{m}/{d}/{pid}/s1_rtc_{pid}_{t}_{y}_{m}_{d}_{band}.tif" for t in S1_TILES]
            clip_mosaic(urls, os.path.join(out, "s1", f"S1_{band}_{y}{m}{d}.tif"))


def fetch_s2(out):
    """6-band HLS-like stack at 20 m (blue, green, red, nir-narrow, swir1, swir2;
    reflectance x 10000) plus the SCL cloud layer, clipped to the AOI. Tile
    36MYE starts at ~34.8E, so the westernmost strip of the AOI is empty."""
    from rasterio.enums import Resampling
    os.makedirs(os.path.join(out, "s2"), exist_ok=True)
    for sid in S2_SCENES:
        date = sid.split("_")[2]
        dst_path = os.path.join(out, "s2", f"S2_SR_{date}.tif")
        if os.path.exists(dst_path):
            print("exists", dst_path)
            continue
        y, m = date[:4], str(int(date[4:6]))
        base = f"{S2}/{y}/{m}/{sid}"
        with rasterio.open(f"/vsicurl/{base}/SCL.tif") as scl_src:
            b = transform_bounds("EPSG:4326", scl_src.crs, *AOI, densify_pts=21)
            w = from_bounds(*b, transform=scl_src.transform).round_offsets().round_lengths()
            w = w.intersection(rasterio.windows.Window(0, 0, scl_src.width, scl_src.height))
            scl = scl_src.read(1, window=w)
            tr = scl_src.window_transform(w)
            prof = dict(driver="GTiff", crs=scl_src.crs, transform=tr, width=scl.shape[1], height=scl.shape[0],
                        compress="deflate", tiled=True, blockxsize=256, blockysize=256)
        stack = []
        for band in S2_BANDS:
            with rasterio.open(f"/vsicurl/{base}/{band}.tif") as src:
                bw = from_bounds(*rasterio.windows.bounds(w, tr), transform=src.transform)
                stack.append(src.read(1, window=bw, out_shape=scl.shape, resampling=Resampling.average))
        with rasterio.open(dst_path, "w", count=6, dtype="uint16", nodata=0, **prof) as dst:
            dst.write(np.stack(stack).astype("uint16"))
            dst.descriptions = ("blue", "green", "red", "nir", "swir1", "swir2")
        with rasterio.open(os.path.join(out, "s2", f"S2_SCL_{date}.tif"), "w", count=1, dtype="uint8", nodata=0, **prof) as dst:
            dst.write(scl, 1)
        print("wrote", dst_path, scl.shape)


def fetch_dea(out):
    cm = [f"{DEA}/crop_mask/eastern/{t[:4]}/{t[4:]}/2019--P1Y/crop_mask_{t}_2019--P1Y_filtered.tif" for t in DEA_TILES]
    clip_mosaic(cm, os.path.join(out, "deafrica_cropmask_2019.tif"))
    wo = [f"{DEA}/wofs_ls_summary_alltime/1-0-0/{t[:4]}/{t[4:]}/1984--P41Y/wofs_ls_summary_alltime_{t}_1984--P41Y_frequency.tif"
          for t in DEA_TILES]
    clip_mosaic(wo, os.path.join(out, "wofs_alltime_frequency.tif"))


def fetch_worldcover(out):
    clip_mosaic([WC], os.path.join(out, "worldcover_2021_v200.tif"))


def fetch_boundaries(out, bounds_ll=AOI, country="KE"):
    """Kenya counties (Overture subtype 'region') and sub-counties ('county')
    that touch the AOI, written as GeoJSON in EPSG:4326."""
    import pyarrow.compute as pc
    import pyarrow.dataset as ds
    import pyarrow.fs as pfs
    from shapely import wkb
    from shapely.geometry import box, mapping

    kw = dict(anonymous=True, region="us-west-2")
    if os.environ.get("HTTPS_PROXY"):
        kw["proxy_options"] = os.environ["HTTPS_PROXY"]
        if os.path.exists("/root/.ccr/ca-bundle.crt"):
            kw["tls_ca_file_path"] = "/root/.ccr/ca-bundle.crt"
    fs = pfs.S3FileSystem(**kw)
    d = ds.dataset(OVERTURE, filesystem=fs, format="parquet")
    xmin, ymin, xmax, ymax = bounds_ll
    f = ((pc.field("country") == country) & pc.field("subtype").isin(["region", "county"])
         & (pc.field("bbox", "xmin") < xmax) & (pc.field("bbox", "xmax") > xmin)
         & (pc.field("bbox", "ymin") < ymax) & (pc.field("bbox", "ymax") > ymin))
    t = d.to_table(columns=["id", "names", "subtype", "region", "geometry"], filter=f).to_pylist()
    aoi = box(*bounds_ll)
    for sub, name in (("region", "zones_counties.geojson"), ("county", "zones_subcounties.geojson")):
        feats = []
        for r in t:
            if r["subtype"] != sub:
                continue
            g = wkb.loads(r["geometry"])
            if not g.intersects(aoi):
                continue
            feats.append({"type": "Feature", "geometry": mapping(g),
                          "properties": {"name": r["names"]["primary"], "overture_id": r["id"],
                                         "subtype": sub, "region": r["region"]}})
        with open(os.path.join(out, name), "w") as fh:
            json.dump({"type": "FeatureCollection", "features": feats}, fh)
        print("wrote", name, len(feats), "features:", sorted(f["properties"]["name"] for f in feats))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
    ap.add_argument("--skip-boundaries", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    with _env():
        fetch_s1(a.out)
        fetch_s2(a.out)
        fetch_dea(a.out)
        fetch_worldcover(a.out)
    if not a.skip_boundaries:
        fetch_boundaries(a.out)
