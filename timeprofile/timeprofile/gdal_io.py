"""The same functions as rio_io.py, with GDAL/OSR only.

QGIS ships GDAL's Python bindings and numpy but not rasterio, so the QGIS
plugin uses this module. Untested: no GDAL bindings were available where this
was written.
"""

import numpy as np
from osgeo import gdal, osr

gdal.UseExceptions()
NAME = "gdal"


class Info:
    def __init__(self, crs, gt, width, height, count, nodata, descriptions, tags):
        self.crs, self.gt = crs, tuple(gt)
        self.width, self.height, self.count = width, height, count
        self.nodata, self.descriptions, self.tags = nodata, descriptions, tags


class Handle:
    def __init__(self, path):
        self.ds = ds = gdal.Open(path)
        bands = [ds.GetRasterBand(i + 1) for i in range(ds.RasterCount)]
        self.info = Info(ds.GetProjection(), ds.GetGeoTransform(), ds.RasterXSize, ds.RasterYSize,
                         ds.RasterCount, [b.GetNoDataValue() for b in bands],
                         [b.GetDescription() or "" for b in bands], ds.GetMetadata() or {})

    def read(self, band, col0, row0, w, h):
        return self.ds.GetRasterBand(band).ReadAsArray(int(col0), int(row0), int(w), int(h))

    def close(self):
        self.ds = None


def open_raster(path):
    return Handle(path)


def info(path):
    return Handle(path).info


def make_transformer(dst_wkt):
    src = osr.SpatialReference()
    src.ImportFromEPSG(4326)
    src.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    dst = osr.SpatialReference()
    dst.ImportFromWkt(dst_wkt)
    dst.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    ct = osr.CoordinateTransformation(src, dst)

    def f(lons, lats):
        pts = ct.TransformPoints([(float(x), float(y)) for x, y in zip(lons, lats)])
        return np.array([p[0] for p in pts]), np.array([p[1] for p in pts])
    return f
