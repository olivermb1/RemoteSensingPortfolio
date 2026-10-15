"""Read scenes, compute season peaks, classify fields, write the table, rasters and pictures."""

import datetime as dt
import json
import os
import re
import warnings
from collections import defaultdict

import numpy as np

from . import core

__version__ = "0.1"


def _date(path):
    m = re.search(r"(20\d{6})", os.path.basename(path))
    return dt.datetime.strptime(m[1], "%Y%m%d").date() if m else None


def read_ndvi(path, grid):
    import rasterio
    from rasterio.warp import reproject, Resampling
    with rasterio.open(path) as s:
        tags, a = s.tags(), s.read()
        src = (s.crs, s.transform, (s.height, s.width))
    if src != grid:
        dst = np.zeros((a.shape[0],) + grid[2], a.dtype)
        reproject(a, dst, src_transform=src[1], src_crs=src[0], dst_transform=grid[1], dst_crs=grid[0],
                  resampling=Resampling.nearest, src_nodata=0, dst_nodata=0)
        a = dst
    return core.ndvi(a[:6], a[6], float(tags.get("TP_SCALE", 1e-4)), float(tags.get("TP_OFFSET", 0)))


def seasons(paths, years, start_md, end_md):
    """{year: [paths]} for scenes inside each year's season window (a window may cross New Year)."""
    out = defaultdict(list)
    for f in paths:
        d = _date(f)
        if d is None:
            continue
        for y in years:
            a = dt.date(y, *start_md)
            b = dt.date(y + (1 if end_md < start_md else 0), *end_md)
            if a <= d <= b:
                out[y].append(f)
    return out


