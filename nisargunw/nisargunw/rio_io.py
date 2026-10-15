"""Command-line I/O backend: rasterio + pyproj."""

import os

import numpy as np


def lonlat_to_crs(lon, lat, epsg):
    from pyproj import Transformer
    t = Transformer.from_crs(4326, epsg, always_xy=True)
    return t.transform(lon, lat)


def lonlat_bounds_to_crs(bbox, epsg):
    """(west, south, east, north) in degrees -> (xmin, ymin, xmax, ymax) in the grid CRS,
    densifying the edges so the box fully covers the lon/lat box."""
    w, s, e, n = bbox
    t = np.linspace(0, 1, 21)
    lons = np.concatenate([w + (e - w) * t, np.full(21, e), e - (e - w) * t, np.full(21, w)])
    lats = np.concatenate([np.full(21, s), s + (n - s) * t, np.full(21, n), n - (n - s) * t])
    x, y = lonlat_to_crs(lons, lats, epsg)
    return float(np.min(x)), float(np.min(y)), float(np.max(x)), float(np.max(y))


def dem_on_grid(dem_path, gt, shape, epsg):
    import rasterio
    from rasterio.warp import reproject, Resampling
    from affine import Affine
    out = np.full(shape, np.nan, np.float32)
    with rasterio.open(dem_path) as src:
        reproject(rasterio.band(src, 1), out, src_nodata=src.nodata, dst_nodata=np.nan,
                  dst_transform=Affine.from_gdal(*gt), dst_crs=f"EPSG:{epsg}",
                  resampling=Resampling.bilinear)
    return out


def write(path, arr, gt, epsg, nodata, description, tags):
    """Write in a local temp folder, then move into place (one sequential copy,
    friendlier to network-mounted folders)."""
    import shutil
    import tempfile
    tmpdir = tempfile.mkdtemp(prefix="nisargunw_")
    try:
        tmp = os.path.join(tmpdir, os.path.basename(path))
        _write(tmp, arr, gt, epsg, nodata, description, tags)
        shutil.move(tmp, path)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _write(path, arr, gt, epsg, nodata, description, tags):
    import rasterio
    from affine import Affine
    arr = np.asarray(arr)
    # No internal overviews: in the project's shared folder, TIFFs with overviews
    # were later rewritten by something outside this tool and broke. QGIS builds
    # pyramids itself when asked.
    profile = dict(driver="GTiff", height=arr.shape[0], width=arr.shape[1], count=1,
                   dtype=arr.dtype.name, crs=f"EPSG:{epsg}", transform=Affine.from_gdal(*gt),
                   compress="deflate", predictor=3 if arr.dtype.kind == "f" else 2)
    if min(arr.shape) >= 256:
        profile.update(tiled=True, blockxsize=256, blockysize=256)
    if nodata is not None:
        profile["nodata"] = nodata
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(arr, 1)
        dst.set_band_description(1, description[:200])
        dst.update_tags(**tags)
        dst.units = (tags.get("UNITS", ""),)
