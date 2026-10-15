"""Read scenes, build monthly composites, apply core rules, write table, rasters and pictures."""

import datetime as dt
import json
import os
import re
from collections import defaultdict

import numpy as np

from . import core

__version__ = "0.1"


def _month(path, tags):
    s = tags.get("TP_DATE") or (re.search(r"(20\d{6})", os.path.basename(path)) or [None, None])[1]
    return s[:6] if s else None


def read_indices(path, grid=None):
    """Scene -> ((3, r, c) ratio/blue/ndvi, profile, 'YYYYMM'). 6 bands + SCL (fetch-s2 output)."""
    import rasterio
    from rasterio.warp import reproject, Resampling
    with rasterio.open(path) as s:
        tags, prof, a = s.tags(), s.profile, s.read()
    if grid is not None and (prof["crs"] != grid[0] or prof["transform"] != grid[1] or a.shape[1:] != grid[2]):
        dst = np.zeros((a.shape[0],) + grid[2], a.dtype)
        reproject(a, dst, src_transform=prof["transform"], src_crs=prof["crs"], dst_transform=grid[1],
                  dst_crs=grid[0], resampling=Resampling.nearest, src_nodata=0, dst_nodata=0)
        a = dst
    x = core.indices(a[:6], a[6], float(tags.get("TP_SCALE", 1e-4)), float(tags.get("TP_OFFSET", 0)))
    return x, prof, _month(path, tags)


def monthly(paths, grid, months_wanted=None, log=print):
    """{'YYYYMM': (3, r, c) median composite} for the months asked."""
    by = defaultdict(list)
    for f in paths:
        m = re.search(r"(20\d{6})", os.path.basename(f))
        if m and (months_wanted is None or m[1][:6] in months_wanted):
            by[m[1][:6]].append(f)
    out = {}
    for m in sorted(by):
        out[m] = core.median(np.stack([read_indices(f, grid)[0] for f in by[m]]))
    return out