def run(scenes, baseline_years, target_year, season, out, cropland=None, crop_classes=(40,), unit_file=None,
        cell=1000.0, places=None, params=None, log=print):
    import geopandas as gpd
    import rasterio
    from rasterio.features import rasterize
    from rasterio.warp import reproject, Resampling
    from shapely.geometry import box

    p = {**core.DEFAULTS, **(params or {})}
    os.makedirs(out, exist_ok=True)
    def _px(f):
        with rasterio.open(f) as s:
            return s.width * s.height
    ref = max(scenes[:50], key=_px)  # scenes may come from two MGRS tiles; use the fullest window as the grid
    with rasterio.open(ref) as s:
        grid = (s.crs, s.transform, (s.height, s.width))
    tr, shape = grid[1], grid[2]
    px_ha = abs(tr.a * tr.e) / 1e4
    smd = tuple(int(x) for x in season[0].split("-"))
    emd = tuple(int(x) for x in season[1].split("-"))
    years = list(baseline_years) + [target_year]
    by = seasons(scenes, years, smd, emd)
    peaks, nobs = {}, {}
    for y in years:
        if not by[y]:
            raise SystemExit(f"no scenes in the {y} season")
        peaks[y], nobs[y] = core.season_peak(np.stack([read_ndvi(f, grid) for f in by[y]]), p["pctl"])
        log(f"{y}: {len(by[y])} scenes, median clear observations per pixel {int(np.median(nobs[y]))}")
    base = np.stack([peaks[y] for y in baseline_years])
    cls = core.classify(peaks[target_year], base, nobs[target_year], p)
    loo = core.leave_one_out(base, np.stack([nobs[y] for y in baseline_years]), p)

    crop = None
    if cropland:
        with rasterio.open(cropland) as c:
            dst = np.zeros(shape, "uint8")
            reproject(c.read(1), dst, src_transform=c.transform, src_crs=c.crs, dst_transform=tr, dst_crs=grid[0],
                      resampling=Resampling.nearest)
        crop = np.isin(dst, crop_classes)

    if unit_file:
        uu = gpd.read_file(unit_file).to_crs(grid[0]).reset_index(drop=True)
        uu["kind"] = "given"
    else:
        x0, y0 = tr.c, tr.f
        x1, y1 = x0 + tr.a * shape[1], y0 + tr.e * shape[0]
        xs = np.arange(np.floor(min(x0, x1) / cell) * cell, max(x0, x1), cell)
        ys = np.arange(np.floor(min(y0, y1) / cell) * cell, max(y0, y1), cell)
        cells = [box(x, y, x + cell, y + cell) for y in ys[::-1] for x in xs]
        uu = gpd.GeoDataFrame({"kind": ["grid"] * len(cells)}, geometry=cells, crs=grid[0])
    uu.insert(0, "unit_id", np.arange(1, len(uu) + 1))
    uid = rasterize([(g, i) for g, i in zip(uu.geometry, uu.unit_id)], out_shape=shape, transform=tr, fill=0,
                    dtype="int32")
    n = len(uu)
    t = core.unit_table(uid, n, cls, crop, px_ha)
    i = uu.unit_id.to_numpy()
    for k, v in t.items():
        uu[k] = np.round(v[i], 1)
    # normal-year floor per unit: the highest not-farmed share seen in any baseline season
    loo_pct = np.stack([core.unit_table(uid, n, c, crop, px_ha)["not_farmed_pct"] for c in loo])
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            uu["normal_year_max_pct"] = np.round(np.nanmax(loo_pct, 0)[i], 1)
    uu["above_normal"] = (uu.not_farmed_pct > uu.normal_year_max_pct + 5) & (uu.not_farmed_ha >= 1)
    # field pattern: does the patchwork of separate fields survive, or has one cover spread over everything?
    cmask = crop if crop is not None else None
    m = crop if crop is not None else np.ones(shape, bool)
    cons = np.stack([core.unit_mean(uid, n, core.field_contrast(peaks[y]), cmask) for y in years])
    tr_ratio, normal = core.pattern_ratios(cons, len(years) - 1)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        nmin = np.nanmin(normal, 0)
    uu["pattern_ratio"] = np.round(tr_ratio[i], 2)
    uu["pattern_normal_min"] = np.round(nmin[i], 2)
    uu["pattern_lost"] = (uu.pattern_ratio < np.minimum(uu.pattern_normal_min, 1.0) - 0.1) & (uu.pattern_ratio < 0.8)
    uu = uu[uu.farmed_base_ha > 0].copy()
    if places:
        from .names import name_units
        uu["place"], uu["place_dist_m"] = name_units(uu, gpd.read_file(places))
    c = uu.geometry.centroid.to_crs(4326)
    uu["centroid_lon"], uu["centroid_lat"] = c.x.round(5), c.y.round(5)
    uu = uu.sort_values("not_farmed_ha", ascending=False)
    cols = [k for k in uu.columns if k != "geometry"]
    uu[cols].to_csv(os.path.join(out, "summary.csv"), index=False)
    uu.to_crs(4326).to_file(os.path.join(out, "units.geojson"), driver="GeoJSON")

    lay = cls.copy()
    if crop is not None:
        lay[~crop & (lay != 255)] = 0
    gp = dict(driver="GTiff", height=shape[0], width=shape[1], crs=grid[0], transform=tr, compress="deflate")
    with rasterio.open(os.path.join(out, "field_classes.tif"), "w", count=1, dtype="uint8", nodata=255, **gp) as d:
        d.write(lay, 1)
        d.update_tags(CLASSES="0 not cropland or not farmed in baseline, 1 farmed as usual, 2 reduced, 3 not farmed, "
                              "255 not enough clear data")
    with rasterio.open(os.path.join(out, "peaks.tif"), "w", count=len(years), dtype="float32", nodata=np.nan, **gp) as d:
        for k, y in enumerate(years, 1):
            d.write(peaks[y], k)
            d.set_band_description(k, f"peak NDVI {y}")

    def tot(c):
        return round(float(((c == 3) & m).sum() * px_ha), 1), round(float((((c >= 1) & (c <= 3)) & m).sum() * px_ha), 1)
    nf, seen = tot(cls)
    info = dict(tool="fallowcheck", version=__version__, run_at=dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
                baseline_years=list(baseline_years), target_year=target_year, season=list(season),
                scenes_per_year={y: len(by[y]) for y in years}, cropland=os.path.basename(cropland) if cropland else None,
                crop_classes=list(crop_classes), params=p, units=unit_file or f"grid {cell:.0f} m",
                target=dict(not_farmed_ha=nf, farmed_base_seen_ha=seen, not_farmed_pct=round(100 * nf / max(seen, 1e-9), 1)),
                normal_years={},
                field_contrast_aoi={y: round(float(np.nanmean(core.field_contrast(peaks[y])[m])), 4) for y in years},
                low_peak_share_pct={y: round(float(100 * np.nanmean(peaks[y][m] < p["max_target"])), 1) for y in years},
                pattern_lost_units=int(uu.pattern_lost.sum()), units_reported=int(len(uu)))
    for y, c in zip(baseline_years, loo):
        a, b = tot(c)
        info["normal_years"][y] = dict(not_farmed_ha=a, farmed_base_seen_ha=b, not_farmed_pct=round(100 * a / max(b, 1e-9), 1))
    with open(os.path.join(out, "run.json"), "w") as f:
        json.dump(info, f, indent=1, default=str)
    log(f"field contrast {info['field_contrast_aoi']}; share of cropland with peak NDVI < {p['max_target']}: "
        f"{info['low_peak_share_pct']}; units with field pattern lost: {info['pattern_lost_units']} of {len(uu)}")
    log(f"{target_year}: {nf} ha of normally farmed cropland not farmed ({info['target']['not_farmed_pct']} %); "
        f"normal years: " + ", ".join(f"{y} {v['not_farmed_pct']} %" for y, v in info["normal_years"].items()))
    try:
        from . import report
        report.map_png(os.path.join(out, "map.png"), peaks, years, lay, uu, grid, info)
    except ImportError as e:
        log(f"pictures skipped ({e})")
    return uu, info
