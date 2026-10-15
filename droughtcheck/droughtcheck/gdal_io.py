"""Raster input/output with GDAL only (what QGIS ships). Same interface as rio.py.
A profile is a dict: transform (GDAL geotransform tuple), crs (WKT), width, height."""
from __future__ import annotations

import re

import numpy as np
from osgeo import gdal, osr

gdal.UseExceptions()


def read_stack(path, band_filter=None):
    ds = gdal.Open(path)
    idx, labels = [], []
    for i in range(1, ds.RasterCount + 1):
        desc = ds.GetRasterBand(i).GetDescription() or f"band {i}"
        if band_filter is None or desc.startswith(band_filter):
            idx.append(i); labels.append(desc)
    arrs = []
    for i in idx:
        b = ds.GetRasterBand(i)
        a = b.ReadAsArray().astype("float64")
        nd = b.GetNoDataValue()
        if nd is not None and not np.isnan(nd):
            a[a == nd] = np.nan
        arrs.append(a)
    prof = dict(transform=ds.GetGeoTransform(), crs=ds.GetProjection(), width=ds.RasterXSize,
                height=ds.RasterYSize, tags=ds.GetMetadata())
    return np.stack(arrs), prof, labels


def month_of(label):
    m = re.search(r"(\d{4})-(\d{2})", label or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def pixel_latitudes(prof):
    gt = prof["transform"]
    cols, rows = np.meshgrid(np.arange(prof["width"]) + 0.5, np.arange(prof["height"]) + 0.5)
    xs = gt[0] + cols * gt[1] + rows * gt[2]
    ys = gt[3] + cols * gt[4] + rows * gt[5]
    src = osr.SpatialReference(); src.ImportFromWkt(prof["crs"])
    if src.IsGeographic():
        return ys
    dst = osr.SpatialReference(); dst.ImportFromEPSG(4326)
    for s in (src, dst):
        s.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    ct = osr.CoordinateTransformation(src, dst)
    pts = ct.TransformPoints(np.c_[xs.ravel(), ys.ravel()].tolist())
    return np.array([p[1] for p in pts]).reshape(xs.shape)


def _mem(stack, prof):
    drv = gdal.GetDriverByName("MEM")
    ds = drv.Create("", prof["width"], prof["height"], stack.shape[0], gdal.GDT_Float64)
    ds.SetGeoTransform(prof["transform"]); ds.SetProjection(prof["crs"])
    for i in range(stack.shape[0]):
        b = ds.GetRasterBand(i + 1); b.SetNoDataValue(np.nan); b.WriteArray(stack[i])
    return ds


def regrid(stack, src_prof, dst_prof, method="bilinear"):
    src = _mem(np.asarray(stack, "float64"), src_prof)
    gt = dst_prof["transform"]
    bounds = (gt[0], gt[3] + gt[5] * dst_prof["height"], gt[0] + gt[1] * dst_prof["width"], gt[3])
    out = gdal.Warp("", src, format="MEM", dstSRS=dst_prof["crs"], outputBounds=bounds,
                    width=dst_prof["width"], height=dst_prof["height"], resampleAlg=method,
                    srcNodata=np.nan, dstNodata=np.nan)
    return np.stack([out.GetRasterBand(i + 1).ReadAsArray() for i in range(out.RasterCount)])


def write_stack(path, stack, prof, labels, dtype="float32", nodata=np.nan, tags=None):
    stack = np.asarray(stack)
    if stack.ndim == 2:
        stack = stack[None]
    gtype = {"float32": gdal.GDT_Float32, "uint8": gdal.GDT_Byte}[dtype]
    ds = gdal.GetDriverByName("GTiff").Create(path, prof["width"], prof["height"], stack.shape[0], gtype,
                                              options=["COMPRESS=DEFLATE"])
    ds.SetGeoTransform(prof["transform"]); ds.SetProjection(prof["crs"])
    for i in range(stack.shape[0]):
        b = ds.GetRasterBand(i + 1)
        if nodata is not None:
            b.SetNoDataValue(float(nodata))
        b.WriteArray(stack[i].astype(dtype)); b.SetDescription(labels[i])
    if tags:
        ds.SetMetadata({k: str(v) for k, v in tags.items()})
    ds = None