def _months_between(a, b):
    y, m = int(a[:4]), int(a[5:7])
    out = []
    while (y, m) <= (int(b[:4]), int(b[5:7])):
        out.append(f"{y}{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def run(scenes, baseline, period, out, unit_file=None, places=None, dry_months=core.DRY_MONTHS, params=None,
        log=print):
    """scenes: scene files; baseline/period: ('YYYY-MM', 'YYYY-MM') inclusive month ranges."""
    import geopandas as gpd
    import rasterio
    from rasterio.features import rasterize, shapes

    p = {**core.DEFAULTS, **(params or {})}
    os.makedirs(out, exist_ok=True)
    with rasterio.open(scenes[0]) as s:
        grid = (s.crs, s.transform, (s.height, s.width))
    tr = grid[1]
    px_ha = abs(tr.a * tr.e) / 1e4

    bm = [m for m in _months_between(*baseline) if int(m[4:]) in dry_months]
    am = [m for m in _months_between(*period) if int(m[4:]) in dry_months]
    base = monthly(scenes, grid, set(bm))
    if not base:
        raise SystemExit("no clear baseline scenes")
    by_cal = defaultdict(list)
    for m, x in base.items():
        by_cal[int(m[4:])].append(x)
    base_cal = {k: core.median(np.stack(v)) for k, v in by_cal.items()}
    log(f"baseline: {len(base)} months with clear scenes ({', '.join(sorted(base))}), calendar months {sorted(base_cal)}")

    def base_for(month):
        k = int(month[4:])
        return base_cal[min(base_cal, key=lambda c: min((c - k) % 12, (k - c) % 12))]

    months, S = [], []
    for m in am:
        cur = monthly(scenes, grid, {m}).get(m)
        if cur is None:
            continue
        months.append(m)
        S.append(core.shelter_month(cur, base_for(m), p))
    if not S:
        raise SystemExit("no clear scenes in the analysis period")
    S = np.stack(S)
    P = core.smooth(S)
    first = core.first_seen(P, p["persist"])
    log(f"analysis: {len(months)} months ({months[0]}..{months[-1]}); "
        f"{(first >= 0).sum() * px_ha:.1f} ha of new shelter pixels")

    # units
    crs_m = grid[0]
    if unit_file:
        uu = gpd.read_file(unit_file).to_crs(crs_m).reset_index(drop=True)
        uu.insert(0, "unit_id", np.arange(1, len(uu) + 1))
        uid = rasterize([(g, i) for g, i in zip(uu.geometry, uu.unit_id)], out_shape=grid[2], transform=tr,
                        fill=0, dtype="int32")
        uu["kind"] = "given"
    else:
        lab, n = core.label(first >= 0, p["join_px"])
        size = np.bincount(lab.ravel(), minlength=n + 1) * px_ha
        keep = size >= p["min_area_ha"]
        keep[0] = False
        remap = np.zeros(n + 1, "int32")
        remap[keep] = np.arange(1, keep.sum() + 1)
        uid = remap[lab]
        from shapely.geometry import shape
        from shapely.ops import unary_union
        d = defaultdict(list)
        for geom, v in shapes(uid, mask=uid > 0, transform=tr):
            d[int(v)].append(shape(geom))
        r = abs(tr.a) * p["join_px"]  # close the gaps between shelter blocks for a readable outline
        uu = gpd.GeoDataFrame({"unit_id": sorted(d)}, crs=crs_m,
                              geometry=[unary_union(d[k]).buffer(r).buffer(-r / 2) for k in sorted(d)])
        uu["kind"] = "detected"
    n_units = len(uu)
    log(f"{n_units} areas")

    foot, obs = core.area_series(P, uid, n_units, first, px_ha)
    own, _ = core.area_series(P, uid, n_units, None, px_ha)

    # per unit summary
    i = uu.unit_id.to_numpy()
    final = foot[-1, i]
    uu["footprint_ha"] = final.round(1)
    def month_reaching(frac):
        res = []
        for k in i:
            tgt = max(foot[-1, k] * frac, 1.0)
            hit = np.nonzero(foot[:, k] >= tgt)[0]
            res.append(months[hit[0]] if len(hit) and foot[-1, k] > 0 else None)
        return res
    uu["first_month"] = month_reaching(0.1)
    uu["half_month"] = month_reaching(0.5)
    def ago(k):
        j = max(len(months) - 1 - k, 0)
        return foot[j, i]
    uu["growth_ha_last3"] = (final - ago(3)).round(1)
    uu["observed_pct_last"] = np.round(obs[-1, i], 0)
    uu["area_ha"] = (uu.geometry.area / 1e4).round(1)
    if places:
        from .names import name_units
        uu["place"], uu["place_dist_m"] = name_units(uu, gpd.read_file(places))
    c = uu.geometry.centroid.to_crs(4326)
    uu["centroid_lon"], uu["centroid_lat"] = c.x.round(5), c.y.round(5)
    uu = uu.sort_values("footprint_ha", ascending=False)

    cols = [k for k in uu.columns if k != "geometry"]
    uu[cols].to_csv(os.path.join(out, "summary.csv"), index=False)
    uu.to_crs(4326).to_file(os.path.join(out, "areas.geojson"), driver="GeoJSON")
    with open(os.path.join(out, "timeseries.csv"), "w") as f:
        f.write("unit_id,month,footprint_ha,shelter_ha_this_month,observed_pct\n")
        for k in i:
            for t, m in enumerate(months):
                f.write(f"{k},{m[:4]}-{m[4:]},{foot[t, k]:.2f},{own[t, k]:.2f},{obs[t, k]:.0f}\n")
    fs = np.where(first >= 0, np.array([int(m) for m in months], "int32")[np.clip(first, 0, None)], 0).astype("int32")
    gp = dict(driver="GTiff", height=grid[2][0], width=grid[2][1], crs=grid[0], transform=tr, compress="deflate")
    with rasterio.open(os.path.join(out, "first_seen.tif"), "w", count=1, dtype="int32", nodata=0, **gp) as d:
        d.write(fs, 1)
        d.set_band_description(1, "YYYYMM a pixel first became shelter and stayed so")
    info = dict(tool="campwatch", version=__version__, run_at=dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
                n_scenes=len(scenes), baseline=baseline, baseline_months=sorted(base), period=period,
                months=months, dry_months=list(dry_months), params=p, units=unit_file or "detected",
                n_areas=n_units, total_footprint_ha=round(float(foot[-1, 1:].sum()), 1),
                total_new_pixels_ha=round(float((first >= 0).sum() * px_ha), 1))
    with open(os.path.join(out, "run.json"), "w") as f:
        json.dump(info, f, indent=1, default=str)
    try:
        from . import report
        report.growth_png(os.path.join(out, "growth.png"), months, foot, uu)
        report.map_png(os.path.join(out, "map.png"), fs, months, uu, grid, scenes)
    except ImportError as e:
        log(f"pictures skipped ({e})")
    log(f"{n_units} areas, {info['total_footprint_ha']} ha footprint by {months[-1]}")
    return uu, info
