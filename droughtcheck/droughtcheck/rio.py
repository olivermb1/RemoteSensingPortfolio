"""Raster input/output with rasterio (the QGIS script uses GDAL directly instead)."""
from __future__ import annotations

import re

import numpy as np


def read_stack(path, band_filter=None):
    """Read a multiband monthly GeoTIFF. Returns (array (n, y, x) float64, profile dict,
    labels). Labels come from band descriptions ('YYYY-MM' or 'tmax YYYY-MM')."""
    import rasterio
    with rasterio.open(path) as d:
        idx = [i for i, desc in enumerate(d.descriptions, 1)
               if band_filter is None or (desc or "").startswith(band_filter)]
        a = d.read(idx).astype("float64")
        if d.nodata is not None and not np.isnan(d.nodata):
            a[a == d.nodata] = np.nan
        labels = [d.descriptions[i - 1] or f"band {i}" for i in idx]
        prof = dict(transform=d.transform, crs=d.crs, width=d.width, height=d.height, tags=d.tags())
    return a, prof, labels


def month_of(label):
    m = re.search(r"(\d{4})-(\d{2})", label or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def pixel_latitudes(prof):
    """Latitude of each pixel centre, (y, x)."""
    from rasterio.warp import transform
    h, w, tr = prof["height"], prof["width"], prof["transform"]
    cols, rows = np.meshgrid(np.arange(w) + 0.5, np.arange(h) + 0.5)
    xs, ys = tr * (cols.ravel(), rows.ravel())
    if prof["crs"] and not prof["crs"].is_geographic:
        _, ys = transform(prof["crs"], "EPSG:4326", list(xs), list(ys))
    return np.asarray(ys).reshape(h, w)


def regrid(stack, src_prof, dst_prof, method="bilinear"):
    """Resample a (n, y, x) stack onto another grid."""
    from rasterio.warp import Resampling, reproject
    out = np.full((stack.shape[0], dst_prof["height"], dst_prof["width"]), np.nan)
    for i in range(stack.shape[0]):
        reproject(stack[i], out[i], src_transform=src_prof["transform"], src_crs=src_prof["crs"],
                  dst_transform=dst_prof["transform"], dst_crs=dst_prof["crs"],
                  resampling=getattr(Resampling, method), src_nodata=np.nan, dst_nodata=np.nan)
    return out


def write_stack(path, stack, prof, labels, dtype="float32", nodata=np.nan, tags=None):
    import rasterio
    stack = np.asarray(stack)
    if stack.ndim == 2:
        stack = stack[None]
    with rasterio.open(path, "w", driver="GTiff", width=prof["width"], height=prof["height"],
                       count=stack.shape[0], dtype=dtype, crs=prof["crs"], transform=prof["transform"],
                       nodata=nodata, compress="deflate") as dst:
        dst.write(stack.astype(dtype))
        for i, lab in enumerate(labels, 1):
            dst.set_band_description(i, lab)
        if tags:
            dst.update_tags(**{k: str(v) for k, v in tags.items()})
