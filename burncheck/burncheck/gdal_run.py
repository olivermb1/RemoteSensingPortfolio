"""GDAL/OGR-only version of pipeline.run, for QGIS (no rasterio, geopandas or shapely).

Same pixel rules (core.py). With units given, per-unit burned and clear counts
match the CLI; the open-land ring is a pixel dilation here, so ring_burned_pct
can differ slightly.
Without units, settlements are built on the pixel grid instead of from vector
buffers: building pixels are grown by `link`/2 metres, joined into connected
groups, and groups larger than `max_km2` are cut into `cell`-metre blocks.
Outlines are pixel-shaped, so counts differ slightly from the CLI.
"""

import csv
import json
import os
import re

import numpy as np
from osgeo import gdal, ogr, osr

from . import core

gdal.UseExceptions()
ogr.UseExceptions()


def read_stack(path, ref=None):
    ds = gdal.Open(path)
    if ref is not None and (ds.GetGeoTransform() != ref.GetGeoTransform() or ds.RasterXSize != ref.RasterXSize
                            or ds.RasterYSize != ref.RasterYSize):
        ds = gdal.Warp("", ds, format="MEM", dstSRS=ref.GetProjection(), width=ref.RasterXSize,
                       height=ref.RasterYSize, outputBounds=_bounds(ref), resampleAlg="near")
    a = ds.ReadAsArray().astype("float32")
    desc = [ds.GetRasterBand(i + 1).GetDescription() for i in range(ds.RasterCount)]
    md = ds.GetMetadata()
    if a.shape[0] >= 7 and desc[6].upper() == "SCL":
        x = core.scl_to_nan(a[:6], a[6], float(md.get("TP_SCALE", 1e-4)), float(md.get("TP_OFFSET", 0)))
    else:
        nd = ds.GetRasterBand(1).GetNoDataValue()
        x = a[:6] * float(md.get("TP_SCALE", 1e-4))
        x[:, (a[0] == (nd if nd is not None else 0)) | ~np.isfinite(a[:6]).all(0)] = np.nan
    m = re.search(r"(20\d{6})", md.get("TP_DATE", "") or os.path.basename(path))
    return x, ds, (m[1] if m else None)


def _bounds(ds):
    gt = ds.GetGeoTransform()
    return (gt[0], gt[3] + gt[5] * ds.RasterYSize, gt[0] + gt[1] * ds.RasterXSize, gt[3])


def _mem_like(ref, dtype=gdal.GDT_Int32):
    m = gdal.GetDriverByName("MEM").Create("", ref.RasterXSize, ref.RasterYSize, 1, dtype)
    m.SetGeoTransform(ref.GetGeoTransform())
    m.SetProjection(ref.GetProjection())
    return m


def rasterize(layer, ref, attr=None, all_touched=False):
    m = _mem_like(ref)
    opts = ["ALL_TOUCHED=TRUE"] if all_touched else []
    if attr:
        gdal.RasterizeLayer(m, [1], layer, options=opts + [f"ATTRIBUTE={attr}"])
    else:
        gdal.RasterizeLayer(m, [1], layer, burn_values=[1], options=opts)
    return m.ReadAsArray()


