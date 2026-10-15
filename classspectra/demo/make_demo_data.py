"""Download a small demo area: Nakuru, Kenya (Lake Nakuru, town, farmland, forest).

Sources (free, no login):
  Sentinel-2 L2A COGs, AWS Open Data bucket sentinel-cogs (Element 84)
  ESA WorldCover 10 m 2020 (v100) and 2021 (v200), AWS bucket esa-worldcover

Writes to demo/data/:
  nakuru_s2_20240215.tif     10 bands (B02..B12) at 10 m, raw DN (scale 1e-4, offset -0.1)
  nakuru_s2_scl.tif          scene classification layer (20 m)
  nakuru_s2_30m.tif          same bands averaged to 30 m (HLS-like grid, tests purity filter)
  worldcover_2020_v100.tif   WorldCover clipped to the area
  worldcover_2021_v200.tif
"""

import os
import sys

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import transform_bounds
from rasterio.windows import from_bounds

os.environ.setdefault("CURL_CA_BUNDLE", "/root/.ccr/ca-bundle.crt")
os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")

BBOX = (35.98, -0.42, 36.18, -0.20)  # W S E N
SCENE = "S2A_36MZE_20240215_0_L2A"  # 1.6% cloud, full coverage of the area
BASE = f"https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/36/M/ZE/2024/2/{SCENE}"
BANDS = ["B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B11", "B12"]
# The area straddles 36 E, so it needs two 3x3 degree WorldCover tiles
WC_BASE = "https://esa-worldcover.s3.eu-central-1.amazonaws.com"
WC = {
    "worldcover_2020_v100.tif": [f"{WC_BASE}/v100/2020/map/ESA_WorldCover_10m_2020_v100_{t}_Map.tif"
                                 for t in ("S03E033", "S03E036")],
    "worldcover_2021_v200.tif": [f"{WC_BASE}/v200/2021/map/ESA_WorldCover_10m_2021_v200_{t}_Map.tif"
                                 for t in ("S03E033", "S03E036")],
}

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(out, exist_ok=True)


def vsi(url):
    return "/vsicurl/" + url


# Reference 10 m grid from B04
with rasterio.open(vsi(f"{BASE}/B04.tif")) as ref:
    b = transform_bounds("EPSG:4326", ref.crs, *BBOX)
    win = from_bounds(*b, transform=ref.transform).round_offsets().round_lengths()
    h, w = int(win.height), int(win.width)
    prof = ref.profile.copy()
    prof.update(driver="GTiff", height=h, width=w, transform=ref.window_transform(win),
                count=len(BANDS), compress="deflate", predictor=2, tiled=True,
                blockxsize=512, blockysize=512, nodata=0)
    bounds = rasterio.windows.bounds(win, ref.transform)

stack = np.zeros((len(BANDS), h, w), "uint16")
for i, band in enumerate(BANDS):
    with rasterio.open(vsi(f"{BASE}/{band}.tif")) as src:
        wsrc = from_bounds(*bounds, transform=src.transform)
        stack[i] = src.read(1, window=wsrc, out_shape=(h, w), resampling=Resampling.nearest)
    print("read", band, file=sys.stderr)

with rasterio.open(os.path.join(out, "nakuru_s2_20240215.tif"), "w", **prof) as dst:
    dst.write(stack)
    dst.descriptions = tuple(BANDS)

with rasterio.open(vsi(f"{BASE}/SCL.tif")) as src:
    wsrc = from_bounds(*bounds, transform=src.transform).round_offsets().round_lengths()
    scl = src.read(1, window=wsrc)
    p = src.profile.copy()
    p.update(driver="GTiff", height=scl.shape[0], width=scl.shape[1],
             transform=src.window_transform(wsrc), compress="deflate", tiled=False)
    with rasterio.open(os.path.join(out, "nakuru_s2_scl.tif"), "w", **p) as dst:
        dst.write(scl, 1)

# 30 m aggregate: mean of 3x3 blocks of valid reflectance, written back as DN
h3, w3 = h // 3, w // 3
refl = stack[:, :h3 * 3, :w3 * 3].astype("float32")
refl[refl == 0] = np.nan
agg = np.nanmean(refl.reshape(len(BANDS), h3, 3, w3, 3), axis=(2, 4))
agg = np.nan_to_num(np.round(agg), nan=0).astype("uint16")
p30 = prof.copy()
p30.update(height=h3, width=w3, transform=prof["transform"] * rasterio.Affine.scale(3))
with rasterio.open(os.path.join(out, "nakuru_s2_30m.tif"), "w", **p30) as dst:
    dst.write(agg)
    dst.descriptions = tuple(BANDS)

# WorldCover in its native EPSG:4326 grid, mosaicked and clipped with a small margin
from rasterio.merge import merge  # noqa: E402

for name, urls in WC.items():
    srcs = [rasterio.open(vsi(u)) for u in urls]
    m = 0.005
    lc, tr = merge(srcs, bounds=(BBOX[0] - m, BBOX[1] - m, BBOX[2] + m, BBOX[3] + m))
    p = srcs[0].profile.copy()
    p.update(driver="GTiff", height=lc.shape[1], width=lc.shape[2], transform=tr,
             compress="deflate", tiled=False)
    with rasterio.open(os.path.join(out, name), "w", **p) as dst:
        dst.write(lc)
        try:
            dst.write_colormap(1, srcs[0].colormap(1))
        except ValueError:
            pass
    for s_ in srcs:
        s_.close()
    print("read", name, file=sys.stderr)

print("done:", out)
