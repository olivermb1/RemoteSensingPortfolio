"""GDAL-only I/O backend (for QGIS, which ships GDAL but not rasterio/pyproj)."""

import numpy as np


def _srs(epsg):
    from osgeo import osr
    s = osr.SpatialReference()
    s.ImportFromEPSG(int(epsg))
    s.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return s


def lonlat_to_crs(lon, lat, epsg):
    from osgeo import osr
    t = osr.CoordinateTransformation(_srs(4326), _srs(epsg))
    lon = np.atleast_1d(lon).astype(float)
    lat = np.atleast_1d(lat).astype(float)
    pts = t.TransformPoints(list(zip(lon, lat)))
    x = np.array([p[0] for p in pts])
    y = np.array([p[1] for p in pts])
    if x.size == 1:
        return float(x[0]), float(y[0])
    return x, y


def lonlat_bounds_to_crs(bbox, epsg):
    w, s, e, n = bbox
    t = np.linspace(0, 1, 21)
    lons = np.concatenate([w + (e - w) * t, np.full(21, e), e - (e - w) * t, np.full(21, w)])
    lats = np.concatenate([np.full(21, s), s + (n - s) * t, np.full(21, n), n - (n - s) * t])
    x, y = lonlat_to_crs(lons, lats, epsg)
    return float(np.min(x)), float(np.min(y)), float(np.max(x)), float(np.max(y))


def dem_on_grid(dem_path, gt, shape, epsg):
    from osgeo import gdal
    gdal.UseExceptions()
    ny, nx = shape
    bounds = (gt[0], gt[3] + ny * gt[5], gt[0] + nx * gt[1], gt[3])
    ds = gdal.Warp("", dem_path, format="MEM", outputBounds=bounds, width=nx, height=ny,
                   dstSRS=f"EPSG:{epsg}", resampleAlg="bilinear", dstNodata=np.nan,
                   outputType=gdal.GDT_Float32)
    a = ds.GetRasterBand(1).ReadAsArray().astype(np.float32)
    if gt[5] > 0:  # grids stored south-up
        a = a[::-1]
    return a


_GDT = {"float32": 6, "float64": 7, "uint8": 1, "uint16": 2, "int16": 3, "uint32": 4, "int32": 5}


def write(path, arr, gt, epsg, nodata, description, tags):
    """Tiled, deflate-compressed GeoTIFF without internal overviews (see rio_io)."""
    from osgeo import gdal
    gdal.UseExceptions()
    arr = np.asarray(arr)
    opts = ["COMPRESS=DEFLATE", f"PREDICTOR={3 if arr.dtype.kind == 'f' else 2}"]
    if min(arr.shape) >= 256:
        opts += ["TILED=YES", "BLOCKXSIZE=256", "BLOCKYSIZE=256"]
    ds = gdal.GetDriverByName("GTiff").Create(path, arr.shape[1], arr.shape[0], 1,
                                              _GDT[arr.dtype.name], opts)
    ds.SetGeoTransform(gt)
    ds.SetProjection(_srs(epsg).ExportToWkt())
    ds.SetMetadata({k: str(v) for k, v in tags.items()})
    b = ds.GetRasterBand(1)
    if nodata is not None:
        b.SetNoDataValue(float(nodata))
    b.SetDescription(description[:200])
    b.SetUnitType(tags.get("UNITS", ""))
    b.WriteArray(arr)
    ds = None
