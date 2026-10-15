"""GDAL/OGR-only version of pipeline.run, for QGIS (no rasterio, geopandas or shapely).

Same rules (core.py), same first_seen.tif and per-area footprints. Detected
area outlines are the raw pixel polygons (the CLI smooths them with a buffer),
and place names are not added.
"""

import csv
import json
import os
import re
from collections import defaultdict

import numpy as np
from osgeo import gdal, ogr, osr

from . import core
from .pipeline import _months_between

gdal.UseExceptions()
ogr.UseExceptions()


def _read(path, ref):
    ds = gdal.Open(path)
    if (ds.GetGeoTransform() != ref.GetGeoTransform() or ds.RasterXSize != ref.RasterXSize
            or ds.RasterYSize != ref.RasterYSize or ds.GetProjection() != ref.GetProjection()):
        gt = ref.GetGeoTransform()
        bounds = (gt[0], gt[3] + gt[5] * ref.RasterYSize, gt[0] + gt[1] * ref.RasterXSize, gt[3])
        ds = gdal.Warp("", ds, format="MEM", dstSRS=ref.GetProjection(), width=ref.RasterXSize,
                       height=ref.RasterYSize, outputBounds=bounds, resampleAlg="near", srcNodata=0, dstNodata=0)
    a = ds.ReadAsArray()
    md = ds.GetMetadata()
    return core.indices(a[:6], a[6], float(md.get("TP_SCALE", 1e-4)), float(md.get("TP_OFFSET", 0)))


def _monthly(paths, ref, months):
    by = defaultdict(list)
    for f in paths:
        m = re.search(r"(20\d{6})", os.path.basename(f))
        if m and m[1][:6] in months:
            by[m[1][:6]].append(f)
    return {m: core.median(np.stack([_read(f, ref) for f in by[m]])) for m in sorted(by)}


def run(scenes, baseline, period, out, unit_file=None, dry_months=core.DRY_MONTHS, params=None, log=print):
    p = {**core.DEFAULTS, **(params or {})}
    os.makedirs(out, exist_ok=True)
    ref = gdal.Open(scenes[0])
    gt = ref.GetGeoTransform()
    px_ha = abs(gt[1] * gt[5]) / 1e4
    bm = {m for m in _months_between(*baseline) if int(m[4:]) in dry_months}
    am = [m for m in _months_between(*period) if int(m[4:]) in dry_months]
    by_cal = defaultdict(list)
    for m, x in _monthly(scenes, ref, bm).items():
        by_cal[int(m[4:])].append(x)
    if not by_cal:
        raise RuntimeError("no clear baseline scenes")
    base_cal = {k: core.median(np.stack(v)) for k, v in by_cal.items()}
    months, S = [], []
    for m in am:
        cur = _monthly(scenes, ref, {m}).get(m)
        if cur is None:
            continue
        k = int(m[4:])
        b = base_cal[min(base_cal, key=lambda c: min((c - k) % 12, (k - c) % 12))]
        months.append(m)
        S.append(core.shelter_month(cur, b, p))
    P = core.smooth(np.stack(S))
    first = core.first_seen(P, p["persist"])

    mem = gdal.GetDriverByName("MEM").Create("", ref.RasterXSize, ref.RasterYSize, 1, gdal.GDT_Int32)
    mem.SetGeoTransform(gt)
    mem.SetProjection(ref.GetProjection())
    if unit_file:
        src = ogr.Open(unit_file)
        lay = src.GetLayer()
        ml = ogr.GetDriverByName("Memory").CreateDataSource("u").CreateLayer("u", lay.GetSpatialRef(), ogr.wkbMultiPolygon)
        ml.CreateField(ogr.FieldDefn("uid", ogr.OFTInteger))
        for i, f in enumerate(lay, 1):
            nf = ogr.Feature(ml.GetLayerDefn())
            nf.SetGeometry(f.GetGeometryRef().Clone())
            nf.SetField("uid", i)
            ml.CreateFeature(nf)
        gdal.RasterizeLayer(mem, [1], ml, options=["ATTRIBUTE=uid"])
        uid = mem.ReadAsArray()
        n = ml.GetFeatureCount()
    else:
        lab, n0 = core.label(first >= 0, p["join_px"])
        size = np.bincount(lab.ravel(), minlength=n0 + 1) * px_ha
        keep = size >= p["min_area_ha"]
        keep[0] = False
        remap = np.zeros(n0 + 1, "int32")
        remap[keep] = np.arange(1, keep.sum() + 1)
        uid = remap[lab]
        n = int(keep.sum())
    foot, obs = core.area_series(P, uid, n, first, px_ha)

    rows = []
    for k in range(1, n + 1):
        fin = foot[-1, k]
        def reach(frac):
            hit = np.nonzero(foot[:, k] >= max(fin * frac, 1.0))[0]
            return months[hit[0]] if len(hit) and fin > 0 else ""
        rows.append(dict(unit_id=k, footprint_ha=round(fin, 1), first_month=reach(0.1), half_month=reach(0.5),
                         growth_ha_last3=round(fin - foot[max(len(months) - 4, 0), k], 1),
                         observed_pct_last=round(float(obs[-1, k]), 0)))
    rows.sort(key=lambda r: -r["footprint_ha"])
    with open(os.path.join(out, "summary.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["unit_id"])
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(out, "timeseries.csv"), "w") as f:
        f.write("unit_id,month,footprint_ha,observed_pct\n")
        for k in range(1, n + 1):
            for t, m in enumerate(months):
                f.write(f"{k},{m[:4]}-{m[4:]},{foot[t, k]:.2f},{obs[t, k]:.0f}\n")
    fs = np.where(first >= 0, np.array([int(m) for m in months], "int32")[np.clip(first, 0, None)], 0)
    d = gdal.GetDriverByName("GTiff").Create(os.path.join(out, "first_seen.tif"), ref.RasterXSize, ref.RasterYSize, 1,
                                             gdal.GDT_Int32, ["COMPRESS=DEFLATE"])
    d.SetGeoTransform(gt)
    d.SetProjection(ref.GetProjection())
    d.GetRasterBand(1).WriteArray(fs)
    d.GetRasterBand(1).SetNoDataValue(0)
    d = None
    if not unit_file:  # polygons of detected areas
        mem.GetRasterBand(1).WriteArray(uid)
        path = os.path.join(out, "areas.geojson")
        if os.path.exists(path):
            os.remove(path)
        ds = ogr.GetDriverByName("GeoJSON").CreateDataSource(path)
        srs = osr.SpatialReference(wkt=ref.GetProjection())
        pl = ds.CreateLayer("areas", srs, ogr.wkbPolygon)
        pl.CreateField(ogr.FieldDefn("unit_id", ogr.OFTInteger))
        gdal.Polygonize(mem.GetRasterBand(1), mem.GetRasterBand(1), pl, 0)
        ds = None
    info = dict(months=months, n_areas=n, total_footprint_ha=round(float(foot[-1, 1:].sum()), 1), params=p)
    with open(os.path.join(out, "run.json"), "w") as f:
        json.dump(info, f, indent=1)
    log(f"{n} areas, {info['total_footprint_ha']} ha by {months[-1]}")
    return rows, info
