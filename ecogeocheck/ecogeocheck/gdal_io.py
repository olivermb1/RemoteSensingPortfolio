"""The same functions as rio_io.py, with GDAL only (QGIS ships GDAL but not rasterio)."""

import numpy as np
from osgeo import gdal, osr

gdal.UseExceptions()
NAME = "gdal"


class Grid:
    def __init__(self, wkt, gt, width, height):
        self.wkt, self.gt, self.width, self.height = wkt, tuple(gt), width, height

    @property
    def bounds(self):
        g = self.gt
        return (g[0], g[3] + g[5] * self.height, g[0] + g[1] * self.width, g[3])


def _tags(ds):
    tags = {}
    for dom in [""] + [d for d in (ds.GetMetadataDomainList() or []) if d]:
        md = ds.GetMetadata(dom)
        if isinstance(md, dict):
            tags.update({(f"{dom}_{k}" if dom else k): v for k, v in md.items()})
    md = ds.GetRasterBand(1).GetMetadata() if ds.RasterCount else {}
    tags.update({f"band1_{k}": v for k, v in (md or {}).items()})
    return tags


def read(path):
    ds = gdal.Open(path)
    b = ds.GetRasterBand(1)
    a = b.ReadAsArray().astype("float64")
    nd = b.GetNoDataValue()
    if nd is not None:
        a[a == nd] = np.nan
    return a, Grid(ds.GetProjection(), ds.GetGeoTransform(), ds.RasterXSize, ds.RasterYSize), _tags(ds)


def read_tags(path):
    return _tags(gdal.Open(path))


def read_on_grid(path, grid, resampling="average"):
    out = gdal.Warp("", path, format="MEM", outputBounds=grid.bounds, width=grid.width, height=grid.height,
                    dstSRS=grid.wkt, resampleAlg=resampling, outputType=gdal.GDT_Float64, srcBands=[1],
                    dstNodata=np.nan)
    return out.GetRasterBand(1).ReadAsArray().astype("float64")


def copy_with_geotransform(src, dst, gt):
    ds = gdal.Translate(dst, src, format="GTiff", creationOptions=["COMPRESS=DEFLATE"])
    ds.SetGeoTransform(tuple(gt))
    ds = None


def write(path, array, grid, nodata=None):
    gdt = {"uint8": gdal.GDT_Byte, "int16": gdal.GDT_Int16, "uint16": gdal.GDT_UInt16,
           "float32": gdal.GDT_Float32, "float64": gdal.GDT_Float64}[str(array.dtype)]
    ds = gdal.GetDriverByName("GTiff").Create(path, grid.width, grid.height, 1, gdt, ["COMPRESS=DEFLATE"])
    ds.SetGeoTransform(grid.gt)
    ds.SetProjection(grid.wkt)
    b = ds.GetRasterBand(1)
    b.WriteArray(array)
    if nodata is not None:
        b.SetNoDataValue(nodata)
    ds = None


def bounds_lonlat(grid):
    s, t = osr.SpatialReference(), osr.SpatialReference()
    s.ImportFromWkt(grid.wkt)
    t.ImportFromEPSG(4326)
    for r in (s, t):
        r.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    tr = osr.CoordinateTransformation(s, t)
    x0, y0, x1, y1 = grid.bounds
    pts = [tr.TransformPoint(x, y)[:2] for x in (x0, x1) for y in (y0, y1)]
    xs, ys = zip(*pts)
    return min(xs), min(ys), max(xs), max(ys)
