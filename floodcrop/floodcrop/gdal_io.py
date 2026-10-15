"""GDAL-only I/O backend (same function names as io.py) so the pipeline runs
inside QGIS, which ships GDAL/OGR but not rasterio.

Zones here are (name, props, WKT geometry) tuples with a CRS given as WKT or
"EPSG:n"; the QGIS script builds them from the layer's features.
"""
import json

import numpy as np
from osgeo import gdal, ogr, osr

from . import core

gdal.UseExceptions()
ogr.UseExceptions()


class Grid:
    def __init__(self, wkt, gt, width, height):
        self.wkt, self.gt, self.width, self.height = wkt, gt, width, height

    @classmethod
    def of(cls, path):
        ds = gdal.Open(path)
        return cls(ds.GetProjection(), ds.GetGeoTransform(), ds.RasterXSize, ds.RasterYSize)

    @property
    def shape(self):
        return (self.height, self.width)

    @property
    def transform(self):  # rasterio/affine order a, b, c, d, e, f
        c, a, b, f, d, e = self.gt
        return (a, b, c, d, e, f)

    @property
    def crs(self):
        return self.wkt

    def bounds(self):
        c, a, _, f, _, e = self.gt
        return (c, f + e * self.height, c + a * self.width, f)

    def __str__(self):
        return self.wkt


def _srs(s):
    r = osr.SpatialReference()
    if str(s).upper().startswith("EPSG:"):
        r.ImportFromEPSG(int(str(s).split(":")[1]))
    else:
        r.SetFromUserInput(str(s))
    r.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return r


def is_geographic(grid):
    return bool(_srs(grid.wkt).IsGeographic())


def _warp(src, grid, alg="near", band=None, out_type=None, src_nodata=None, dst_nodata=None):
    kw = dict(format="MEM", dstSRS=grid.wkt, outputBounds=grid.bounds(), width=grid.width, height=grid.height,
              resampleAlg=alg)
    if band is not None:
        src = gdal.Translate("", src, format="VRT", bandList=[band])
    if out_type is not None:
        kw["outputType"] = out_type
    if src_nodata is not None:
        kw["srcNodata"] = src_nodata
    if dst_nodata is not None:
        kw["dstNodata"] = dst_nodata
    ds = gdal.Warp("", src, **kw)  # keep a reference: the band dies with its dataset
    arr = ds.GetRasterBand(1).ReadAsArray()
    ds = None
    return arr


def _nodata(path, band=1):
    return gdal.Open(path).GetRasterBand(band).GetNoDataValue()


def dswx_classes(path, grid):
    return core.decode_dswx(_warp(path, grid, "near", dst_nodata=255))


def mask_classes(path, grid, water_values=(1,), dry_values=(0,)):
    nd = _nodata(path)
    nd = 255 if nd is None else nd
    return core.decode_mask(_warp(path, grid, "near", dst_nodata=nd), water_values, dry_values, nd)


def sar_db(path, grid):
    a = _warp(path, grid, "average", out_type=gdal.GDT_Float32, dst_nodata=float("nan")).astype(np.float32)
    f = a[np.isfinite(a)]
    if f.size and np.nanmedian(f) < 0:
        return a
    return core.to_db(a)


def optical_classes(path, grid, cloud=None, cloud_kind="scl", scale=1.0, bands=(1, 2, 3, 4, 5, 6)):
    refl = [_warp(path, grid, "bilinear", band=b, out_type=gdal.GDT_Float32).astype(np.float32) for b in bands]
    invalid = None
    if cloud:
        c = _warp(cloud, grid, "near", dst_nodata=0 if cloud_kind == "scl" else 255)
        invalid = np.isin(c, core.SCL_INVALID) if cloud_kind == "scl" else core.fmask_invalid(c)
    return core.optical_water(*refl, invalid=invalid, scale=scale)


CROPLAND_VALUES = {"worldcover": (40,), "deafrica": (1,), "worldcereal": (100,), "binary": None}


