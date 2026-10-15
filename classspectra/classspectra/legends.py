"""Class names and colours for common free land cover maps."""

# ESA WorldCover 10 m (v100 2020, v200 2021)
WORLDCOVER = {
    10: ("Tree cover", "#006400"),
    20: ("Shrubland", "#ffbb22"),
    30: ("Grassland", "#ffff4c"),
    40: ("Cropland", "#f096ff"),
    50: ("Built-up", "#fa0000"),
    60: ("Bare / sparse vegetation", "#b4b4b4"),
    70: ("Snow and ice", "#f0f0f0"),
    80: ("Permanent water bodies", "#0064c8"),
    90: ("Herbaceous wetland", "#0096a0"),
    95: ("Mangroves", "#00cf75"),
    100: ("Moss and lichen", "#fae6a0"),
}

# Impact Observatory / Esri 10 m annual LULC (v003 class codes)
IO_LULC = {
    1: ("Water", "#419bdf"),
    2: ("Trees", "#397d49"),
    4: ("Flooded vegetation", "#7a87c6"),
    5: ("Crops", "#e49635"),
    7: ("Built area", "#c4281b"),
    8: ("Bare ground", "#a59b8f"),
    9: ("Snow/ice", "#a8ebff"),
    10: ("Clouds", "#616161"),
    11: ("Rangeland", "#e3e2c3"),
}

# Google Dynamic World "label" band
DYNAMIC_WORLD = {
    0: ("Water", "#419bdf"),
    1: ("Trees", "#397d49"),
    2: ("Grass", "#88b053"),
    3: ("Flooded vegetation", "#7a87c6"),
    4: ("Crops", "#e49635"),
    5: ("Shrub and scrub", "#dfc35a"),
    6: ("Built", "#c4281b"),
    7: ("Bare", "#a59b8f"),
    8: ("Snow and ice", "#b39fe1"),
}

LEGENDS = {
    "worldcover": WORLDCOVER,
    "io": IO_LULC,
    "dynamicworld": DYNAMIC_WORLD,
}

# Rough cross-walk to a shared set of broad classes, so two different maps
# can be compared class by class. Keys are broad class names.
BROAD = {
    "worldcover": {10: "Trees", 20: "Shrub", 30: "Grass", 40: "Crops", 50: "Built",
                   60: "Bare", 80: "Water", 90: "Wetland", 95: "Trees"},
    "io": {1: "Water", 2: "Trees", 4: "Wetland", 5: "Crops", 7: "Built", 8: "Bare",
           11: "Grass"},
    "dynamicworld": {0: "Water", 1: "Trees", 2: "Grass", 3: "Wetland", 4: "Crops",
                     5: "Shrub", 6: "Built", 7: "Bare"},
}


def class_name(legend, value):
    entry = LEGENDS.get(legend, {}).get(int(value))
    return entry[0] if entry else f"Class {int(value)}"


def class_colour(legend, value, fallback="#555555"):
    entry = LEGENDS.get(legend, {}).get(int(value))
    return entry[1] if entry else fallback


# Shared broad classes used when comparing two maps
BROAD_CLASSES = {
    1: ("Water", "#419bdf"),
    2: ("Trees", "#397d49"),
    3: ("Grass", "#c9c94d"),
    4: ("Shrub", "#dfa35a"),
    5: ("Crops", "#d65fd6"),
    6: ("Built", "#c4281b"),
    7: ("Bare", "#a59b8f"),
    8: ("Wetland", "#0096a0"),
}
LEGENDS["broad"] = BROAD_CLASSES
BROAD_CODES = {name: code for code, (name, _) in BROAD_CLASSES.items()}
