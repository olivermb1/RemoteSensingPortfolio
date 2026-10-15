"""Raster reading and writing with rasterio, or GDAL's osgeo bindings when rasterio is missing.

QGIS ships osgeo and numpy but not rasterio, so the QGIS plugin runs on the
GDAL backend. Set QAMASK_BACKEND=gdal to force it elsewhere.
"""

import os
from xml.sax.saxutils import escape

import numpy as np

from .crsfix import hls_crs_fix, shifted_geotransform

BACKEND = None
if os.environ.get("QAMASK_BACKEND") != "gdal":
    try:
        import rasterio
        from rasterio.transform import Affine
        BACKEND = "rasterio"
    except ImportError:
        pass
if BACKEND is None:
    from osgeo import gdal, osr
    gdal.UseExceptions()
    BACKEND = "gdal"

_GDAL_NAMES = {"uint8": "Byte", "int8": "Int8", "uint16": "UInt16", "int16": "Int16", "uint32": "UInt32",
               "int32": "Int32", "float32": "Float32", "float64": "Float64"}

MASK_COLORS = {0: (215, 48, 39, 255), 1: (26, 152, 80, 255), 255: (0, 0, 0, 0)}


class Info:
    """What the rest of the code needs to know about a raster."""

    def __init__(self, path, epsg, wkt, gt, width, height, count, dtype, nodata, tags):
        self.path, self.epsg, self.wkt, self.gt = path, epsg, wkt, tuple(gt)
        self.width, self.height, self.count, self.dtype = width, height, count, dtype
        self.nodata, self.tags = nodata, tags

    @property
    def top(self):
        return self.gt[3]

    @property
    def bottom(self):
        return self.gt[3] + self.gt[5] * self.height

    def crs_check(self):
        return hls_crs_fix(self.epsg, self.top, self.bottom, os.path.basename(self.path))

    def fixed(self):
        """A copy of this Info with the southern-hemisphere fix applied, plus the check result."""
        chk = self.crs_check()
        if not chk["needed"]:
            return self, chk
        new = Info(self.path, chk["new_epsg"], None, shifted_geotransform(self.gt, chk["y_shift"]),
                   self.width, self.height, self.count, self.dtype, self.nodata, self.tags)
        return new, chk


def info(path):
    if BACKEND == "rasterio":
        with rasterio.open(path) as s:
            epsg = s.crs.to_epsg() if s.crs else None
            return Info(path, epsg, s.crs.to_wkt() if s.crs else None, s.transform.to_gdal(), s.width, s.height,
                        s.count, s.dtypes[0], s.nodata, s.tags())
    ds = gdal.Open(path)
    srs = ds.GetSpatialRef()
    epsg = None
    if srs is not None:
        srs.AutoIdentifyEPSG()
        code = srs.GetAuthorityCode(None)
        epsg = int(code) if code and code.isdigit() else None
    b = ds.GetRasterBand(1)
    dtype = gdal.GetDataTypeName(b.DataType)
    inv = {v: k for k, v in _GDAL_NAMES.items()}
    return Info(path, epsg, ds.GetProjection() or None, ds.GetGeoTransform(), ds.RasterXSize, ds.RasterYSize,
                ds.RasterCount, inv.get(dtype, dtype.lower()), b.GetNoDataValue(), ds.GetMetadata() or {})


def read(path, band=1):
    if BACKEND == "rasterio":
        with rasterio.open(path) as s:
            return s.read(band)
    ds = gdal.Open(path)
    return ds.GetRasterBand(band).ReadAsArray()


def read_all(path):
    if BACKEND == "rasterio":
        with rasterio.open(path) as s:
            return s.read()
    ds = gdal.Open(path)
    return np.stack([ds.GetRasterBand(i + 1).ReadAsArray() for i in range(ds.RasterCount)])


def _srs_wkt(ref):
    if ref.epsg:
        if BACKEND == "rasterio":
            return rasterio.crs.CRS.from_epsg(ref.epsg).to_wkt()
        s = osr.SpatialReference()
        s.ImportFromEPSG(ref.epsg)
        return s.ExportToWkt()
    return ref.wkt


def write(path, data, ref, nodata=None, colormap=None, tags=None, band_names=None):
    """Write a (bands, rows, cols) or (rows, cols) array as a tiled, compressed GeoTIFF on ref's grid."""
    data = np.asarray(data)
    if data.ndim == 2:
        data = data[None]
    dtype = str(data.dtype)
    if BACKEND == "rasterio":
        prof = dict(driver="GTiff", width=ref.width, height=ref.height, count=data.shape[0], dtype=dtype,
                    crs=rasterio.crs.CRS.from_wkt(_srs_wkt(ref)) if (ref.epsg or ref.wkt) else None,
                    transform=Affine.from_gdal(*ref.gt), nodata=nodata, compress="deflate", tiled=True,
                    blockxsize=256, blockysize=256)
        with rasterio.open(path, "w", **prof) as o:
            o.write(data)
            if colormap:
                o.write_colormap(1, colormap)
            if tags:
                o.update_tags(**{k: str(v) for k, v in tags.items()})
            for i, n in enumerate(band_names or []):
                o.set_band_description(i + 1, n)
        return path
    gtype = gdal.GetDataTypeByName(_GDAL_NAMES[dtype])
    ds = gdal.GetDriverByName("GTiff").Create(path, ref.width, ref.height, data.shape[0], gtype,
                                              ["COMPRESS=DEFLATE", "TILED=YES"])
    ds.SetGeoTransform(ref.gt)
    wkt = _srs_wkt(ref)
    if wkt:
        ds.SetProjection(wkt)
    if colormap:  # must be set before pixels are written
        ct = gdal.ColorTable()
        for k, c in colormap.items():
            ct.SetColorEntry(int(k), tuple(c))
        ds.GetRasterBand(1).SetRasterColorTable(ct)
    for i in range(data.shape[0]):
        b = ds.GetRasterBand(i + 1)
        if nodata is not None:
            b.SetNoDataValue(float(nodata))
        b.WriteArray(data[i])
        if band_names and i < len(band_names):
            b.SetDescription(band_names[i])
    if tags:
        ds.SetMetadata({k: str(v) for k, v in tags.items()})
    ds.FlushCache()
    ds = None
    return path


def write_fix_vrt(path, ref_fixed, src_path):
    """A small VRT that points at src_path with the corrected CRS and origin; no pixels are copied."""
    s = info(src_path)
    bands = []
    for i in range(1, s.count + 1):
        nd = f"<NoDataValue>{s.nodata}</NoDataValue>" if s.nodata is not None else ""
        bands.append(
            f'  <VRTRasterBand dataType="{_GDAL_NAMES.get(s.dtype, "Byte")}" band="{i}">{nd}\n'
            f'    <SimpleSource><SourceFilename relativeToVRT="0">{escape(os.path.abspath(src_path))}</SourceFilename>'
            f'<SourceBand>{i}</SourceBand></SimpleSource>\n  </VRTRasterBand>')
    gt = ", ".join(repr(float(v)) for v in ref_fixed.gt)
    xml = (f'<VRTDataset rasterXSize="{s.width}" rasterYSize="{s.height}">\n'
           f'  <SRS>EPSG:{ref_fixed.epsg}</SRS>\n  <GeoTransform>{gt}</GeoTransform>\n' + "\n".join(bands) + "\n</VRTDataset>\n")
    with open(path, "w") as fh:
        fh.write(xml)
    return path
