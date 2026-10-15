"""Band presets: names, centre wavelengths (nm) and reflectance scaling.

Reflectance = DN * scale + offset.
"""

PRESETS = {
    # Sentinel-2 L2A with the -1000 DN offset already removed ("harmonized"),
    # e.g. the AWS sentinel-cogs COGs (checked on a Feb 2024 scene: forest blue
    # ~440 DN, which would be negative if the offset were still in).
    "s2_l2a": {
        "bands": ["B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B11", "B12"],
        "wavelengths": [490, 560, 665, 705, 740, 783, 842, 865, 1610, 2190],
        "scale": 0.0001, "offset": 0.0, "nodata": 0,
    },
    # Raw ESA L2A DN from processing baseline 04.00 on (25 Jan 2022 onward),
    # which still carry BOA_ADD_OFFSET = -1000.
    "s2_l2a_offset": {
        "bands": ["B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B11", "B12"],
        "wavelengths": [490, 560, 665, 705, 740, 783, 842, 865, 1610, 2190],
        "scale": 0.0001, "offset": -0.1, "nodata": 0,
    },
    # NASA HLS v2.0 S30 (Sentinel-2 part), reflective bands in this order
    "hls_s30": {
        "bands": ["B01", "B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B11", "B12"],
        "wavelengths": [443, 490, 560, 665, 705, 740, 783, 842, 865, 1610, 2190],
        "scale": 0.0001, "offset": 0.0, "nodata": -9999,
    },
    # NASA HLS v2.0 L30 (Landsat part)
    "hls_l30": {
        "bands": ["B01", "B02", "B03", "B04", "B05", "B06", "B07"],
        "wavelengths": [443, 482, 561, 655, 865, 1609, 2201],
        "scale": 0.0001, "offset": 0.0, "nodata": -9999,
    },
}

# Index of red and NIR band in each preset, for NDVI
RED_NIR = {
    "s2_l2a": ("B04", "B08"),
    "s2_l2a_offset": ("B04", "B08"),
    "hls_s30": ("B04", "B8A"),
    "hls_l30": ("B04", "B05"),
}
