"""Raster and vector I/O with rasterio (standalone CLI). The QGIS script uses
GDAL/QGIS directly and only shares core.py."""
import json
import os

import numpy as np
import rasterio
from rasterio import features
from rasterio.enums import Resampling
from rasterio.warp import reproject, transform_geom

from . import core


class Grid:
    """The analysis grid: CRS, transform, shape (taken from the first event file)."""

    def __init__(self, crs, transform, width, height):
        self.crs, self.transform, self.width, self.height = crs, transform, width, height

    @classmethod
    def of(cls, path):
        with rasterio.open(path) as s:
            return cls(s.crs, s.transform, s.width, s.height)

    @property
    def shape(self):
        return (self.height, self.width)

    def profile(self, dtype, nodata=None, count=1):
        return dict(driver="GTiff", crs=self.crs, transform=self.transform, width=self.width,
                    height=self.height, count=count, dtype=dtype, nodata=nodata, compress="deflate",
                    tiled=True, blockxsize=256, blockysize=256)


def read_on_grid(path, grid, band=1, resampling=Resampling.nearest, dtype=None, src_nodata=None, dst_nodata=None):
    """Read one band of `path` resampled onto `grid`."""
    with rasterio.open(path) as s:
        if (s.crs == grid.crs and s.transform == grid.transform and s.shape == grid.shape):
            a = s.read(band)
            return a.astype(dtype) if dtype else a
        dt = dtype or s.dtypes[band - 1]
        nd = s.nodata if src_nodata is None else src_nodata
        if dst_nodata is None:
            dst_nodata = np.nan if np.dtype(dt).kind == "f" else (nd if nd is not None else 0)
        out = np.full(grid.shape, dst_nodata, dtype=dt)
        reproject(rasterio.band(s, band), out, src_nodata=nd, dst_transform=grid.transform,
                  dst_crs=grid.crs, dst_nodata=dst_nodata, resampling=resampling)
        return out


def write(path, arr, grid, nodata=None, descriptions=None):
    arr = np.asarray(arr)
    if arr.ndim == 2:
        arr = arr[None]
    with rasterio.open(path, "w", **grid.profile(arr.dtype.name, nodata, arr.shape[0])) as d:
        d.write(arr)
        if descriptions:
            d.descriptions = tuple(descriptions)


# ------------------------------------------------------------ water sources

def dswx_classes(path, grid):
    return core.decode_dswx(read_on_grid(path, grid, dtype="uint8", dst_nodata=255))


def mask_classes(path, grid, water_values=(1,), dry_values=(0,)):
    with rasterio.open(path) as s:
        nd = s.nodata
    a = read_on_grid(path, grid, dst_nodata=nd if nd is not None else 255)
    return core.decode_mask(a, water_values, dry_values, nd if nd is not None else 255)


def sar_db(path, grid):
    """VV gamma0 (linear power, or dB if the values are already negative) on the grid, in dB."""
    a = read_on_grid(path, grid, resampling=Resampling.average, dtype="float32")
    finite = a[np.isfinite(a)]
    if finite.size and np.nanmedian(finite) < 0:  # already dB
        return a
    return core.to_db(a)


def optical_classes(path, grid, cloud=None, cloud_kind="scl", scale=1.0, bands=(1, 2, 3, 4, 5, 6)):
    """6-band reflectance stack (blue, green, red, nir, swir1, swir2) -> classes."""
    refl = [read_on_grid(path, grid, band=b, resampling=Resampling.bilinear, dtype="float32") for b in bands]
    invalid = None
    if cloud:
        c = read_on_grid(cloud, grid, dtype=None, dst_nodata=0 if cloud_kind == "scl" else 255)
        invalid = np.isin(c, core.SCL_INVALID) if cloud_kind == "scl" else core.fmask_invalid(c)
    return core.optical_water(*refl, invalid=invalid, scale=scale)


# ------------------------------------------------------------ cropland

CROPLAND_PRESETS = {
    "worldcover": dict(values=(40,), note="ESA WorldCover class 40 (cropland)"),
    "deafrica": dict(values=(1,), note="Digital Earth Africa cropland mask (1 = crop)"),
    "worldcereal": dict(values=(100,), note="ESA WorldCereal temporary crops (100 = crop)"),
    "binary": dict(values=None, note="any value > 0 is cropland"),
}


def crop_fraction(path, grid, preset="worldcover", values=None):
    """Fraction of each analysis pixel covered by cropland (0-1, NaN where the
    cropland map has no data), by averaging a 0/1 mask from the map's native
    resolution onto the grid."""
    vals = values or CROPLAND_PRESETS[preset]["values"]
    with rasterio.open(path) as s:
        a = s.read(1)
        nd = s.nodata
        m = (np.isin(a, vals) if vals else (a > 0)).astype(np.float32)
        if nd is not None:
            m[a == nd] = np.nan
        if preset == "worldcover":
            m[a == 0] = np.nan
        out = np.full(grid.shape, np.nan, np.float32)
        reproject(m, out, src_transform=s.transform, src_crs=s.crs, src_nodata=np.nan,
                  dst_transform=grid.transform, dst_crs=grid.crs, dst_nodata=np.nan,
                  resampling=Resampling.average)
    return out


def permanent_mask(path, grid, threshold=0.8):
    """Permanent water from a frequency/occurrence layer (WOfS 0-1, JRC GSW 0-100)."""
    a = read_on_grid(path, grid, resampling=Resampling.bilinear, dtype="float32")
    if np.nanmax(a) > 1.0:
        a = a / 100.0
    return np.nan_to_num(a, nan=0.0) >= threshold


# ------------------------------------------------------------------ zones

def read_zones(path, name_field=None):
    """Read polygons -> list of (name, properties, geometry dict in the file CRS), crs string.
    GeoJSON is read natively; other formats need fiona."""
    if path.lower().endswith((".geojson", ".json")):
        with open(path) as fh:
            fc = json.load(fh)
        crs = "EPSG:4326"
        name = (fc.get("crs") or {}).get("properties", {}).get("name")
        if name and "CRS84" not in name:
            crs = name
        feats = [(f.get("properties") or {}, f["geometry"]) for f in fc["features"] if f.get("geometry")]
    else:
        import fiona
        with fiona.open(path) as src:
            crs = src.crs_wkt
            feats = [(dict(f["properties"]), dict(f["geometry"])) for f in src]
    out = []
    for i, (props, geom) in enumerate(feats):
        nm = props.get(name_field) if name_field else None
        if nm is None:
            for k in ("name", "NAME", "shapeName", "ADM2_EN", "ADM1_EN", "LZNAMEEN", "LZNAME", "FNID", "admin2Name"):
                if props.get(k):
                    nm = props[k]
                    break
        out.append((str(nm if nm is not None else i), props, geom))
    return out, crs


def zone_masks(zones, zones_crs, grid):
    """Yield (name, props, geom_in_grid_crs, bool mask) per zone (pixel centres inside)."""
    for name, props, geom in zones:
        g = transform_geom(zones_crs, grid.crs, geom) if str(zones_crs) != str(grid.crs) else geom
        mask = features.geometry_mask([g], out_shape=grid.shape, transform=grid.transform, invert=True)
        yield name, props, geom, mask


def is_geographic(grid):
    return bool(grid.crs and grid.crs.is_geographic)
