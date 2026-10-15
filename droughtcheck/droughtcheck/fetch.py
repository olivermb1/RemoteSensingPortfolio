"""Download the open inputs Drought Check needs, clipped to an area.

All sources are public, need no login, and are read as cloud-optimised files,
so only the area asked for is transferred.

  chirps     CHIRPS v2.0 monthly rainfall (mm), 0.05 deg, 1981 onward.
             Digital Earth Africa copy: s3://deafrica-input-datasets/rainfall_chirps_monthly
  temps      Monthly mean daily Tmax / Tmin (deg C) from NASA POWER (MERRA-2,
             0.5 x 0.625 deg): s3://nasa-power/merra2/temporal/..monthly..zarr
  ndvi       DE Africa monthly NDVI standardised anomaly (Landsat 8/9 + Sentinel-2,
             30 m, vs a 1984-2020 Landsat climatology), 2017 onward:
             s3://deafrica-services/ndvi_anomaly
  worldcover ESA WorldCover 2021 v200 (10 m), aggregated by majority to the NDVI grid.

Usage:
  python -m droughtcheck.fetch chirps     --bbox W S E N --start 1981-01 --end 2026-08 --out chirps.tif
  python -m droughtcheck.fetch temps      --bbox W S E N --start 1981-01 --end 2026-08 --out power.tif
  python -m droughtcheck.fetch ndvi       --tile x217y076 --start 2017-01 --end 2026-09 --overview 8 --out ndvi.tif
  python -m droughtcheck.fetch worldcover --like ndvi.tif --out worldcover.tif
"""
from __future__ import annotations

import argparse
import json
import math
from concurrent.futures import ThreadPoolExecutor

import numpy as np

CHIRPS_URL = ("https://deafrica-input-datasets.s3.af-south-1.amazonaws.com/"
              "rainfall_chirps_monthly/chirps-v2.0_{y:04d}.{m:02d}.tif")
CHIRPS_DAILY_URL = ("https://deafrica-input-datasets.s3.af-south-1.amazonaws.com/"
                    "rainfall_chirps_daily/{y:04d}/{m:02d}/chirps-v2.0_{y:04d}.{m:02d}.{d:02d}.tif")
POWER_ZARR = ("https://nasa-power.s3.amazonaws.com/merra2/temporal/"
              "power_merra2_monthly_temporal_utc.zarr")
NDVI_URL = ("https://deafrica-services.s3.af-south-1.amazonaws.com/ndvi_anomaly/1-0-0/"
            "{tx}/{ty}/{y:04d}-{m:02d}--P1M/ndvi_anomaly_{tile}_{y:04d}-{m:02d}--P1M_{band}.tif")
WC_URL = ("https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
          "ESA_WorldCover_10m_2021_v200_{tile}_Map.tif")

# DE Africa tiles: EPSG:6933, 96 km squares of 3200 x 30 m pixels
DEA_ORIGIN_X, DEA_ORIGIN_Y, DEA_TILE = -17376000.0, 7296000.0, 96000.0


def months(start: str, end: str) -> list[tuple[int, int]]:
    y, m = map(int, start.split("-"))
    ye, me = map(int, end.split("-"))
    out = []
    while (y, m) <= (ye, me):
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _env():
    import rasterio
    return rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MAX_RETRY="4",
                        GDAL_HTTP_RETRY_DELAY="2", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif")


def _write_stack(path, stack, transform, crs, labels, nodata=np.nan, extra_tags=None):
    import rasterio
    stack = np.asarray(stack, dtype="float32")
    prof = dict(driver="GTiff", width=stack.shape[2], height=stack.shape[1], count=stack.shape[0],
                dtype="float32", crs=crs, transform=transform, nodata=nodata,
                compress="deflate", tiled=stack.shape[2] >= 256 and stack.shape[1] >= 256)
    with rasterio.open(path, "w", **prof) as dst:
        dst.write(stack)
        for i, lab in enumerate(labels, 1):
            dst.set_band_description(i, lab)
        if extra_tags:
            dst.update_tags(**extra_tags)


