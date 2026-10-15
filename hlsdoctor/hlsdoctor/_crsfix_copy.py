"""Fallback copy of qamaskbuilder/qamask/crsfix.py (hls_crs_fix only), used
when hlsdoctor runs without its sibling folder. Keep in step with the original."""

import re

FALSE_NORTHING_SOUTH = 10_000_000.0
_MGRS = re.compile(r"T(\d{2})([C-HJ-NP-X])([A-HJ-NP-Z]{2})")


def mgrs_tile(filename):
    m = _MGRS.search(filename or "")
    if not m:
        return None
    return int(m.group(1)), m.group(2), m.group(3)


def hls_crs_fix(epsg, top, bottom, filename=None):
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
