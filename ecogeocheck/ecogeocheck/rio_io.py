"""Raster reading and writing with rasterio (the command line).

gdal_io.py has the same functions with GDAL only, for QGIS.
"""

import numpy as np
import rasterio
from rasterio import warp
from rasterio.transform import Affine

NAME = "rasterio"


class Grid:
    def __init__(self, wkt, gt, width, height):
        self.wkt, self.gt, self.width, self.height = wkt, tuple(gt), width, height

    @property
    def bounds(self):
        g = self.gt
        return (g[0], g[3] + g[5] * self.height, g[0] + g[1] * self.width, g[3])


def read(path):
    """(float64 array with NaN for no-data, Grid, tags dict from every metadata domain)."""
    with rasterio.open(path) as ds:
        a = ds.read(1).astype("float64")
        if ds.nodata is not None:
            a[a == ds.nodata] = np.nan
        tags = dict(ds.tags())
        for ns in ds.tag_namespaces() or []:
            tags.update({f"{ns}_{k}": v for k, v in ds.tags(ns=ns).items()})
        tags.update({f"band1_{k}": v for k, v in ds.tags(1).items()})
        return a, Grid(ds.crs.to_wkt() if ds.crs else "", ds.transform.to_gdal(), ds.width, ds.height), tags


def read_tags(path):
    with rasterio.open(path) as ds:
        tags = dict(ds.tags())
        for ns in ds.tag_namespaces() or []:
            tags.update({f"{ns}_{k}": v for k, v in ds.tags(ns=ns).items()})
        return tags


def read_on_grid(path, grid, resampling="average"):
    """Band 1 of any raster warped onto grid, float64 with NaN outside."""
    out = np.full((grid.height, grid.width), np.nan, "float64")
    with rasterio.open(path) as ds:
        src = ds.read(1).astype("float64")
        if ds.nodata is not None:
            src[src == ds.nodata] = np.nan
        warp.reproject(src, out, src_transform=ds.transform, src_crs=ds.crs, src_nodata=np.nan,
                       dst_transform=Affine.from_gdal(*grid.gt), dst_crs=grid.wkt, dst_nodata=np.nan,
                       resampling=getattr(warp.Resampling, resampling))
    return out


def copy_with_geotransform(src, dst, gt):
    """Copy a GeoTIFF unchanged except for its geotransform (no resampling)."""
    with rasterio.open(src) as ds:
        prof = ds.profile.copy()
        prof.update(driver="GTiff", transform=Affine.from_gdal(*gt), compress="deflate")
        for k in ("blockxsize", "blockysize", "tiled", "interleave"):
            prof.pop(k, None)
        with rasterio.open(dst, "w", **prof) as out:
            out.write(ds.read())
            out.update_tags(**ds.tags())


def write(path, array, grid, nodata=None):
    prof = dict(driver="GTiff", width=grid.width, height=grid.height, count=1, dtype=array.dtype,
                crs=grid.wkt, transform=Affine.from_gdal(*grid.gt), compress="deflate", nodata=nodata)
    with rasterio.open(path, "w", **prof) as ds:
        ds.write(array, 1)


def bounds_lonlat(grid):
    return warp.transform_bounds(grid.wkt, "EPSG:4326", *grid.bounds)
