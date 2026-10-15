"""What a NISAR L2 GUNW file looks like: HDF5 paths, layers, units, codes.

Sources (checked 2026-10-15, see README "Where the layout comes from"):
- isce3 `nisar/products/insar/GUNW_writer.py` and `workflows/h5_prep.py`
  (the code JPL uses to write GUNW files; product spec 1.2.1 era),
- MintPy `prep_nisar.py` (an independent reader of real GUNW files),
- ASF's NISAR GUNW page and the L2 GUNW product spec (JPL D-102272).
"""

SPEED_OF_LIGHT = 299_792_458.0

ROOT = "/science/LSAR"
IDENT = f"{ROOT}/identification"
GUNW = f"{ROOT}/GUNW"
RADAR_GRID = f"{GUNW}/metadata/radarGrid"


def grids_root(freq="A"):
    return f"{GUNW}/grids/frequency{freq}"


def unw_group(freq="A"):
    return f"{grids_root(freq)}/unwrappedInterferogram"


def wrapped_group(freq="A"):
    return f"{grids_root(freq)}/wrappedInterferogram"


def offsets_group(freq="A"):
    return f"{grids_root(freq)}/pixelOffsets"


# Layers read straight from the file. key -> (group function, in-pol-group?,
# dataset name, units, description). Pol groups are e.g. .../HH/.
# The "mask" layer sits next to the pol groups, not inside them.
LAYERS = {
    "unwrapped_phase": (unw_group, True, "unwrappedPhase", "radians",
                        "Unwrapped interferometric phase (no corrections applied)"),
    "coherence": (unw_group, True, "coherenceMagnitude", "1",
                  "Coherence magnitude (80 m grid)"),
    "connected_components": (unw_group, True, "connectedComponents", "1",
                             "Connected component label from unwrapping (0 = not unwrapped reliably)"),
    "ionosphere": (unw_group, True, "ionospherePhaseScreen", "radians",
                   "Ionosphere phase screen (not applied to unwrappedPhase in the product)"),
    "ionosphere_uncertainty": (unw_group, True, "ionospherePhaseScreenUncertainty", "radians",
                               "Uncertainty of the ionosphere phase screen"),
    "valid_data": (unw_group, True, "validDataMask", "1",
                   "Valid-data bits: bit 1 reference valid, bit 0 secondary valid"),
    "mask": (unw_group, False, "mask", "1",
             "Product mask: water flag and subswath numbers in bits 0-7, anomaly flags above"),
    "wrapped_phase": (wrapped_group, True, "wrappedInterferogram", "radians",
                      "Phase of the complex wrapped interferogram (20 m grid)"),
    "wrapped_coherence": (wrapped_group, True, "coherenceMagnitude", "1",
                          "Coherence magnitude (20 m grid)"),
    "along_track_offset": (offsets_group, True, "alongTrackOffset", "meters",
                           "Along-track pixel offset"),
    "slant_range_offset": (offsets_group, True, "slantRangeOffset", "meters",
                           "Slant-range pixel offset"),
    "offset_correlation": (offsets_group, True, "correlationSurfacePeak", "1",
                           "Normalized cross-correlation surface peak of the offsets"),
}

# Layers the tool computes on the 80 m unwrapped grid.
DERIVED = {
    "los_displacement": ("meters",
                         "Line-of-sight displacement, positive towards the satellite, after the "
                         "chosen corrections and re-referencing"),
    "vertical_displacement": ("meters",
                              "LOS displacement / cos(incidence): vertical motion IF there is no "
                              "horizontal motion"),
    "incidence_angle": ("degrees", "Incidence angle at the pixel's height (from the radar grid cube)"),
    "los_east": ("1", "East component of the unit vector from ground to satellite"),
    "los_north": ("1", "North component of the unit vector from ground to satellite"),
    "los_up": ("1", "Up component of the unit vector from ground to satellite"),
    "troposphere": ("radians", "Wet + hydrostatic troposphere phase at the pixel's height"),
    "solid_earth_tide": ("radians", "Solid Earth tide phase (slant range) at the pixel's height"),
    "keep_mask": ("1", "1 where the pixel is used for los_displacement, 0 elsewhere"),
}

DEFAULT_LAYERS = ["los_displacement", "unwrapped_phase", "coherence",
                  "connected_components", "incidence_angle"]

# Radar grid cube layers (height, y, x) in metadata/radarGrid.
CUBE = {
    "incidence_angle": "incidenceAngle",
    "los_x": "losUnitVectorX",
    "los_y": "losUnitVectorY",
    "wet_tropo": "wetTroposphericPhaseScreen",
    "hydro_tropo": "hydrostaticTroposphericPhaseScreen",
    "set": "slantRangeSolidEarthTidesPhase",
}

CORRECTIONS = ("ionosphere", "troposphere", "solid_earth_tide")

IDENT_FIELDS = [
    "granuleId", "missionId", "productType", "productVersion",
    "productSpecificationVersion", "compositeReleaseId", "trackNumber",
    "frameNumber", "orbitPassDirection", "lookDirection",
    "referenceZeroDopplerStartTime", "referenceZeroDopplerEndTime",
    "secondaryZeroDopplerStartTime", "secondaryZeroDopplerEndTime",
    "listOfFrequencies", "isFullFrame", "processingDateTime", "productDoi",
]


def wavelength(center_frequency_hz):
    return SPEED_OF_LIGHT / float(center_frequency_hz)


def decode_mask(mask_bits, fill=None):
    """Split the GUNW `mask` layer into (valid, water) boolean arrays.

    Bits 0-7 hold a 3-digit decimal number: hundreds = water flag (1 = water),
    tens = reference subswath, ones = secondary subswath; 0 in either
    subswath digit means an invalid sample. This is the reading MintPy uses.
    """
    import numpy as np
    m = np.asarray(mask_bits)
    present = np.ones(m.shape, bool)
    if fill is not None:
        present &= m != fill
    low = np.where(present, m.astype(np.int64) & 0xFF, 0)
    water = present & ((low // 100) == 1)
    ref_sw = (low // 10) % 10
    sec_sw = low % 10
    valid = present & (ref_sw > 0) & (sec_sw > 0)
    return valid, water
