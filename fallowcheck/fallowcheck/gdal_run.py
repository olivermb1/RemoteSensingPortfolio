"""GDAL/OGR-only version of pipeline.run, for QGIS (no rasterio, geopandas or shapely).

Same rules (core.py) and same field_classes.tif. Grid units are cells of the
image grid (cell / pixel size pixels), so with a 10 m image and a 1000 m cell they
match the CLI's grid when the image origin sits on a round 1000 m line; with
your own polygons they match exactly. No place names and no picture.
"""

import csv
import json
import os

import numpy as np
from osgeo import gdal, ogr

from . import core
from .pipeline import seasons

gdal.UseExceptions()
ogr.UseExceptions()


def _warp(ds, ref, alg="near"):
    gt = ref.GetGeoTransform()
    b = (gt[0], gt[3] + gt[5] * ref.RasterYSize, gt[0] + gt[1] * ref.RasterXSize, gt[3])
    return gdal.Warp("", ds, format="MEM", dstSRS=ref.GetProjection(), width=ref.RasterXSize,
                     height=ref.RasterYSize, outputBounds=b, resampleAlg=alg)


def _ndvi(path, ref):
    ds = gdal.Open(path)
    if ds.GetGeoTransform() != ref.GetGeoTransform() or ds.RasterXSize != ref.RasterXSize \
            or ds.RasterYSize != ref.RasterYSize or ds.GetProjection() != ref.GetProjection():
        ds = _warp(ds, ref)
    a = ds.ReadAsArray()
    md = ds.GetMetadata()
    return core.ndvi(a[:6], a[6], float(md.get("TP_SCALE", 1e-4)), float(md.get("TP_OFFSET", 0)))


def run(scenes, baseline_years, target_year, season, out, cropland=None, crop_classes=(40,), unit_file=None,
        cell=1000.0, params=None, log=print):
    p = {**core.DEFAULTS, **(params or {})}
    os.makedirs(out, exist_ok=True)
    ref = max((gdal.Open(f) for f in scenes[:50]), key=lambda d: d.RasterXSize * d.RasterYSize)
    gt = ref.GetGeoTransform()
    shape = (ref.RasterYSize, ref.RasterXSize)
    px_ha = abs(gt[1] * gt[5]) / 1e4
    years = list(baseline_years) + [target_year]
    by = seasons(scenes, years, tuple(int(x) for x in season[0].split("-")), tuple(int(x) for x in season[1].split("-")))
    peaks, nobs = {}, {}
    for y in years:
        if not by[y]:
            raise RuntimeError(f"no scenes in the {y} season")
        peaks[y], nobs[y] = core.season_peak(np.stack([_ndvi(f, ref) for f in by[y]]), p["pctl"])
        log(f"{y}: {len(by[y])} scenes")
    base = np.stack([peaks[y] for y in baseline_years])
    cls = core.classify(peaks[target_year], base, nobs[target_year], p)
    loo = core.leave_one_out(base, np.stack([nobs[y] for y in baseline_years]), p)
    crop = None
    if cropland:
        crop = np.isin(_warp(gdal.Open(cropland), ref).ReadAsArray(), crop_classes)

    if unit_file:
        mem = gdal.GetDriverByName("MEM").Create("", shape[1], shape[0], 1, gdal.GDT_Int32)
        mem.SetGeoTransform(gt)
        mem.SetProjection(ref.GetProjection())
        lay = ogr.Open(unit_file).GetLayer()
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
        k = max(int(round(cell / abs(gt[1]))), 1)
        rr, cc = np.indices(shape)
        ncol = -(-shape[1] // k)
        uid = ((rr // k) * ncol + cc // k + 1).astype("int32")
        n = int(uid.max())
    t = core.unit_table(uid, n, cls, crop, px_ha)
    loo_pct = np.stack([core.unit_table(uid, n, c, crop, px_ha)["not_farmed_pct"] for c in loo])
    cons = np.stack([core.unit_mean(uid, n, core.field_contrast(peaks[y]), crop) for y in years])
    pr, normal = core.pattern_ratios(cons, len(years) - 1)
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        nmax, nmin = np.nanmax(loo_pct, 0), np.nanmin(normal, 0)
    rows = []
    for u in range(1, n + 1):
        if t["farmed_base_ha"][u] <= 0:
            continue
        r = {"unit_id": u, **{k: round(float(v[u]), 1) for k, v in t.items()}}
        r["normal_year_max_pct"] = round(float(nmax[u]), 1)
        r["pattern_ratio"] = round(float(pr[u]), 2)
        r["pattern_normal_min"] = round(float(nmin[u]), 2)
        r["pattern_lost"] = bool(pr[u] < min(nmin[u], 1.0) - 0.1 and pr[u] < 0.8)
        rows.append(r)
    rows.sort(key=lambda r: -r["not_farmed_ha"])
    with open(os.path.join(out, "summary.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["unit_id"])
        w.writeheader()
        w.writerows(rows)
    lay_ = cls.copy()
    if crop is not None:
        lay_[~crop & (lay_ != 255)] = 0
    d = gdal.GetDriverByName("GTiff").Create(os.path.join(out, "field_classes.tif"), shape[1], shape[0], 1,
                                             gdal.GDT_Byte, ["COMPRESS=DEFLATE"])
    d.SetGeoTransform(gt)
    d.SetProjection(ref.GetProjection())
    d.GetRasterBand(1).WriteArray(lay_)
    d.GetRasterBand(1).SetNoDataValue(255)
    d = None
    m = crop if crop is not None else np.ones(shape, bool)
    nf = float(((cls == 3) & m).sum() * px_ha)
    seen = float((((cls >= 1) & (cls <= 3)) & m).sum() * px_ha)
    info = dict(not_farmed_ha=round(nf, 1), not_farmed_pct=round(100 * nf / max(seen, 1e-9), 1),
                pattern_lost_units=sum(r["pattern_lost"] for r in rows), units_reported=len(rows))
    with open(os.path.join(out, "run.json"), "w") as f:
        json.dump(info, f, indent=1)
    log(f"{target_year}: {info}")
    return rows, info
