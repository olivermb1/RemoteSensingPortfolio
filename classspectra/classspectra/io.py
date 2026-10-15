"""Reading and aligning rasters with rasterio (standalone use)."""

import numpy as np
import rasterio
from rasterio.warp import reproject, transform_bounds, Resampling
from rasterio.windows import from_bounds


def read_image(path, bbox=None, scale=1.0, offset=0.0, nodata=None, bands=None):
    """Read a multiband image as float32 reflectance with NaN for nodata.

    bbox is (west, south, east, north) in EPSG:4326. Returns (array, profile).
    """
    with rasterio.open(path) as src:
        window = None
        if bbox is not None:
            b = transform_bounds("EPSG:4326", src.crs, *bbox)
            window = from_bounds(*b, transform=src.transform).round_offsets().round_lengths()
        idx = bands or list(range(1, src.count + 1))
        raw = src.read(idx, window=window)
        nd = src.nodata if nodata is None else nodata
        img = raw.astype("float32") * scale + offset
        if nd is not None:
            img[raw == nd] = np.nan
        profile = src.profile.copy()
        profile.update(
            height=img.shape[1], width=img.shape[2], count=img.shape[0],
            transform=src.window_transform(window) if window else src.transform,
        )
        profile["descriptions"] = [src.descriptions[i - 1] for i in idx]
    return img, profile


def read_mask(path, profile, invalid_values=None, bitmask=None):
    """Read a quality layer on the image grid and return a boolean valid mask.

    invalid_values: list of values to reject (e.g. Sentinel-2 SCL 0,1,3,8,9,10,11).
    bitmask: integer; pixels with any of these bits set are rejected (HLS Fmask).
    """
    q = align_to(path, profile, Resampling.nearest)
    valid = np.ones(q.shape, bool)
    if invalid_values:
        valid &= ~np.isin(q, invalid_values)
    if bitmask:
        valid &= (q.astype(np.int64) & int(bitmask)) == 0
    return valid


def align_to(path, profile, resampling=Resampling.nearest, band=1, dtype=None):
    """Reproject one band of `path` onto the image grid described by profile."""
    with rasterio.open(path) as src:
        dst = np.zeros((profile["height"], profile["width"]), dtype=dtype or src.dtypes[band - 1])
        reproject(
            rasterio.band(src, band), dst,
            dst_transform=profile["transform"], dst_crs=profile["crs"],
            resampling=resampling, src_nodata=src.nodata, dst_nodata=0,
        )
    return dst


def map_resolution_ratio(path, profile):
    """Approximate image pixel size / map pixel size (>1 means map is finer)."""
    with rasterio.open(path) as src:
        b = transform_bounds(profile["crs"], src.crs,
                             *rasterio.transform.array_bounds(profile["height"], profile["width"], profile["transform"]))
        win = from_bounds(*b, transform=src.transform)
        return float(win.width / profile["width"])


def read_labels(path, profile):
    """Land cover on the image grid, plus a purity layer when the map is finer.

    Same or coarser map: nearest neighbour, purity None.
    Finer map (e.g. 10 m WorldCover on 30 m HLS): majority (mode) label and
    purity = share of the coarse pixel covered by that label.
    """
    ratio = map_resolution_ratio(path, profile)
    if ratio < 1.5:
        return align_to(path, profile, Resampling.nearest), None
    labels = align_to(path, profile, Resampling.mode)
    with rasterio.open(path) as src:
        b = transform_bounds(profile["crs"], src.crs,
                             *rasterio.transform.array_bounds(profile["height"], profile["width"], profile["transform"]))
        win = from_bounds(*b, transform=src.transform).round_offsets().round_lengths()
        win = win.intersection(rasterio.windows.Window(0, 0, src.width, src.height))
        fine = src.read(1, window=win)
        fine_transform, fine_crs = src.window_transform(win), src.crs
    purity = np.zeros(labels.shape, "float32")
    for v in np.unique(labels):
        if v == 0:
            continue
        # share of each coarse pixel covered by class v
        frac = np.zeros(labels.shape, "float32")
        reproject((fine == v).astype("float32"), frac,
                  src_transform=fine_transform, src_crs=fine_crs,
                  dst_transform=profile["transform"], dst_crs=profile["crs"],
                  resampling=Resampling.average)
        purity[labels == v] = frac[labels == v]
    return labels, purity
