"""Read inputs, run the rules in core.py, write the table, map layers and pictures."""

import csv
import datetime as dt
import json
import os
import re

import numpy as np

from . import core, units as U

__version__ = "0.1"


def _date_of(path, tags):
    s = tags.get("TP_DATE") or (re.search(r"(20\d{6})", os.path.basename(path)) or [None, None])[1]
    return dt.datetime.strptime(s, "%Y%m%d").date() if s else None


def read_stack(path, grid=None, scale=1e-4, offset=0.0):
    """One input file -> ((6, r, c) reflectance with NaN, profile, date).

    Accepts a burncheck/timeprofile scene (6 bands + SCL, tags give scale and
    offset) or any 6-band reflectance GeoTIFF in band order blue, green, red,
    nir, swir1, swir2 (e.g. an Earth Engine or HLS export; pass scale/offset).
    With grid=(crs, transform, shape) it is resampled onto that grid."""
    import rasterio
    from rasterio.warp import reproject, Resampling
    with rasterio.open(path) as s:
        tags = s.tags()
        desc = [d or "" for d in s.descriptions]
        a = s.read().astype("float32")
        prof = s.profile
        nodata = s.nodata
    if grid is not None and (prof["crs"] != grid[0] or prof["transform"] != grid[1] or a.shape[1:] != grid[2]):
        dst = np.zeros((a.shape[0],) + grid[2], "float32")
        reproject(a, dst, src_transform=prof["transform"], src_crs=prof["crs"], dst_transform=grid[1],
                  dst_crs=grid[0], resampling=Resampling.nearest, src_nodata=nodata, dst_nodata=0)
        a, prof = dst, {**prof, "crs": grid[0], "transform": grid[1], "height": grid[2][0], "width": grid[2][1]}
    if a.shape[0] >= 7 and desc[6].upper() == "SCL":
        x = core.scl_to_nan(a[:6], a[6], float(tags.get("TP_SCALE", 1e-4)), float(tags.get("TP_OFFSET", 0)))
    else:
        x = a[:6] * scale + offset
        bad = ~np.isfinite(a[:6]).all(0) | (a[0] == (nodata if nodata is not None else 0))
        x[:, bad] = np.nan
    return x, prof, _date_of(path, tags)


def read_firms(path, start, end):
    """FIRMS CSV (any of MODIS/VIIRS archive or NRT downloads) -> list of (lon, lat, date) in (start, end]."""
    pts = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            d = dt.date.fromisoformat(r["acq_date"][:10])
            if start < d <= end:
                pts.append((float(r["longitude"]), float(r["latitude"]), d))
    return pts