def crop_fraction(path, grid, preset="worldcover", values=None):
    ds = gdal.Open(path)
    a = ds.GetRasterBand(1).ReadAsArray()
    nd = ds.GetRasterBand(1).GetNoDataValue()
    vals = values or CROPLAND_VALUES[preset]
    m = (np.isin(a, vals) if vals else (a > 0)).astype(np.float32)
    if nd is not None:
        m[a == nd] = np.nan
    if preset == "worldcover":
        m[a == 0] = np.nan
    mem = gdal.GetDriverByName("MEM").Create("", ds.RasterXSize, ds.RasterYSize, 1, gdal.GDT_Float32)
    mem.SetGeoTransform(ds.GetGeoTransform())
    mem.SetProjection(ds.GetProjection())
    mem.GetRasterBand(1).WriteArray(m)
    mem.GetRasterBand(1).SetNoDataValue(float("nan"))
    return _warp(mem, grid, "average", out_type=gdal.GDT_Float32, dst_nodata=float("nan")).astype(np.float32)


def permanent_mask(path, grid, threshold=0.8):
    a = _warp(path, grid, "bilinear", out_type=gdal.GDT_Float32).astype(np.float32)
    if np.nanmax(a) > 1.0:
        a = a / 100.0
    return np.nan_to_num(a, nan=0.0) >= threshold


def write(path, arr, grid, nodata=None, descriptions=None):
    arr = np.asarray(arr)
    if arr.ndim == 2:
        arr = arr[None]
    dt = {np.dtype("uint8"): gdal.GDT_Byte, np.dtype("float32"): gdal.GDT_Float32}[arr.dtype]
    ds = gdal.GetDriverByName("GTiff").Create(path, grid.width, grid.height, arr.shape[0], dt,
                                              options=["COMPRESS=DEFLATE", "TILED=YES"])
    ds.SetGeoTransform(grid.gt)
    ds.SetProjection(grid.wkt)
    for i in range(arr.shape[0]):
        b = ds.GetRasterBand(i + 1)
        if nodata is not None:
            b.SetNoDataValue(float(nodata))
        b.WriteArray(arr[i])
    ds = None


def read_zones(path, name_field=None):
    """Any OGR-readable polygon file -> ([(name, props, wkt)], crs wkt)."""
    ds = ogr.Open(path)
    lyr = ds.GetLayer(0)
    sr = lyr.GetSpatialRef()
    out = []
    for i, f in enumerate(lyr):
        props = {f.GetFieldDefnRef(j).GetName(): f.GetField(j) for j in range(f.GetFieldCount())}
        nm = props.get(name_field) if name_field else None
        if nm is None:
            for k in ("name", "NAME", "shapeName", "ADM2_EN", "ADM1_EN", "LZNAMEEN", "LZNAME", "FNID"):
                if props.get(k):
                    nm = props[k]
                    break
        out.append((str(nm if nm is not None else i), props, f.GetGeometryRef().ExportToWkt()))
    return out, (sr.ExportToWkt() if sr else "EPSG:4326")


def zone_masks(zones, zones_crs, grid):
    """Yield (name, props, geometry-as-GeoJSON-dict in zone CRS, mask)."""
    src, dst = _srs(zones_crs), _srs(grid.wkt)
    ct = None if src.IsSame(dst) else osr.CoordinateTransformation(src, dst)
    drv = ogr.GetDriverByName("Memory")
    for name, props, wkt in zones:
        g = ogr.CreateGeometryFromWkt(wkt)
        geo = json.loads(g.ExportToJson())
        if ct is not None:
            g.Transform(ct)
        mem = drv.CreateDataSource("z")
        lyr = mem.CreateLayer("z", dst, ogr.wkbUnknown)
        feat = ogr.Feature(lyr.GetLayerDefn())
        feat.SetGeometry(g)
        lyr.CreateFeature(feat)
        r = gdal.GetDriverByName("MEM").Create("", grid.width, grid.height, 1, gdal.GDT_Byte)
        r.SetGeoTransform(grid.gt)
        r.SetProjection(grid.wkt)
        gdal.RasterizeLayer(r, [1], lyr, burn_values=[1])
        yield name, props, geo, r.GetRasterBand(1).ReadAsArray().astype(bool)
