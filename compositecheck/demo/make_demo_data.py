"""Download the demo stack: Nakuru, Kenya, January to June 2024.

Builds an HLS-like 30 m stack from free, no-login sources:
  Sentinel-2 L2A COGs, AWS bucket sentinel-cogs (Element 84), tile 36MZE
  Landsat 8/9 Collection 2 Level-2, AWS bucket deafrica-landsat (Digital Earth Africa), WRS-2 169/060
  DE Africa Sentinel-2 GeoMAD, first half of 2024, tile x217y076 (bucket deafrica-services)

HLS itself (NASA LP DAAC) was not reachable from the build sandbox, so the
script imitates the parts of HLS that Composite Check relies on:
  * one 30 m UTM grid for both sensors (S2 averaged from 10/20 m)
  * Sentinel-2 bandpass-adjusted to Landsat 8 OLI with the HLS v2.0
    coefficients (hls.gsfc.nasa.gov/algorithms/bandpass-adjustment)
  * cloud masks recoded to HLS Fmask bits
It does NOT apply the HLS BRDF (view-angle) normalisation or the HLS
atmospheric correction, so Landsat vs Sentinel-2 residuals here should be
somewhat larger than in real HLS.

Writes to demo/data/:
  scenes/<id>.tif         6 bands (blue, green, red, nir, swir1, swir2), reflectance x 10000, int16, nodata -9999
  scenes/<id>_Fmask.tif   HLS-style Fmask bits (uint8, 255 = no data)
  manifest.csv            path, fmask, date, sensor, scene_id
  geomad_2024H1.tif       GeoMAD median bands (same 6) + COUNT on the same grid
"""

import csv
import os
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.warp import reproject, transform_bounds
from rasterio.windows import from_bounds

os.environ.setdefault("CURL_CA_BUNDLE", "/root/.ccr/ca-bundle.crt")
os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("GDAL_HTTP_MAX_RETRY", "4")
os.environ.setdefault("GDAL_HTTP_RETRY_DELAY", "2")

BBOX = (36.00, -0.40, 36.12, -0.28)  # W S E N: Nakuru town, farmland, lake shore
START, END = "2024-01-01", "2024-06-30"
CRS = "EPSG:32736"  # UTM 36S, the Sentinel-2 tile's CRS
RES = 30.0

S2_BUCKET = "https://sentinel-cogs.s3.us-west-2.amazonaws.com"
S2_PREFIX = "sentinel-s2-l2a-cogs/36/M/ZE/2024"
S2_BANDS = ["B02", "B03", "B04", "B8A", "B11", "B12"]
LS_BUCKET = "https://deafrica-landsat.s3.af-south-1.amazonaws.com"
LS_PREFIX = "collection02/level-2/standard/oli-tirs/2024/169/060"
LS_BANDS = ["SR_B2", "SR_B3", "SR_B4", "SR_B5", "SR_B6", "SR_B7"]
GM = ("https://deafrica-services.s3.af-south-1.amazonaws.com/gm_s2_semiannual/1-0-0/x217/y076/"
      "2024-01--P6M/gm_s2_semiannual_x217y076_2024-01--P6M_{}.tif")

# HLS v2.0 bandpass adjustment, MSI -> OLI: (slope, offset) per band
BANDPASS = {
    "S2A": [(0.9778, -0.004), (1.0053, -0.0009), (0.9765, 0.0009), (0.9983, -0.0001), (0.9987, -0.0011), (1.003, -0.0012)],
    "S2B": [(0.9778, -0.004), (1.0075, -0.0008), (0.9761, 0.001), (0.9966, 0.0), (1.000, -0.0003), (0.9867, 0.0004)],
}

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "data")
SCN = os.path.join(OUT, "scenes")
os.makedirs(SCN, exist_ok=True)


def list_prefixes(bucket, prefix):
    url = f"{bucket}/?list-type=2&prefix={prefix}&delimiter=/"
    with urllib.request.urlopen(url, timeout=60) as r:
        xml = r.read().decode()
    return re.findall(r"<Prefix>([^<]+)</Prefix>", xml)[1:]