def _label(mask):
    try:
        from scipy import ndimage
        return ndimage.label(mask)
    except ImportError:  # union-find over runs, pure numpy/python (slower, no scipy needed)
        lab = np.zeros(mask.shape, "int32")
        parent = [0]

        def find(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a
        for r in range(mask.shape[0]):
            row = mask[r]
            c = 0
            while c < row.size:
                if not row[c]:
                    c += 1
                    continue
                c1 = c
                while c1 < row.size and row[c1]:
                    c1 += 1
                parent.append(len(parent))
                k = len(parent) - 1
                lab[r, c:c1] = k
                if r:
                    for up in np.unique(lab[r - 1, max(c - 1, 0):min(c1 + 1, row.size)]):
                        if up:
                            a, b = find(int(up)), find(k)
                            parent[max(a, b)] = min(a, b)
                c = c1
        roots = np.array([find(i) for i in range(len(parent))])
        _, comp = np.unique(roots, return_inverse=True)
        lab = comp[lab].astype("int32")
        return lab, int(lab.max())


def grid_units(bmask, px_m, link=40.0, max_km2=0.5, cell=250.0, min_buildings=5, centroids=None):
    """Settlement / block id raster from the building mask."""
    k = max(int(round(link / 2 / px_m)), 0)
    grown = bmask.copy()
    for _ in range(k):  # 4-neighbour dilation, k steps
        g = grown.copy()
        g[1:] |= grown[:-1]
        g[:-1] |= grown[1:]
        g[:, 1:] |= grown[:, :-1]
        g[:, :-1] |= grown[:, 1:]
        grown = g
    lab, n = _label(grown)
    size = np.bincount(lab.ravel(), minlength=n + 1) * px_m * px_m / 1e6
    big = size[lab] > max_km2
    step = max(int(round(cell / px_m)), 1)
    rr, cc = np.indices(lab.shape)
    block = (rr // step) * (lab.shape[1] // step + 1) + cc // step + 1
    key = np.where(lab == 0, 0, np.where(big, lab.astype("int64") * 10**7 + block, lab))
    _, ids = np.unique(key, return_inverse=True)
    ids = ids.reshape(lab.shape).astype("int32")  # 0 stays 0 as the smallest key
    kind_big = np.zeros(ids.max() + 1, bool)
    kind_big[ids[big]] = True
    if centroids is not None:  # drop units with few buildings
        nb = np.bincount(ids[centroids[0], centroids[1]], minlength=ids.max() + 1)
        keep = nb >= min_buildings
        keep[0] = False
        remap = np.zeros(len(keep), "int32")
        remap[keep] = np.arange(1, keep.sum() + 1)
        ids = remap[ids]
        kind_big = np.concatenate([[False], kind_big[keep]])
        nb = np.concatenate([[0], nb[keep]])
    return ids, int(ids.max()), kind_big, nb


def run(before, after, buildings, out, unit_file=None, params=None, link=40.0, max_km2=0.5, cell=250.0,
        min_buildings=5, log=print):
    p = {**core.DEFAULTS, **(params or {})}
    os.makedirs(out, exist_ok=True)
    _, ref, _ = read_stack(before[0])
    B, _ = core.composite([read_stack(f, ref)[0] for f in before])
    A, _ = core.composite([read_stack(f, ref)[0] for f in after])
    gt = ref.GetGeoTransform()
    px_m = abs(gt[1])
    srs = osr.SpatialReference(wkt=ref.GetProjection())

    bsrc = ogr.Open(buildings)
    blay = bsrc.GetLayer()
    bmask = rasterize(blay, ref, all_touched=True) > 0
    # building centres in pixel coordinates
    tr = osr.CoordinateTransformation(blay.GetSpatialRef(), srs)
    for s in (blay.GetSpatialRef(), srs):
        s.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    rows, cols = [], []
    blay.ResetReading()
    for f in blay:
        g = f.GetGeometryRef()
        if g is None:
            continue
        c = g.Centroid()
        x, y, _ = tr.TransformPoint(c.GetX(), c.GetY())
        cols.append(int((x - gt[0]) / gt[1]))
        rows.append(int((y - gt[3]) / gt[5]))
    rows, cols = np.array(rows), np.array(cols)
    ok = (rows >= 0) & (rows < ref.RasterYSize) & (cols >= 0) & (cols < ref.RasterXSize)
    cen = (rows[ok], cols[ok])

    if unit_file:
        usrc = ogr.Open(unit_file)
        ulay = usrc.GetLayer()
        mem = ogr.GetDriverByName("Memory").CreateDataSource("u")
        ml = mem.CreateLayer("u", ulay.GetSpatialRef(), ogr.wkbMultiPolygon)
        ml.CreateField(ogr.FieldDefn("uid", ogr.OFTInteger))
        for i, f in enumerate(ulay, 1):
            nf = ogr.Feature(ml.GetLayerDefn())
            nf.SetGeometry(f.GetGeometryRef().Clone())
            nf.SetField("uid", i)
            ml.CreateFeature(nf)
        uid = rasterize(ml, ref, "uid")
        n = int(ml.GetFeatureCount())
        kind_big = np.zeros(n + 1, bool)
        nb = np.bincount(uid[cen], minlength=n + 1)
    else:
        uid, n, kind_big, nb = grid_units(bmask, px_m, link, max_km2, cell, min_buildings, cen)
    log(f"{len(rows)} buildings -> {n} units")

    # ring: open land 50..300 m around each unit (pixel approximation by dilation of each unit's id)
    grown = uid.copy()
    inner = uid.copy()
    for step in range(int(round(300 / px_m))):
        g = grown.copy()
        for sl_to, sl_from in (((slice(1, None),), (slice(None, -1),)), ((slice(None, -1),), (slice(1, None),)),
                               ((slice(None), slice(1, None)), (slice(None), slice(None, -1))),
                               ((slice(None), slice(None, -1)), (slice(None), slice(1, None)))):
            src = grown[sl_from]
            dst = g[sl_to]
            fill = (dst == 0) & (src > 0)
            dst[fill] = src[fill]
        grown = g
        if step + 1 == int(round(50 / px_m)):
            inner = grown.copy()
    ring = np.where(inner == 0, grown, 0)

    L = core.burn_layers(B, A, bmask, p)
    st = core.unit_stats(uid, n, bmask, L, ring)
    cls, burned_pct, clear_pct, ring_pct, landscape = core.classify(st, p)

    # polygons of units with their numbers
    m = _mem_like(ref)
    m.GetRasterBand(1).WriteArray(uid)
    drv = ogr.GetDriverByName("GeoJSON")
    path = os.path.join(out, "units.geojson")
    if os.path.exists(path):
        drv.DeleteDataSource(path)
    tmp = ogr.GetDriverByName("Memory").CreateDataSource("p")
    pl = tmp.CreateLayer("p", srs, ogr.wkbPolygon)
    pl.CreateField(ogr.FieldDefn("unit_id", ogr.OFTInteger))
    gdal.Polygonize(m.GetRasterBand(1), m.GetRasterBand(1), pl, 0)
    geoms = {}
    for f in pl:
        u = f.GetField("unit_id")
        g = geoms.setdefault(u, ogr.Geometry(ogr.wkbMultiPolygon))
        g.AddGeometry(f.GetGeometryRef().Clone())
    wgs = osr.SpatialReference()
    wgs.ImportFromEPSG(4326)
    wgs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    to_wgs = osr.CoordinateTransformation(srs, wgs)
    rows_out = []
    for u in range(1, n + 1):
        rows_out.append(dict(unit_id=u, kind="given" if unit_file else ("block" if kind_big[u] else "settlement"),
                             n_buildings=int(nb[u]), bld_px=int(st["bld_px"][u]), clear_pct=round(float(clear_pct[u]), 1),
                             burned_px=int(st["burned_px"][u]), burned_pct=round(float(burned_pct[u]), 1),
                             burned_ha=round(float(st["burned_px"][u]) * px_m * px_m / 1e4, 2),
                             mean_anomaly=round(float(st["mean_anomaly"][u]), 3),
                             ring_burned_pct=round(float(ring_pct[u]), 1), landscape_fire=bool(landscape[u]),
                             class_code=int(cls[u]), **{"class": core.CLASSES[int(cls[u])]}))
    with open(os.path.join(out, "summary.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows_out[0]) if rows_out else ["unit_id"])
        w.writeheader()
        w.writerows(rows_out)
    feats = []
    for r in rows_out:
        g = geoms.get(r["unit_id"])
        if g is None:
            continue
        g = g.Clone()
        g.Transform(to_wgs)
        feats.append({"type": "Feature", "properties": r, "geometry": json.loads(g.ExportToJson())})
    with open(path, "w") as f:
        json.dump({"type": "FeatureCollection", "features": feats}, f)
    lay = np.zeros(bmask.shape, "uint8")
    lay[bmask] = 1
    lay[L["burned"] & bmask] = 3
    lay[L["burned_open"] & ~bmask] = 2
    lay[~L["clear"]] = 255
    d = gdal.GetDriverByName("GTiff").Create(os.path.join(out, "burn_classes.tif"), ref.RasterXSize, ref.RasterYSize,
                                             1, gdal.GDT_Byte, ["COMPRESS=DEFLATE"])
    d.SetGeoTransform(gt)
    d.SetProjection(ref.GetProjection())
    d.GetRasterBand(1).WriteArray(lay)
    d.GetRasterBand(1).SetNoDataValue(255)
    d = None
    counts = {core.CLASSES[k]: int((cls[1:] == k).sum()) for k in core.CLASSES}
    log(f"units: {counts}")
    return rows_out, counts
