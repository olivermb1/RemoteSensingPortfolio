"""Build the synthetic demo: 12 ECOSTRESS-style tiled LST scenes over the
Kenyan Rift lakes (Nakuru, Elmenteita and the north of Naivasha), some of
them shifted the way a badly geolocated scene would be.

The landscape is real: ESA WorldCover 2021 (10 m, read from its public AWS
bucket and cached at 30 m in data/worldcover_rift_30m.tif). Temperatures,
clouds, flags and shifts are invented. File names, layer names, the 70 m UTM
grid and the L1B GEO metadata layout follow ECOSTRESS collection 2, but the
.h5 files hold only the metadata group, not real geolocation arrays.

Run from anywhere: python demo/make_demo_data.py
"""

import json
import os
from datetime import datetime

import numpy as np
import rasterio
from rasterio import warp
from rasterio.transform import Affine, from_origin

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
SCENES = os.path.join(DATA, "scenes")
WC_CACHE = os.path.join(DATA, "worldcover_rift_30m.tif")
WC_URL = ("/vsicurl/https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
          "ESA_WorldCover_10m_2021_v200_S03E036_Map.tif")
LON0, LAT0, LON1, LAT1 = 36.0, -0.95, 36.45, -0.12

TILE = "37MAV"
CRS = "EPSG:32737"
RES = 70.0
X0, Y0 = 166040.0, 9975010.0   # upper-left of the demo subset (synthetic; real tiles are 109.8 km)
W, H = 620, 1140                # 43 x 80 km
PAD = 90                        # px of extra landscape around the subset, so shifts don't wrap

# (date-time UTC, NASA flag, OrbitCorrectionPerformed, true shift east m, true shift north m,
#  cloud fraction, FieldOfViewObstruction, where the flag is stored)
PLAN = [
    ("2025-01-06T07:52:11", "best", True, 0, 0, 0.10, False, "geo"),
    ("2025-01-19T13:10:40", "best", True, 35, -20, 0.05, False, "geo"),
    ("2025-02-03T09:40:02", "good", True, 60, 40, 0.20, False, "geo"),
    ("2025-02-17T11:05:57", "suspect", False, 2300, -1400, 0.15, False, "geo"),
    ("2025-03-04T15:30:19", "poor", False, -4200, 3100, 0.10, False, "geo"),
    ("2025-03-21T08:20:44", "good", True, 40, -30, 0.25, False, "sidecar"),
    ("2025-04-08T21:40:08", "suspect", False, 50, 20, 0.15, False, "geo"),
    ("2025-05-27T10:15:31", "best", True, 0, 30, 0.30, False, "geo"),
    ("2025-06-12T12:44:13", "good", True, -45, 0, 0.10, True, "summary"),
    ("2025-06-25T09:02:50", None, None, 0, 0, 0.10, False, "none"),
    ("2025-07-10T14:18:26", None, None, 1100, 600, 0.20, False, "none"),
    ("2025-08-02T08:47:05", "best", True, 0, 0, 0.85, True, "geo"),
]
# Class temperature offsets (K) by WorldCover class, daytime. Water flips sign at night.
OFFSET = {10: -4.0, 20: 1.0, 30: 0.0, 40: -1.0, 50: 5.0, 60: 7.0, 70: -6.0, 80: -8.0, 90: -3.0, 95: -4.0, 100: -2.0}


def worldcover():
    if not os.path.exists(WC_CACHE):
        from rasterio.windows import from_bounds
        print("reading ESA WorldCover from AWS (once)")
        with rasterio.open(WC_URL) as src:
            win = from_bounds(LON0, LAT0, LON1, LAT1, src.transform)
            h, w = int(win.height) // 3, int(win.width) // 3
            a = src.read(1, window=win, out_shape=(h, w), resampling=rasterio.enums.Resampling.mode)
            tr = src.window_transform(win) * Affine.scale(win.width / w, win.height / h)
        os.makedirs(DATA, exist_ok=True)
        with rasterio.open(WC_CACHE, "w", driver="GTiff", width=w, height=h, count=1, dtype="uint8",
                           crs="EPSG:4326", transform=tr, compress="deflate", nodata=0) as dst:
            dst.write(a, 1)
    with rasterio.open(WC_CACHE) as src:
        out = np.zeros((H + 2 * PAD, W + 2 * PAD), "uint8")
        warp.reproject(rasterio.band(src, 1), out, dst_transform=from_origin(X0 - PAD * RES, Y0 + PAD * RES, RES, RES),
                       dst_crs=CRS, resampling=warp.Resampling.mode, src_nodata=0, dst_nodata=0)
    out[out == 0] = 30  # outside WorldCover's tile: call it grassland (no edges)
    return out


def smooth_field(rng, shape, scale):
    """Low-frequency random field (stand-in for terrain and soil moisture), unit variance."""
    f = np.fft.fft2(rng.normal(size=shape))
    ky, kx = np.meshgrid(np.fft.fftfreq(shape[0]), np.fft.fftfreq(shape[1]), indexing="ij")
    f *= np.exp(-(kx ** 2 + ky ** 2) * (scale ** 2))
    a = np.real(np.fft.ifft2(f))
    return (a - a.mean()) / a.std()


def clouds(rng, shape, frac):
    if frac <= 0:
        return np.zeros(shape, bool)
    f = smooth_field(rng, shape, 40)
    return f > np.quantile(f, 1 - frac)


