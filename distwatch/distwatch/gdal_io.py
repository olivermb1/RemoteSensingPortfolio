"""The same functions as rio_io.py, with GDAL/OGR/OSR only.

QGIS ships GDAL's Python bindings and numpy but not rasterio, so the QGIS
Processing script uses this module. Untested: no GDAL bindings were available
where this was written.
"""

import json

import numpy as np
from osgeo import gdal, ogr, osr

gdal.UseExceptions()
ogr.UseExceptions()

NAME = "gdal"
_GDT = {"uint8": gdal.GDT_Byte, "uint16": gdal.GDT_UInt16, "int16": gdal.GDT_Int16,
        "int32": gdal.GDT_Int32, "float32": gdal.GDT_Float32}


def _srs(wkt=None, epsg=None):
    s = osr.SpatialReference()
    if epsg:
        s.ImportFromEPSG(epsg)
    else:
        s.ImportFromWkt(wkt)
    s.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return s


class Grid:
    def __init__(self, wkt, gt, width, height):
        self.wkt, self.gt, self.width, self.height = wkt, tuple(gt), width, height

    @property
    def bounds(self):
        g = self.gt
        return (g[0], g[3] + g[5] * self.height, g[0] + g[1] * self.width, g[3])


def read(path):
    ds = gdal.Open(path)
    return ds.GetRasterBand(1).ReadAsArray(), Grid(ds.GetProjection(), ds.GetGeoTransform(),
                                                    ds.RasterXSize, ds.RasterYSize)


def read_on_grid(path, grid, fill=0):
    out = gdal.Warp("", path, format="MEM", outputBounds=grid.bounds, width=grid.width, height=grid.height,
                    dstSRS=grid.wkt, resampleAlg="near", outputType=gdal.GDT_Byte, srcBands=[1], dstNodata=fill)
    return out.GetRasterBand(1).ReadAsArray().astype("uint8")


def _mem(grid, gdt=gdal.GDT_Byte, count=1, width=None, height=None, gt=None):
    ds = gdal.GetDriverByName("MEM").Create("", width or grid.width, height or grid.height, count, gdt)
    ds.SetGeoTransform(gt or grid.gt)
    ds.SetProjection(grid.wkt)
    return ds


def write(path, array, grid, nodata=None, descriptions=None):
    arr = array if array.ndim == 3 else array[None]
    ds = gdal.GetDriverByName("GTiff").Create(path, grid.width, grid.height, arr.shape[0], _GDT[str(arr.dtype)],
                                              options=["COMPRESS=DEFLATE", "TILED=YES"])
    ds.SetGeoTransform(grid.gt)
    ds.SetProjection(grid.wkt)
    for i in range(arr.shape[0]):
        b = ds.GetRasterBand(i + 1)
        b.WriteArray(arr[i])
        if nodata is not None:
            b.SetNoDataValue(nodata)
        if descriptions:
            b.SetDescription(descriptions[i])
    ds = None


def lonlat(grid, rows, cols):
    g = grid.gt
    x = g[0] + (np.asarray(cols, "float64") + 0.5) * g[1]
    y = g[3] + (np.asarray(rows, "float64") + 0.5) * g[5]
    tr = osr.CoordinateTransformation(_srs(grid.wkt), _srs(epsg=4326))
    pts = np.array(tr.TransformPoints(np.column_stack([x.ravel(), y.ravel()]).tolist())) if x.size else np.zeros((0, 3))
    return pts[:, 0].reshape(x.shape), pts[:, 1].reshape(x.shape)


def tile_center(grid):
    lon, lat = lonlat(grid, [grid.height / 2 - 0.5], [grid.width / 2 - 0.5])
    return float(lon[0]), float(lat[0])


def area_ha(geom):
    g = ogr.CreateGeometryFromJson(json.dumps(geom))
    g.AssignSpatialReference(_srs(epsg=4326))
    if hasattr(g, "GeodesicArea"):  # GDAL 3.9+
        return abs(g.GeodesicArea()) / 1e4
    g.TransformTo(_srs(epsg=6933))  # equal-area fallback
    return g.GetArea() / 1e4


def area_windows(feats, grid):
    tr = osr.CoordinateTransformation(_srs(epsg=4326), _srs(grid.wkt))
    gt = grid.gt
    for i, f in enumerate(feats):
        g = ogr.CreateGeometryFromJson(json.dumps(f["geometry"]))
        g.Transform(tr)
        x0, x1, y0, y1 = g.GetEnvelope()
        c0 = max(int(np.floor((x0 - gt[0]) / gt[1])), 0)
        c1 = min(int(np.ceil((x1 - gt[0]) / gt[1])), grid.width)
        r0 = max(int(np.floor((y1 - gt[3]) / gt[5])), 0)
        r1 = min(int(np.ceil((y0 - gt[3]) / gt[5])), grid.height)
        if c1 <= c0 or r1 <= r0:
            continue
        wgt = (gt[0] + c0 * gt[1], gt[1], 0.0, gt[3] + r0 * gt[5], 0.0, gt[5])
        ds = _mem(grid, width=c1 - c0, height=r1 - r0, gt=wgt)
        vds = ogr.GetDriverByName("Memory").CreateDataSource("")
        lyr = vds.CreateLayer("a", _srs(grid.wkt), ogr.wkbUnknown)
        feat = ogr.Feature(lyr.GetLayerDefn())
        feat.SetGeometry(g)
        lyr.CreateFeature(feat)
        gdal.RasterizeLayer(ds, [1], lyr, burn_values=[1])
        m = ds.GetRasterBand(1).ReadAsArray().astype(bool)
        if m.any():
            yield i, (r0, r1, c0, c1), m


def polygonize(labels, grid):
    ds = _mem(grid, gdal.GDT_Int32)
    ds.GetRasterBand(1).WriteArray(labels.astype("int32"))
    mds = _mem(grid)
    mds.GetRasterBand(1).WriteArray((labels > 0).astype("uint8"))
    vds = ogr.GetDriverByName("Memory").CreateDataSource("")
    lyr = vds.CreateLayer("p", _srs(grid.wkt), ogr.wkbPolygon)
    lyr.CreateField(ogr.FieldDefn("v", ogr.OFTInteger))
    gdal.Polygonize(ds.GetRasterBand(1), mds.GetRasterBand(1), lyr, 0, ["8CONNECTED=8"])
    tr = osr.CoordinateTransformation(_srs(grid.wkt), _srs(epsg=4326))
    out = {}
    for f in lyr:
        v = f.GetField("v")
        g = f.GetGeometryRef().Clone()
        g.Transform(tr)
        out[v] = g if v not in out else out[v].Union(g)
    return {k: json.loads(v.ExportToJson()) for k, v in out.items()}