def fetch_chirps(bbox, start, end, out, workers=16):
    """Clip CHIRPS monthly totals to bbox (W, S, E, N); one band per month."""
    import rasterio
    from rasterio.windows import from_bounds
    mlist = months(start, end)

    def read(ym):
        try:
            return _read(CHIRPS_URL.format(y=ym[0], m=ym[1]))
        except Exception:
            pass
        try:  # monthly file missing from the bucket: sum the daily files instead
            import calendar
            days = calendar.monthrange(*ym)[1]
            parts = [_read(CHIRPS_DAILY_URL.format(y=ym[0], m=ym[1], d=d)) for d in range(1, days + 1)]
            filled.append(f"{ym[0]:04d}-{ym[1]:02d}")
            return np.sum([q[0] for q in parts], axis=0), parts[0][1], parts[0][2]
        except Exception:  # month not published (yet)
            return None

    filled: list[str] = []

    def _read(url):
        with _env(), rasterio.open(url) as src:
            win = from_bounds(*bbox, transform=src.transform).round_offsets().round_lengths()
            a = src.read(1, window=win).astype("float32")
            a[a == src.nodata] = np.nan
            a[a < 0] = np.nan
            return a, src.window_transform(win), src.crs

    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(read, mlist))
    while res and res[-1] is None:  # drop unpublished trailing months
        res.pop(); mlist = mlist[:-1]
    missing = [f"{y:04d}-{m:02d}" for (y, m), r in zip(mlist, res) if r is None]
    ref = next(r for r in res if r is not None)
    stack = np.stack([r[0] if r is not None else np.full_like(ref[0], np.nan) for r in res])
    if filled:
        print(f"CHIRPS months summed from daily files: {', '.join(sorted(filled))}")
    if missing:
        print(f"CHIRPS months not found: {', '.join(missing)}")
    _write_stack(out, stack, ref[1], ref[2], [f"{y:04d}-{m:02d}" for y, m in mlist],
                 extra_tags=dict(source="CHIRPS v2.0 monthly (DE Africa copy)", units="mm/month",
                                 summed_from_daily=",".join(sorted(filled)), missing=",".join(missing),
                                 first_month=f"{mlist[0][0]:04d}-{mlist[0][1]:02d}"))
    return out


def fetch_power_temps(bbox, start, end, out, pad=0.7):
    """Monthly mean daily Tmax and Tmin from NASA POWER MERRA-2 (Zarr v2, read over HTTP).

    Writes a 2*n-band GeoTIFF: bands 1..n Tmax, n+1..2n Tmin, on the native POWER grid,
    padded so every pixel of bbox has a cell around it.
    """
    import fsspec
    import zarr
    store = fsspec.get_mapper(POWER_ZARR)
    g = zarr.open_group(store, mode="r")
    lat = np.asarray(g["lat"][:]); lon = np.asarray(g["lon"][:])
    t = np.asarray(g["time"][:])  # days since 1981-01-31
    base = np.datetime64("1981-01-31")
    tm = [(int(str(d)[:4]), int(str(d)[5:7])) for d in (base + t.astype("timedelta64[D]"))]
    want = months(start, end)
    idx = [tm.index(ym) for ym in want if ym in tm]
    got = [tm[i] for i in idx]
    W, S, E, N = bbox
    yi = np.where((lat >= S - pad) & (lat <= N + pad))[0]
    xi = np.where((lon >= W - pad) & (lon <= E + pad))[0]
    sl = (slice(idx[0], idx[-1] + 1), slice(yi[0], yi[-1] + 1), slice(xi[0], xi[-1] + 1))
    tmax = np.asarray(g["T2M_MAX_AVG"][sl], dtype="float32")
    tmin = np.asarray(g["T2M_MIN_AVG"][sl], dtype="float32")
    keep = [i - idx[0] for i in idx]
    tmax, tmin = tmax[keep], tmin[keep]
    # rows north-up
    la = lat[yi]
    if la[0] < la[-1]:
        tmax, tmin, la = tmax[:, ::-1], tmin[:, ::-1], la[::-1]
    lo = lon[xi]
    dx = float(lo[1] - lo[0]); dy = float(la[0] - la[1])
    from rasterio.transform import from_origin
    tr = from_origin(lo[0] - dx / 2, la[0] + dy / 2, dx, dy)
    # trailing months POWER has not filled yet come back NaN; drop them
    ok = [i for i in range(len(got)) if np.isfinite(tmax[i]).any()]
    labels = [f"tmax {got[i][0]:04d}-{got[i][1]:02d}" for i in ok] + \
             [f"tmin {got[i][0]:04d}-{got[i][1]:02d}" for i in ok]
    _write_stack(out, np.concatenate([tmax[ok], tmin[ok]]), tr, "EPSG:4326", labels,
                 extra_tags=dict(source="NASA POWER MERRA-2 monthly T2M_MAX_AVG / T2M_MIN_AVG",
                                 units="degC", first_month=f"{got[ok[0]][0]:04d}-{got[ok[0]][1]:02d}",
                                 n_months=str(len(ok))))
    return out


def dea_tile_bounds(tile: str):
    tx, ty = int(tile[1:4]), int(tile[5:8])
    left = DEA_ORIGIN_X + tx * DEA_TILE
    top = DEA_ORIGIN_Y - ty * DEA_TILE
    return left, top - DEA_TILE, left + DEA_TILE, top


