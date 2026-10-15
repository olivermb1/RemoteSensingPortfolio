"""Reading a scene stack and writing results with rasterio (standalone use).

Two ways in (see catalog.py):
  * a manifest CSV with columns path, date, sensor and optionally fmask,
    scene_id (one multiband file per scene, bands blue..swir2);
  * a folder of NASA HLS v2.0 granules as downloaded from LP DAAC.
All scenes are placed on the grid of the first one (or of `grid_from`),
cut to `bbox` (degrees) if given.
"""

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import reproject, transform_bounds
from rasterio.windows import from_bounds

from . import catalog
from .sensors import COMMON_BANDS


class Grid:
    def __init__(self, crs, transform, width, height):
        self.crs, self.transform, self.width, self.height = crs, transform, width, height

    @classmethod
    def from_file(cls, path, bbox=None):
        with rasterio.open(path) as src:
            if bbox is None:
                return cls(src.crs, src.transform, src.width, src.height)
            b = transform_bounds("EPSG:4326", src.crs, *bbox)
            win = from_bounds(*b, transform=src.transform).round_offsets().round_lengths()
            return cls(src.crs, src.window_transform(win), int(win.width), int(win.height))

    def profile(self, **kw):
        p = dict(driver="GTiff", crs=self.crs, transform=self.transform, width=self.width,
                 height=self.height, compress="deflate", tiled=True, blockxsize=256, blockysize=256)
        p.update(kw)
        return p


def read_on_grid(path, grid, band=1, resampling=Resampling.nearest, dtype=None, fill=0):
    """Read one band of path onto grid, warping only if the grid differs."""
    with rasterio.open(path) as src:
        dtype = dtype or src.dtypes[band - 1]
        if src.crs == grid.crs and src.transform.a == grid.transform.a and src.transform.e == grid.transform.e:
            col = (grid.transform.c - src.transform.c) / src.transform.a
            row = (grid.transform.f - src.transform.f) / src.transform.e
            if abs(col - round(col)) < 1e-6 and abs(row - round(row)) < 1e-6:
                win = rasterio.windows.Window(round(col), round(row), grid.width, grid.height)
                return src.read(band, window=win, boundless=True, fill_value=fill).astype(dtype)
        out = np.full((grid.height, grid.width), fill, dtype)
        reproject(rasterio.band(src, band), out, dst_transform=grid.transform, dst_crs=grid.crs,
                  resampling=resampling, src_nodata=src.nodata, dst_nodata=fill)
        return out


def load(stack_path, bbox=None, fmask_bits=(0, 1, 2, 3), dilate=0, start=None, end=None,
         sensors=None, grid_from=None):
    """Load a manifest CSV or an HLS folder as a core.Stack."""
    scenes, scale, nodata = catalog.find_scenes(stack_path)
    scenes = catalog.filter_scenes(scenes, start, end, sensors)
    grid = Grid.from_file(grid_from or scenes[0]["bands"][0][0], bbox)
    read = lambda p, b, dtype, fill: read_on_grid(p, grid, b, Resampling.nearest, dtype, fill)  # noqa: E731
    return catalog.assemble(scenes, read, (grid.height, grid.width), fmask_bits, dilate, scale, nodata,
                            meta={"grid": grid})


def read_composite(path, grid, bands=None, scale=1e-4, nodata=None):
    """Read an existing composite onto the stack grid as reflectance (B, H, W).

    bands: 1-based band numbers in blue..swir2 order (default 1..6).
    A composite finer than the grid is averaged onto it.
    """
    bands = bands or list(range(1, len(COMMON_BANDS) + 1))
    with rasterio.open(path) as src:
        nd = src.nodata if nodata is None else nodata
        finer = abs(src.transform.a) < abs(grid.transform.a) * 0.9
    out = []
    for b in bands:
        a = read_on_grid(path, grid, b, Resampling.average if finer else Resampling.nearest, "float32",
                         nd if nd is not None else np.nan)
        if nd is not None:
            a[a == nd] = np.nan
        out.append(a * scale)
    return np.stack(out)


def write_layers(layers, grid, path, order):
    """Write the QA layers as one float32 GeoTIFF, band descriptions = names."""
    names = [n for n in order if n in layers]
    with rasterio.open(path, "w", **grid.profile(count=len(names), dtype="float32", nodata=-9999)) as d:
        for i, n in enumerate(names):
            a = layers[n].astype("float32")
            d.write(np.where(np.isfinite(a), a, -9999), i + 1)
        d.descriptions = tuple(n.upper() for n in names)
    return names


def write_composite(comp, grid, path):
    data = np.where(np.isfinite(comp), np.round(comp * 10000), -9999).astype("int16")
    with rasterio.open(path, "w", **grid.profile(count=comp.shape[0], dtype="int16", nodata=-9999)) as d:
        d.write(data)
        d.descriptions = tuple(COMMON_BANDS)