def make_grid():
    b = transform_bounds("EPSG:4326", CRS, *BBOX)
    x0, y1 = np.floor(b[0] / RES) * RES, np.ceil(b[3] / RES) * RES
    w, h = int(np.ceil((b[2] - x0) / RES)), int(np.ceil((y1 - b[1]) / RES))
    return from_origin(x0, y1, RES, RES), w, h


TRANSFORM, W, H = make_grid()
GRID_BOUNDS = (TRANSFORM.c, TRANSFORM.f - H * RES, TRANSFORM.c + W * RES, TRANSFORM.f)


def warp(url, resampling, dtype="float32", src_nodata=None):
    """Read only the window of a remote COG that covers the grid, then warp it on."""
    with rasterio.open("/vsicurl/" + url) as src:
        b = transform_bounds(CRS, src.crs, *GRID_BOUNDS)
        m = 3 * max(abs(src.transform.a), abs(src.transform.e))
        win = from_bounds(b[0] - m, b[1] - m, b[2] + m, b[3] + m, transform=src.transform)
        win = win.round_offsets().round_lengths().intersection(rasterio.windows.Window(0, 0, src.width, src.height))
        arr = src.read(1, window=win)
        nd = src.nodata if src_nodata is None else src_nodata
        dst = np.full((H, W), np.nan if dtype == "float32" else 0, dtype)
        reproject(arr.astype(dtype) if dtype == "float32" else arr, dst,
                  src_transform=src.window_transform(win), src_crs=src.crs,
                  dst_transform=TRANSFORM, dst_crs=CRS, resampling=resampling,
                  src_nodata=nd, dst_nodata=np.nan if dtype == "float32" else 0)
    return dst


def fmask_bits(cirrus, cloud, adjacent, shadow, snow, water, aerosol=None):
    f = (cirrus.astype(np.uint8) << 0) | (cloud.astype(np.uint8) << 1) | (adjacent.astype(np.uint8) << 2) \
        | (shadow.astype(np.uint8) << 3) | (snow.astype(np.uint8) << 4) | (water.astype(np.uint8) << 5)
    if aerosol is not None:
        f |= (aerosol.astype(np.uint8) & 3) << 6
    return f


def write_scene(sid, refl, fmask):
    prof = dict(driver="GTiff", width=W, height=H, crs=CRS, transform=TRANSFORM, compress="deflate",
                tiled=True, blockxsize=256, blockysize=256)
    data = np.where(np.isfinite(refl), np.round(refl * 10000), -9999).astype("int16")
    with rasterio.open(os.path.join(SCN, sid + ".tif"), "w", count=6, dtype="int16", nodata=-9999, **prof) as d:
        d.write(data)
        d.descriptions = ("blue", "green", "red", "nir", "swir1", "swir2")
    with rasterio.open(os.path.join(SCN, sid + "_Fmask.tif"), "w", count=1, dtype="uint8", nodata=255, **prof) as d:
        d.write(fmask, 1)


def do_s2(folder):
    sid = folder.rstrip("/").split("/")[-1]  # S2A_36MZE_20240105_0_L2A
    base = f"{S2_BUCKET}/{folder}"
    sensor = sid[:3]
    refl = np.stack([warp(f"{base}{b}.tif", Resampling.average, src_nodata=0) for b in S2_BANDS]) * 1e-4
    scl = warp(f"{base}SCL.tif", Resampling.nearest, dtype="uint8", src_nodata=0)
    # any 20 m SCL pixel flagged inside the 30 m cell flags the cell (30 m is not a multiple of 20 m, so use nearest + 1 px dilation later in the tool)
    nodata = (scl == 0) | (scl == 1) | ~np.all(np.isfinite(refl), axis=0)
    for i, (a, o) in enumerate(BANDPASS[sensor]):
        refl[i] = refl[i] * a + o
    refl[:, nodata] = np.nan
    f = fmask_bits(scl == 10, (scl == 8) | (scl == 9), np.zeros_like(nodata), scl == 3, scl == 11, scl == 6)
    f[nodata] = 255
    return sid, sid[10:18], sensor, refl, f


