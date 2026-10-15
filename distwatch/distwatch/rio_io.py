"""Raster and vector work with rasterio, shapely and pyproj (the command line).

gdal_io.py offers the same functions with GDAL/OGR only, for QGIS.
"""

import numpy as np
import rasterio
from pyproj import Geod, Transformer
from rasterio import features, warp
from rasterio.transform import Affine
from rasterio.windows import Window
from shapely.geometry import mapping, shape
import shapely

NAME = "rasterio"
_GEOD = Geod(ellps="WGS84")


class Grid:
    def __init__(self, wkt, gt, width, height):
        self.wkt, self.gt, self.width, self.height = wkt, tuple(gt), width, height

    @property
    def affine(self):
        return Affine.from_gdal(*self.gt)

    @property
    def bounds(self):
        g = self.gt
        return (g[0], g[3] + g[5] * self.height, g[0] + g[1] * self.width, g[3])


def read(path):
    with rasterio.open(path) as ds:
        return ds.read(1), Grid(ds.crs.to_wkt(), ds.transform.to_gdal(), ds.width, ds.height)


def read_on_grid(path, grid, fill=0):
    """Nearest-neighbour warp of band 1 of path onto grid (for a forest mask)."""
    out = np.full((grid.height, grid.width), fill, "uint8")
    with rasterio.open(path) as ds:
        warp.reproject(rasterio.band(ds, 1), out, dst_transform=grid.affine, dst_crs=grid.wkt,
                       dst_nodata=fill, resampling=warp.Resampling.nearest)
    return out


def write(path, array, grid, nodata=None, descriptions=None):
    arr = array if array.ndim == 3 else array[None]
    prof = dict(driver="GTiff", width=grid.width, height=grid.height, count=arr.shape[0], dtype=arr.dtype,
                crs=grid.wkt, transform=grid.affine, compress="deflate", tiled=True, nodata=nodata)
    with rasterio.open(path, "w", **prof) as ds:
        ds.write(arr)
        for i, d in enumerate(descriptions or []):
            ds.set_band_description(i + 1, d)


def _to_ll(grid):
    return Transformer.from_crs(grid.wkt, "EPSG:4326", always_xy=True)


def lonlat(grid, rows, cols):
    """Lon/lat of pixel centres."""
    g = grid.gt
    x = g[0] + (np.asarray(cols) + 0.5) * g[1]
    y = g[3] + (np.asarray(rows) + 0.5) * g[5]
    return _to_ll(grid).transform(x, y)


def tile_center(grid):
    lon, lat = lonlat(grid, [grid.height / 2 - 0.5], [grid.width / 2 - 0.5])
    return float(lon[0]), float(lat[0])


def area_ha(geom):
    """Geodesic area of a GeoJSON geometry in lon/lat, hectares."""
    return abs(_GEOD.geometry_area_perimeter(shape(geom))[0]) / 1e4


def area_windows(feats, grid):
    """For each area that touches the grid: (index, (r0, r1, c0, c1), boolean mask)."""
    fwd = Transformer.from_crs("EPSG:4326", grid.wkt, always_xy=True)
    gt = grid.gt
    for i, f in enumerate(feats):
        g = shapely.transform(shape(f["geometry"]), fwd.transform, interleaved=False)
        x0, y0, x1, y1 = g.bounds
        c0 = max(int(np.floor((x0 - gt[0]) / gt[1])), 0)
        c1 = min(int(np.ceil((x1 - gt[0]) / gt[1])), grid.width)
        r0 = max(int(np.floor((y1 - gt[3]) / gt[5])), 0)
        r1 = min(int(np.ceil((y0 - gt[3]) / gt[5])), grid.height)
        if c1 <= c0 or r1 <= r0:
            continue
        tr = rasterio.windows.transform(Window(c0, r0, c1 - c0, r1 - r0), grid.affine)
        m = features.rasterize([(mapping(g), 1)], out_shape=(r1 - r0, c1 - c0), transform=tr,
                               fill=0, dtype="uint8").astype(bool)
        if m.any():
            yield i, (r0, r1, c0, c1), m


def polygonize(labels, grid):
    """{label: GeoJSON geometry in lon/lat} for each labelled patch."""
    inv = _to_ll(grid)
    out = {}
    for geom, val in features.shapes(labels, mask=labels > 0, transform=grid.affine, connectivity=8):
        g = shapely.transform(shape(geom), inv.transform, interleaved=False)
        v = int(val)
        out[v] = g if v not in out else out[v].union(g)
    return {k: mapping(v) for k, v in out.items()}
