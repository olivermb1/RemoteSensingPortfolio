"""Raster access with rasterio. The QGIS plugin uses gdal_io.py instead, which
has the same three functions."""

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.warp import transform as _transform
from rasterio.windows import Window

NAME = "rasterio"


class Info:
    """What the extractor needs to know about one raster file."""

    def __init__(self, crs, gt, width, height, count, nodata, descriptions, tags):
        self.crs, self.gt = crs, tuple(gt)
        self.width, self.height, self.count = width, height, count
        self.nodata, self.descriptions, self.tags = nodata, descriptions, tags


class Handle:
    def __init__(self, path):
        self.ds = rasterio.open(path)
        t = self.ds.transform
        self.info = Info(self.ds.crs.to_wkt() if self.ds.crs else "", (t.c, t.a, t.b, t.f, t.d, t.e),
                         self.ds.width, self.ds.height, self.ds.count, list(self.ds.nodatavals),
                         [d or "" for d in self.ds.descriptions], self.ds.tags())

    def read(self, band, col0, row0, w, h):
        return self.ds.read(band, window=Window(col0, row0, w, h))

    def close(self):
        self.ds.close()


def open_raster(path):
    return Handle(path)


def info(path):
    h = Handle(path)
    try:
        return h.info
    finally:
        h.close()


def make_transformer(dst_wkt):
    """f(lons, lats) -> (xs, ys) in dst_wkt."""
    dst = CRS.from_wkt(dst_wkt)

    def f(lons, lats):
        xs, ys = _transform(CRS.from_epsg(4326), dst, list(map(float, lons)), list(map(float, lats)))
        return np.asarray(xs), np.asarray(ys)
    return f
