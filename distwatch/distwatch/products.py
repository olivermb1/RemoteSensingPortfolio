"""What the OPERA DIST-ALERT-HLS product looks like: collection, file names, layers, codes.

Values follow the OPERA DIST-ALERT-HLS v1 product specification as we understand
it. Check STATUS against the current spec before relying on it: a new product
version could renumber the codes, and everything else here follows from them.
"""

import datetime as dt
import re

COLLECTION = "OPERA_L3_DIST-ALERT-HLS_V1"
PROVIDER = "LPCLOUD"

# Day numbers in VEG-DIST-DATE and VEG-LAST-DATE count from this date. It is
# also the EUDR deforestation cutoff, which is handy.
EPOCH = dt.date(2020, 12, 31)
PIXEL_HA = 0.09  # 30 m x 30 m

# VEG-DIST-STATUS codes.
STATUS = {
    0: "no disturbance",
    1: "first detection, <50% loss",
    2: "provisional, <50% loss",
    3: "confirmed, <50% loss",
    4: "first detection, >=50% loss",
    5: "provisional, >=50% loss",
    6: "confirmed, >=50% loss",
    7: "finished, <50% loss",
    8: "finished, >=50% loss",
    255: "no data",
}
STATUS_NODATA = 255

# Which codes count at each alert level. "finished" means a confirmed
# disturbance that has stopped, so it still counts as loss.
LEVELS = {
    "first": {1, 2, 3, 4, 5, 6, 7, 8},
    "provisional": {2, 3, 5, 6, 7, 8},
    "confirmed": {3, 6, 7, 8},
}

# Layers DIST Watch reads. Only the first three are required.
REQUIRED = ("VEG-DIST-STATUS", "VEG-ANOM-MAX", "VEG-DIST-DATE")
OPTIONAL = ("VEG-DIST-CONF", "VEG-LAST-DATE")
LAYERS = REQUIRED + OPTIONAL
NODATA = {"VEG-DIST-STATUS": 255, "VEG-ANOM-MAX": 255, "VEG-DIST-DATE": -1,
          "VEG-DIST-CONF": -1, "VEG-LAST-DATE": -1}

# OPERA_L3_DIST-ALERT-HLS_T30NWM_20250110T103021Z_20250112T051234Z_S2A_30_v1_VEG-DIST-STATUS.tif
NAME_RE = re.compile(
    r"(?P<granule>OPERA_L3_DIST-ALERT-HLS_T(?P<tile>\d{2}[A-Z]{3})_(?P<sensing>\d{8}T\d{6})Z_"
    r"(?P<production>\d{8}T\d{6})Z_(?P<sensor>[A-Z0-9]+)_30_v(?P<version>[\d.]+))_(?P<layer>[A-Z-]+)\.tif$")


def parse_name(name):
    """Return the parts of a DIST-ALERT layer file name, or None if it isn't one."""
    m = NAME_RE.search(name)
    if not m:
        return None
    d = m.groupdict()
    d["sensing"] = dt.datetime.strptime(d["sensing"], "%Y%m%dT%H%M%S")
    d["production"] = dt.datetime.strptime(d["production"], "%Y%m%dT%H%M%S")
    return d


def day_to_date(day):
    return EPOCH + dt.timedelta(days=int(day))


def date_to_day(date):
    if isinstance(date, str):
        date = dt.date.fromisoformat(date)
    return (date - EPOCH).days