def fetch_ndvi_anomaly(tile, start, end, out, overview=8, workers=12):
    """DE Africa monthly NDVI standardised anomaly for one tile, read at a COG overview
    (8 -> 240 m). Writes anomaly bands and a second file *_clear.tif with clear counts."""
    import rasterio
    from rasterio.transform import Affine
    mlist = months(start, end)
    tx, ty = tile[:4], tile[4:]
    ovr = int(overview)

    def read(args):
        (y, m), band = args
        url = NDVI_URL.format(tx=tx, ty=ty, tile=tile, y=y, m=m, band=band)
        try:
            with _env(), rasterio.open(url, overview_level=None if ovr == 1 else
                                       [2, 4, 8, 16, 32].index(ovr)) as src:
                a = src.read(1).astype("float32")
                return a, src.transform, src.crs
        except Exception:
            return None

    with ThreadPoolExecutor(workers) as ex:
        anom = list(ex.map(read, [(ym, "ndvi_std_anomaly") for ym in mlist]))
        clear = list(ex.map(read, [(ym, "clear_count") for ym in mlist]))
    ref = next(r for r in anom if r is not None)
    shape = ref[0].shape
    A = np.full((len(mlist),) + shape, np.nan, "float32")
    C = np.zeros((len(mlist),) + shape, "float32")
    for i, (a, c) in enumerate(zip(anom, clear)):
        if a is not None:
            A[i] = a[0]
        if c is not None:
            C[i] = c[0]
    A[C <= 0] = np.nan
    labels = [f"{y:04d}-{m:02d}" for y, m in mlist]
    tags = dict(source=f"DE Africa ndvi_anomaly 1-0-0 tile {tile}, overview {ovr}",
                units="standard deviations", first_month=labels[0])
    _write_stack(out, A, ref[1], ref[2], labels, extra_tags=tags)
    _write_stack(out.replace(".tif", "_clear.tif"), C, ref[1], ref[2], labels, nodata=None,
                 extra_tags=dict(tags, units="clear observations"))
    return out


def fetch_worldcover_like(like, out):
    """ESA WorldCover 2021 aggregated by majority (mode) onto the grid of `like`."""
    import rasterio
    from rasterio.warp import reproject, Resampling, transform_bounds
    from rasterio.windows import from_bounds
    with rasterio.open(like) as ref:
        dst_tr, dst_crs, h, w = ref.transform, ref.crs, ref.height, ref.width
        W, S, E, N = transform_bounds(ref.crs, "EPSG:4326", *ref.bounds, densify_pts=21)
    tiles = set()
    for lat in np.arange(math.floor(S / 3) * 3, N, 3):
        for lon in np.arange(math.floor(W / 3) * 3, E, 3):
            la, lo = int(lat), int(lon)
            tiles.add(f"{'N' if la >= 0 else 'S'}{abs(la):02d}{'E' if lo >= 0 else 'W'}{abs(lo):03d}")
    dst = np.zeros((h, w), "uint8")
    for t in sorted(tiles):
        with _env(), rasterio.open(WC_URL.format(tile=t)) as src:
            win = from_bounds(max(W, src.bounds.left), max(S, src.bounds.bottom),
                              min(E, src.bounds.right), min(N, src.bounds.top), src.transform)
            win = win.round_offsets().round_lengths()
            if win.width <= 0 or win.height <= 0:
                continue
            a = src.read(1, window=win)
            part = np.zeros((h, w), "uint8")
            reproject(a, part, src_transform=src.window_transform(win), src_crs=src.crs,
                      dst_transform=dst_tr, dst_crs=dst_crs, resampling=Resampling.mode,
                      src_nodata=0, dst_nodata=0)
            dst = np.where(dst == 0, part, dst)
    prof = dict(driver="GTiff", width=w, height=h, count=1, dtype="uint8", crs=dst_crs,
                transform=dst_tr, nodata=0, compress="deflate")
    with rasterio.open(out, "w", **prof) as o:
        o.write(dst, 1)
        o.update_tags(source=f"ESA WorldCover 2021 v200, majority to {like}", tiles=",".join(sorted(tiles)))
    return out


def main(argv=None):
    p = argparse.ArgumentParser(prog="droughtcheck.fetch", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("what", choices=["chirps", "temps", "ndvi", "worldcover"])
    p.add_argument("--bbox", nargs=4, type=float, metavar=("W", "S", "E", "N"))
    p.add_argument("--tile", help="DE Africa tile, e.g. x217y076")
    p.add_argument("--start"); p.add_argument("--end")
    p.add_argument("--overview", type=int, default=8)
    p.add_argument("--like")
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    if a.what == "chirps":
        fetch_chirps(a.bbox, a.start, a.end, a.out)
    elif a.what == "temps":
        fetch_power_temps(a.bbox, a.start, a.end, a.out)
    elif a.what == "ndvi":
        fetch_ndvi_anomaly(a.tile, a.start, a.end, a.out, a.overview)
    else:
        fetch_worldcover_like(a.like, a.out)
    print(json.dumps({"wrote": a.out}))


if __name__ == "__main__":
    main()