def run(before, after, buildings, out, unit_file=None, places=None, firms=None, params=None,
        link=40.0, max_km2=0.5, cell=250.0, min_buildings=5, scale=1e-4, offset=0.0, n_chips=12, log=print):
    import geopandas as gpd
    import rasterio
    from rasterio.features import rasterize

    p = {**core.DEFAULTS, **(params or {})}
    os.makedirs(out, exist_ok=True)
    b0, prof, _ = read_stack(before[0], scale=scale, offset=offset)
    grid = (prof["crs"], prof["transform"], b0.shape[1:])
    bstacks, bdates, astacks, adates = [], [], [], []
    for paths, stacks, dates in ((before, bstacks, bdates), (after, astacks, adates)):
        for f in paths:
            x, _, d = read_stack(f, grid, scale, offset)
            stacks.append(x)
            dates.append(d)
    B, nB = core.composite(bstacks)
    A, nA = core.composite(astacks)
    log(f"before: {len(bstacks)} images {min(filter(None, bdates), default=None)}..{max(filter(None, bdates), default=None)}; "
        f"after: {len(astacks)} images {min(filter(None, adates), default=None)}..{max(filter(None, adates), default=None)}")

    # vector inputs in a metric CRS
    crs = prof["crs"]
    bld = gpd.read_file(buildings)
    if crs.is_geographic:
        c = bld.to_crs(4326).union_all().centroid
        crs = U.utm_crs(c.x, c.y)
    bld = bld.to_crs(crs)
    if unit_file:
        uu = gpd.read_file(unit_file).to_crs(crs).reset_index(drop=True)
        uu.insert(0, "unit_id", np.arange(1, len(uu) + 1))
        uu["kind"] = "given"
        uu["n_buildings"] = U.count_points(uu, bld.geometry.representative_point())
        uu["area_ha"] = (uu.geometry.area / 1e4).round(2)
    else:
        uu = U.settlements(bld, link, max_km2, cell, min_buildings)
    log(f"{len(bld)} buildings -> {len(uu)} units ({(uu.kind == 'block').sum()} town blocks)")
    rg = U.rings(uu)

    shape, tr = grid[2], grid[1]

    def burn(geoms, values, **kw):
        g = gpd.GeoSeries(geoms, crs=crs).to_crs(grid[0])
        pairs = [(gg, int(v)) for gg, v in zip(g, values) if gg is not None and not gg.is_empty]
        return rasterize(pairs, out_shape=shape, transform=tr, fill=0, dtype="int32", **kw) if pairs \
            else np.zeros(shape, "int32")

    bmask = burn(bld.geometry, np.ones(len(bld)), all_touched=True) > 0
    uid = burn(uu.geometry, uu.unit_id)
    rid = burn(rg.geometry, rg.unit_id)

    L = core.burn_layers(B, A, bmask, p)
    st = core.unit_stats(uid, len(uu), bmask, L, rid)
    cls, burned_pct, clear_pct, ring_pct, landscape = core.classify(st, p)

    uu["place"], uu["place_dist_m"] = U.name_units(uu, gpd.read_file(places) if places else None)
    i = uu.unit_id.to_numpy()
    uu["bld_px"] = st["bld_px"][i]
    uu["clear_pct"] = clear_pct[i].round(1)
    uu["burned_px"] = st["burned_px"][i]
    uu["burned_pct"] = burned_pct[i].round(1)
    uu["burned_ha"] = (st["burned_px"][i] * abs(tr.a * tr.e) / 1e4).round(2)
    uu["mean_anomaly"] = np.round(st["mean_anomaly"][i], 3)
    uu["ring_burned_pct"] = ring_pct[i].round(1)
    uu["landscape_fire"] = landscape[i]
    uu["class_code"] = cls[i]
    uu["class"] = [core.CLASSES[c] for c in cls[i]]

    win = (max(filter(None, bdates), default=None), min(filter(None, adates), default=None))
    if firms and all(win):
        pts = read_firms(firms, *win)
        g = gpd.GeoDataFrame(geometry=gpd.points_from_xy([q[0] for q in pts], [q[1] for q in pts]), crs=4326).to_crs(crs)
        buf = gpd.GeoDataFrame({"unit_id": uu.unit_id}, geometry=uu.buffer(375), crs=crs)
        j = gpd.sjoin(g, buf, predicate="within")
        uu["firms_n"] = j.groupby("unit_id").size().reindex(uu.unit_id).fillna(0).astype(int).to_numpy()
        log(f"FIRMS: {len(pts)} detections between {win[0]} and {win[1]}")
    uu["centroid_lon"], uu["centroid_lat"] = [np.round(v, 5) for v in
                                              (uu.geometry.centroid.to_crs(4326).x, uu.geometry.centroid.to_crs(4326).y)]

    # outputs
    rank = uu.class_code.map({2: 3, 1: 2, 0: 1, 9: 0})
    order = uu.assign(_r=rank).sort_values(["_r", "burned_pct"], ascending=False).drop(columns="_r")
    cols = [c for c in uu.columns if c != "geometry"]
    order[cols].to_csv(os.path.join(out, "summary.csv"), index=False)
    order.to_crs(4326).to_file(os.path.join(out, "units.geojson"), driver="GeoJSON")
    lay = np.full(shape, 0, "uint8")
    lay[bmask] = 1
    lay[L["burned"] & bmask] = 3
    lay[L["burned_open"] & ~bmask] = 2
    lay[~L["clear"]] = 255
    gp = dict(driver="GTiff", height=shape[0], width=shape[1], crs=grid[0], transform=tr, compress="deflate")
    with rasterio.open(os.path.join(out, "burn_classes.tif"), "w", count=1, dtype="uint8", nodata=255, **gp) as d:
        d.write(lay, 1)
        d.update_tags(CLASSES="0 open land, 1 building no change, 2 open land burned, 3 building burned, 255 not clear")
    with rasterio.open(os.path.join(out, "anomaly.tif"), "w", count=1, dtype="float32", nodata=np.nan, **gp) as d:
        d.write(L["anomaly"].astype("float32"), 1)
        d.set_band_description(1, "dNBR minus local building background")

    counts = {core.CLASSES[k]: int((cls[i] == k).sum()) for k in core.CLASSES}
    info = dict(tool="burncheck", version=__version__, run_at=dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
                before=[os.path.basename(f) for f in before], after=[os.path.basename(f) for f in after],
                before_dates=[str(d) for d in bdates], after_dates=[str(d) for d in adates],
                buildings=os.path.basename(buildings), n_buildings=int(len(bld)), units=unit_file or "auto",
                unit_rules=dict(link_m=link, max_km2=max_km2, cell_m=cell, min_buildings=min_buildings),
                params=p, unit_counts=counts,
                burned_ha_total=float(uu.burned_ha.sum()),
                buildings_burned_pct_aoi=round(100 * float((L["burned"] & bmask).sum()) / max(int((bmask & L["clear"]).sum()), 1), 3),
                firms=os.path.basename(firms) if firms else None)
    with open(os.path.join(out, "run.json"), "w") as f:
        json.dump(info, f, indent=1, default=str)
    log(f"units: {counts}; burned building area {info['burned_ha_total']:.1f} ha")

    try:
        from . import report
        report.map_png(os.path.join(out, "map.png"), B, A, lay, uu, grid, crs, info)
        report.chips_png(os.path.join(out, "chips.png"), B, A, L["anomaly"], order, grid, crs, n_chips)
    except ImportError as e:
        log(f"pictures skipped ({e})")
    return uu, info
