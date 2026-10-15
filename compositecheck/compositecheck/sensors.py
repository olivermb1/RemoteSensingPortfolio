"""Band names shared by Landsat and Sentinel-2, as in NASA HLS v2.0."""

COMMON_BANDS = ("blue", "green", "red", "nir", "swir1", "swir2")

# HLS v2.0 file band names in COMMON_BANDS order
HLS_BANDS = {
    "S30": ["B02", "B03", "B04", "B8A", "B11", "B12"],
    "L30": ["B02", "B03", "B04", "B05", "B06", "B07"],
}

# HLS v2.0 bandpass adjustment, Sentinel-2 MSI -> Landsat 8 OLI, (slope, offset)
# in COMMON_BANDS order. Source: hls.gsfc.nasa.gov/algorithms/bandpass-adjustment.
# Only needed for non-HLS Sentinel-2 input; HLS S30 is already adjusted.
BANDPASS_MSI_TO_OLI = {
    "S2A": [(0.9778, -0.004), (1.0053, -0.0009), (0.9765, 0.0009), (0.9983, -0.0001), (0.9987, -0.0011), (1.003, -0.0012)],
    "S2B": [(0.9778, -0.004), (1.0075, -0.0008), (0.9761, 0.001), (0.9966, 0.0), (1.000, -0.0003), (0.9867, 0.0004)],
}

# QA layer order in the output GeoTIFF; names follow FORCE INF where one exists
LAYER_ORDER = [
    "nclear", "max_gap", "src_scene", "src_doy", "doyd", "src_sensor", "landsat_share",
    "src_scene_share", "src_outlier", "ls_rel_diff", "aerosol_high_share",
]

LAYER_DOC = {
    "nclear": "clear observations in the period (Francini criterion 1; FORCE INF NUM)",
    "max_gap": "longest stretch with no clear observation, days, including the period edges",
    "src_scene": "1-based scene number the composite pixel came from (0 = none); proxy for median composites",
    "src_doy": "day of year of the source observation (FORCE INF DOY)",
    "doyd": "days between source observation and target date (Francini criterion 4; FORCE INF DOYD)",
    "src_sensor": "sensor of the source observation: 1 Landsat, 2 Sentinel-2 (FORCE INF SEN)",
    "landsat_share": "share of the pixel's clear observations that are Landsat",
    "src_scene_share": "share of the whole area that came from this pixel's source scene (dominance)",
    "src_outlier": "1 if the source observation is a robust outlier in the visible bands, 0 if not, 255 unknown",
    "ls_rel_diff": "largest |Landsat-only minus Sentinel-2-only median| / mean across red, NIR, SWIR1, SWIR2",
    "aerosol_high_share": "share of clear observations with high aerosol in Fmask bits 6-7 (inferred signal)",
}
