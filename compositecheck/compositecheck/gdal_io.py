"""The same reading and writing as io.py, with GDAL's Python bindings only.

QGIS ships GDAL (osgeo) and numpy but not rasterio, so the QGIS Processing
script uses this module. The command line falls back to it when rasterio is
not installed.
"""

import numpy as np
from osgeo import gdal, osr

from . import catalog
from .sensors import COMMON_BANDS

gdal.UseExceptions()

_NP = {"int16": gdal.GDT_Int16, "uint8": gdal.GDT_Byte, "float32": gdal.GDT_Float32, "uint16": gdal.GDT_UInt16}


class Grid:
    def __init__(self, wkt, gt, width, height):
        self.wkt, self.gt, self.width, self.height = wkt, gt, width, height

    @property
    def bounds(self):
        g = self.gt
        return (g[0], g[3] + g[5] * self.height, g[0] + g[1] * self.width, g[3])

    @classmethod
    def from_file(cls, path, bbox=None):
        ds = gdal.Open(path)
        gt, w, h, wkt = ds.GetGeoTransform(), ds.RasterXSize, ds.RasterYSize, ds.GetProjection()
        if bbox is None:
            return cls(wkt, gt, w, h)
        src = osr.SpatialReference()
        src.ImportFromEPSG(4326)
        src.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        dst = osr.SpatialReference(wkt=wkt)
        dst.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        tr = osr.CoordinateTransformation(src, dst)
        W, S, E, N = bbox
        xs, ys = [], []
        for i in range(21):  # densify the edges, like rasterio's transform_bounds
            f = i / 20
            for x, y in ((W + f * (E - W), S), (W + f * (E - W), N), (W, S + f * (N - S)), (E, S + f * (N - S))):
                px, py, _ = tr.TransformPoint(x, y)
                xs.append(px)
                ys.append(py)
        c0 = int(round((min(xs) - gt[0]) / gt[1]))
        c1 = int(round((max(xs) - gt[0]) / gt[1]))
        r0 = int(round((max(ys) - gt[3]) / gt[5]))
        r1 = int(round((min(ys) - gt[3]) / gt[5]))
        return cls(wkt, (gt[0] + c0 * gt[1], gt[1], 0.0, gt[3] + r0 * gt[5], 0.0, gt[5]), c1 - c0, r1 - r0)


def read_on_grid(path, grid, band=1, resampling="near", dtype="int16", fill=0):
    """Warp one band of path (a file name or an open dataset) onto grid."""
    out = gdal.Warp("", path, format="MEM", outputBounds=grid.bounds, width=grid.width, height=grid.height,
                    dstSRS=grid.wkt, resampleAlg=resampling, outputType=_NP[dtype], srcBands=[band],
                    dstNodata=fill, multithread=True)
    return out.GetRasterBand(1).ReadAsArray().astype(dtype)


def load(stack_path, bbox=None, fmask_bits=(0, 1, 2, 3), dilate=0, start=None, end=None,
         sensors=None, grid_from=None, progress=None):
    scenes, scale, nodata = catalog.find_scenes(stack_path)
    scenes = catalog.filter_scenes(scenes, start, end, sensors)
    grid = Grid.from_file(grid_from or scenes[0]["bands"][0][0], bbox)
    read = lambda p, b, dtype, fill: read_on_grid(p, grid, b, "near", dtype, fill)  # noqa: E731
    return catalog.assemble(scenes, read, (grid.height, grid.width), fmask_bits, dilate, scale, nodata,
                            meta={"grid": grid}, progress=progress)


def read_composite(path, grid, bands=None, scale=1e-4, nodata=None):
    bands = bands or list(range(1, len(COMMON_BANDS) + 1))
    ds = gdal.Open(path)
    nd = ds.GetRasterBand(1).GetNoDataValue() if nodata is None else nodata
    finer = abs(ds.GetGeoTransform()[1]) < abs(grid.gt[1]) * 0.9
    out = []
    for b in bands:
        a = read_on_grid(path, grid, b, "average" if finer else "near", "float32",
                         nd if nd is not None else -9999)
        a[a == (nd if nd is not None else -9999)] = np.nan
        out.append(a * scale)
    return np.stack(out)


def _create(path, grid, count, gdt):
    ds = gdal.GetDriverByName("GTiff").Create(path, grid.width, grid.height, count, gdt,
                                              options=["COMPRESS=DEFLATE", "TILED=YES"])
    ds.SetGeoTransform(grid.gt)
    ds.SetProjection(grid.wkt)
    return ds


def write_layers(layers, grid, path, order):
    names = [n for n in order if n in layers]
    ds = _create(path, grid, len(names), gdal.GDT_Float32)
    for i, n in enumerate(names):
        a = layers[n].astype("float32")
        band = ds.GetRasterBand(i + 1)
        band.WriteArray(np.where(np.isfinite(a), a, -9999))
        band.SetNoDataValue(-9999)
        band.SetDescription(n.upper())
    ds = None
    return names


def write_composite(comp, grid, path):
    ds = _create(path, grid, comp.shape[0], gdal.GDT_Int16)
    for i in range(comp.shape[0]):
        band = ds.GetRasterBand(i + 1)
        band.WriteArray(np.where(np.isfinite(comp[i]), np.round(comp[i] * 10000), -9999).astype("int16"))
        band.SetNoDataValue(-9999)
        band.SetDescription(COMMON_BANDS[i])
    ds = None