def do_ls(folder):
    sid = folder.rstrip("/").split("/")[-1]  # LC08_L2SP_169060_20240105_20240113_02_T1
    base = f"{LS_BUCKET}/{folder}{sid}_"
    sensor = "L" + sid[3]
    refl = np.stack([warp(base + b + ".TIF", Resampling.bilinear, src_nodata=0) for b in LS_BANDS]) * 2.75e-5 - 0.2
    qa = warp(base + "QA_PIXEL.TIF", Resampling.nearest, dtype="uint16", src_nodata=1)
    aer = warp(base + "SR_QA_AEROSOL.TIF", Resampling.nearest, dtype="uint8", src_nodata=1)
    bit = lambda a, n: (a >> n) & 1 == 1  # noqa: E731
    nodata = (qa == 0) | bit(qa, 0) | ~np.all(np.isfinite(refl), axis=0)
    refl[:, nodata] = np.nan
    f = fmask_bits(bit(qa, 2), bit(qa, 3), bit(qa, 1), bit(qa, 4), bit(qa, 5), bit(qa, 7), (aer >> 6) & 3)
    f[nodata] = 255
    return sid, sid[17:25], sensor, refl, f


def main():
    jobs = []
    for m in range(1, 7):
        folders = list_prefixes(S2_BUCKET, f"{S2_PREFIX}/{m}/")
        # keep the latest reprocessing (_1 over _0) for each date and satellite
        latest = {}
        for f in sorted(folders):
            sid = f.rstrip("/").split("/")[-1]
            latest[sid[:18]] = f
        jobs += [("s2", f) for f in latest.values()]
    for f in list_prefixes(LS_BUCKET, LS_PREFIX + "/"):
        d = f.rstrip("/").split("/")[-1][17:25]
        if START.replace("-", "") <= d <= END.replace("-", ""):
            jobs.append(("ls", f))
    print(f"{len(jobs)} scenes to read", file=sys.stderr)

    def run(job):
        kind, f = job
        try:
            sid, date, sensor, refl, fm = (do_s2 if kind == "s2" else do_ls)(f)
        except Exception as e:  # keep going; report at the end
            return job, None, str(e)
        valid = np.mean(fm != 255)
        if valid < 0.01:
            return job, None, "no data over the area"
        write_scene(sid, refl, fm)
        clear = np.mean((fm != 255) & ((fm & 0b1111) == 0))
        return job, (sid, date, sensor, valid, clear), None

    rows, skipped = [], []
    with ThreadPoolExecutor(8) as ex:
        for job, row, err in ex.map(run, jobs):
            if row:
                rows.append(row)
                print(f"{row[0]}: valid {row[3]:.0%}, clear {row[4]:.0%}", file=sys.stderr)
            else:
                skipped.append((job[1], err))
    rows.sort(key=lambda r: (r[1], r[0]))
    with open(os.path.join(OUT, "manifest.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["path", "fmask", "date", "sensor", "scene_id"])
        for sid, date, sensor, _, _ in rows:
            w.writerow([f"scenes/{sid}.tif", f"scenes/{sid}_Fmask.tif",
                        f"{date[:4]}-{date[4:6]}-{date[6:]}", sensor, sid])
    for f, err in skipped:
        print("skipped", f, err, file=sys.stderr)

    # GeoMAD: median bands and COUNT, averaged (bands) / nearest (COUNT) onto the 30 m grid
    gm_bands = ["B02", "B03", "B04", "B8A", "B11", "B12"]
    gm = [warp(GM.format(b), Resampling.average) for b in gm_bands]
    count = warp(GM.format("COUNT"), Resampling.nearest, dtype="uint16")
    prof = dict(driver="GTiff", width=W, height=H, crs=CRS, transform=TRANSFORM, compress="deflate")
    with rasterio.open(os.path.join(OUT, "geomad_2024H1.tif"), "w", count=7, dtype="int16", nodata=-9999, **prof) as d:
        for i, a in enumerate(gm):
            d.write(np.where(np.isfinite(a), np.round(a), -9999).astype("int16"), i + 1)
        d.write(count.astype("int16"), 7)
        d.descriptions = ("blue", "green", "red", "nir", "swir1", "swir2", "COUNT")
    print(f"done: {len(rows)} scenes, {len(skipped)} skipped -> {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
