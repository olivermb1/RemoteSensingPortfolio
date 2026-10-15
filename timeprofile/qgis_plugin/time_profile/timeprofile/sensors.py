"""Band names, scale factors and quality masks for each supported product.

Every product's bands are mapped to common names (blue, green, red, nir,
swir1, swir2, rededge1..3, nirn), so one index formula works for all of them.
"nir" follows each product's own convention: Sentinel-2 B08 (10 m, the usual
NDVI band), HLS S30 B8A (HLS's harmonised NIR), Landsat OLI B5.
"""

# common name -> band file suffix / code
HLS_BANDS = {
    "S30": {"coastal": "B01", "blue": "B02", "green": "B03", "red": "B04", "rededge1": "B05",
            "rededge2": "B06", "rededge3": "B07", "nirb": "B08", "nir": "B8A", "swir1": "B11", "swir2": "B12"},
    "L30": {"coastal": "B01", "blue": "B02", "green": "B03", "red": "B04", "nir": "B05",
            "swir1": "B06", "swir2": "B07"},
}
S2_BANDS = {"coastal": "B01", "blue": "B02", "green": "B03", "red": "B04", "rededge1": "B05",
            "rededge2": "B06", "rededge3": "B07", "nir": "B08", "nirn": "B8A", "swir1": "B11", "swir2": "B12"}
LANDSAT_BANDS = {
    "OLI": {"coastal": "SR_B1", "blue": "SR_B2", "green": "SR_B3", "red": "SR_B4", "nir": "SR_B5",
            "swir1": "SR_B6", "swir2": "SR_B7"},          # Landsat 8 and 9
    "TM": {"blue": "SR_B1", "green": "SR_B2", "red": "SR_B3", "nir": "SR_B4",
           "swir1": "SR_B5", "swir2": "SR_B7"},          # Landsat 4, 5 and 7
}

# reflectance = DN * scale + offset
SCALE = {
    "HLS": (1e-4, 0.0),
    "S2": (1e-4, 0.0),        # before baseline 04.00, or harmonised (AWS Element 84 removes the offset)
    "S2_PB04": (1e-4, -0.1),  # baseline 04.00+ (from 25 Jan 2022): DN carries a +1000 offset
    "LANDSAT": (2.75e-5, -0.2),
}
NODATA = {"HLS": -9999, "S2": 0, "LANDSAT": 0}

# Quality masks. kind "bits": drop a pixel if any listed (start, length, values) field matches.
# kind "classes": keep a pixel only if its class is in "keep".
MASKS = {
    "fmask": {  # HLS v2.0 Fmask
        "kind": "bits", "fill": [255],
        "drop": {"cloud": (1, 1, [1]), "adjacent": (2, 1, [1]), "shadow": (3, 1, [1]),
                 "snow": (4, 1, [1]), "aerosol_high": (6, 2, [3])},
        "optional": {"water": (5, 1, [1]), "aerosol_moderate": (6, 2, [2, 3]), "cirrus": (0, 1, [1])},
    },
    "scl": {  # Sentinel-2 L2A Scene Classification
        "kind": "classes", "fill": [0],
        "keep": [2, 4, 5, 6, 7],  # dark area, vegetation, bare, water, unclassified
        "names": {0: "no data", 1: "saturated", 2: "dark area", 3: "cloud shadow", 4: "vegetation",
                  5: "not vegetated", 6: "water", 7: "unclassified", 8: "cloud medium", 9: "cloud high",
                  10: "thin cirrus", 11: "snow"},
    },
    "qa_pixel": {  # Landsat Collection 2 Level-2 QA_PIXEL
        "kind": "bits", "fill": [1],
        "drop": {"dilated_cloud": (1, 1, [1]), "cirrus": (2, 1, [1]), "cloud": (3, 1, [1]),
                 "shadow": (4, 1, [1]), "snow": (5, 1, [1])},
        "optional": {"water": (7, 1, [1])},
    },
}


def clear_mask(qa, kind, extra_drop=()):
    """Boolean array, True where the pixel is clear by the given mask kind."""
    import numpy as np

    m = MASKS[kind]
    qa = np.asarray(qa)
    ok = ~np.isin(qa, m["fill"])
    if m["kind"] == "classes":
        return ok & np.isin(qa, m["keep"])
    q = qa.astype(np.int64)
    rules = dict(m["drop"])
    for name in extra_drop:
        rules[name] = m["optional"][name]
    for start, n, vals in rules.values():
        ok &= ~np.isin((q >> start) & ((1 << n) - 1), vals)
    return ok


def landsat_family(sensor_code):
    """'OLI' for LC08/LC09, 'TM' for LT04/LT05/LE07."""
    return "OLI" if sensor_code in ("LC08", "LC09", "LO08", "LO09") else "TM"
