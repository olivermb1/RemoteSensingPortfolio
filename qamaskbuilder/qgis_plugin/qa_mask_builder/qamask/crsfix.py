"""Fix for the HLS southern-hemisphere CRS label.

HLS v2.0 GeoTIFFs (and OPERA DSWx-HLS, made by the same pipeline) label every
tile with a northern UTM zone, e.g. EPSG:32619, even when the tile lies south
of the equator. The coordinates are written with a false northing of 0, so Y is
negative. The pixels land in the right place, but the EPSG code is wrong for the
tile, and tools that expect EPSG:327xx (PostGIS, mosaics with Sentinel-2 or
Digital Earth Africa data) either error or reproject. LP DAAC confirmed the
cause in Jan 2026 (forum.earthdata.nasa.gov/viewtopic.php?p=24898) and gave no
fix date.

The fix needs no resampling: relabel as the southern zone (EPSG:327zz) and add
10,000,000 m to every Y coordinate. Every pixel keeps its exact place on Earth.
"""

import re

FALSE_NORTHING_SOUTH = 10_000_000.0
_MGRS = re.compile(r"T(\d{2})([C-HJ-NP-X])([A-HJ-NP-Z]{2})")


def mgrs_tile(filename):
    """(zone, latitude band, square) from an HLS/OPERA/S2 file name, or None."""
    m = _MGRS.search(filename or "")
    if not m:
        return None
    return int(m.group(1)), m.group(2), m.group(3)


def hls_crs_fix(epsg, top, bottom, filename=None):
    """Decide whether a raster needs the southern-hemisphere relabel.

    epsg: the file's EPSG code (int or None); top/bottom: Y of the raster's
    edges in that CRS. Returns a dict with 'needed' (bool), 'reason', and when
    needed 'new_epsg' and 'y_shift'.
    """
    tile = mgrs_tile(filename)
    if epsg is None:
        return {"needed": False, "reason": "no EPSG code on the file; set the CRS by hand"}
    if 32701 <= epsg <= 32760:
        return {"needed": False, "reason": f"already a southern UTM zone (EPSG:{epsg})"}
    if not 32601 <= epsg <= 32660:
        return {"needed": False, "reason": f"EPSG:{epsg} is not a WGS 84 UTM zone"}
    zone = epsg - 32600
    if tile and tile[0] != zone:
        return {"needed": False, "reason": f"file name says zone {tile[0]} but the CRS says zone {zone}; not touching it"}
    if top > 0:
        if bottom < 0:
            return {"needed": False, "reason": "raster crosses the equator; the northern zone is the right label"}
        return {"needed": False, "reason": "raster is north of the equator"}
    if tile and tile[1] > "M":
        return {"needed": False, "reason": f"Y is negative but the MGRS band {tile[1]} is northern; check the file"}
    return {"needed": True, "new_epsg": 32700 + zone, "y_shift": FALSE_NORTHING_SOUTH,
            "reason": f"EPSG:{epsg} with negative northings; relabel as EPSG:{32700 + zone} and add 10,000,000 m to Y"}


def shifted_geotransform(gt, y_shift):
    """GDAL geotransform (x0, dx, rx, y0, ry, dy) with the origin moved north by y_shift."""
    return (gt[0], gt[1], gt[2], gt[3] + y_shift, gt[4], gt[5])