def orbit_for(t):
    return 35724 + int(round((t - datetime(2024, 10, 24)).total_seconds() / 86400 * 15.54))


def write_tif(path, a, dtype, nodata):
    with rasterio.open(path, "w", driver="GTiff", width=W, height=H, count=1, dtype=dtype, crs=CRS,
                       transform=from_origin(X0, Y0, RES, RES), compress="deflate", predictor=2 if dtype != "float32" else 3,
                       nodata=nodata, tiled=True, blockxsize=256, blockysize=256) as d:
        d.write(a.astype(dtype), 1)


def write_geo_h5(path, qa, corrected, fov):
    import h5py
    with h5py.File(path, "w") as f:
        g = f.create_group("L1GEOMetadata")
        g["GeolocationAccuracyQA"] = np.bytes_(qa.capitalize())
        g["GeolocationAccuracyQAExplanation"] = np.bytes_({
            "best": "Image matching was performed for this scene",
            "good": "Matched a nearby scene in the orbit; correction carried over",
            "suspect": "Matched elsewhere in the orbit, far from this scene",
            "poor": "No image matching in this orbit"}[qa])
        g["OrbitCorrectionPerformed"] = np.bytes_(str(corrected))
        s = f.create_group("StandardMetadata")
        s["FieldOfViewObstruction"] = np.bytes_(str(fov))
        s["SyntheticDemo"] = np.bytes_("metadata only; no geolocation arrays")


def main():
    rng = np.random.default_rng(42)
    lc = worldcover()
    os.makedirs(SCENES, exist_ok=True)
    for f in os.listdir(SCENES):
        os.remove(os.path.join(SCENES, f))
    water_truth = (lc == 80)
    terrain = smooth_field(rng, lc.shape, 25)
    summary_rows = []
    for i, (ts, qa, corr, sx, sy, cf, fov, where) in enumerate(PLAN):
        t = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S")
        orbit, scene = orbit_for(t), 3 + (i * 5) % 17
        night = t.hour >= 18 or t.hour < 4
        base = 287.0 if night else 300.0 + 8 * np.sin(np.pi * (t.hour - 6) / 12)
        off = np.vectorize(lambda c: OFFSET.get(int(c), 0.0))(lc)
        if night:
            off = np.where(water_truth, 5.0, off * 0.3)
        lst = base + off + 1.5 * terrain + rng.normal(0, 0.6, lc.shape)
        # the shift: what the sensor saw at true position p is written at p + shift
        dx_px, dy_px = int(round(sx / RES)), int(round(-sy / RES))
        r0, c0 = PAD - dy_px, PAD - dx_px
        lst_obs = lst[r0:r0 + H, c0:c0 + W]
        cl = clouds(rng, (H, W), cf)
        lst_obs = np.where(cl, base - 25 + rng.normal(0, 2, (H, W)), lst_obs)
        water_layer = water_truth[PAD:PAD + H, PAD:PAD + W]  # static mask: always in the right place
        stem = f"ECOv002_L2T_LSTE_{orbit:05d}_{scene:03d}_{TILE}_{t:%Y%m%dT%H%M%S}_0712_01"
        write_tif(os.path.join(SCENES, stem + "_LST.tif"), np.round(lst_obs, 2), "float32", np.nan)
        write_tif(os.path.join(SCENES, stem + "_cloud.tif"), cl, "uint8", 255)
        write_tif(os.path.join(SCENES, stem + "_water.tif"), water_layer, "uint8", 255)
        if where == "geo":
            write_geo_h5(os.path.join(SCENES, f"ECOv002_L1B_GEO_{orbit:05d}_{scene:03d}_{t:%Y%m%dT%H%M%S}_0712_01.h5"),
                         qa, corr, fov)
        elif where == "sidecar":
            umm = {"GranuleUR": stem, "AdditionalAttributes": [
                {"Name": "GeolocationAccuracyQA", "Values": [qa.capitalize()]},
                {"Name": "OrbitCorrectionPerformed", "Values": [str(corr)]},
                {"Name": "FieldOfViewObstruction", "Values": [str(fov)]}]}
            json.dump(umm, open(os.path.join(SCENES, stem + ".json"), "w"), indent=1)
        elif where == "summary":
            summary_rows.append((orbit, scene, t, qa))
        print(f"{stem}: flag {qa or '-':8s} ({where:7s}) true shift {sx:+5d} m E {sy:+5d} m N, cloud {cf:.0%}")
    # A made-up summary table (NASA's real layout was not available) to show the reader at work.
    with open(os.path.join(DATA, "geolocation_summary_example.txt"), "w") as f:
        f.write("# Synthetic stand-in for NASA's ECOSTRESS geolocation summary file\n")
        f.write("Orbit Scene StartTime GeolocationAccuracyQA\n")
        f.write("35730 001 2024-10-24T10:00:00 Best\n")
        for orbit, scene, t, qa in summary_rows:
            f.write(f"{orbit} {scene:03d} {t:%Y-%m-%dT%H:%M:%S} {qa.capitalize()}\n")
    # shifts are applied in whole pixels, so record what was applied
    truth = [{"time": p[0], "flag": p[1], "applied_east_m": round(p[3] / RES) * RES,
              "applied_north_m": round(p[4] / RES) * RES, "cloud": p[5], "fov_obstruction": p[6],
              "flag_stored_in": p[7]} for p in PLAN]
    json.dump(truth, open(os.path.join(DATA, "truth.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
