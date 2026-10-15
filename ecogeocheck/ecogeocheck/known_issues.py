"""Dated ECOSTRESS problems that NASA lists on the v002 product pages.

These don't move pixels, but they matter for the same "should I trust this
scene?" question, so each scene is checked against them.
Source: earthdata.nasa.gov catalog pages for ECO_L1B_GEO.002 and ECO_L2T_LSTE.002
(read 2026-10-15).
"""

from datetime import datetime

# (start, end, level, message). level "caution" changes the decision; "note" only reports.
WINDOWS = [
    (datetime(2018, 9, 29), datetime(2019, 5, 15), "note",
     "mass storage unit anomalies: acquisitions were interrupted"),
    (datetime(2019, 5, 15), datetime(2023, 4, 28), "note",
     "3-band period: bands 2, 4 and 5 were not downlinked and hold fill values"),
    (datetime(2020, 2, 8), datetime(2020, 2, 17), "note",
     "band 4 striping (NASA reprocessed these; check you have the reprocessed build)"),
    (datetime(2025, 5, 15), datetime(2025, 7, 2), "caution",
     "data noisier than expected (15 May to 1 July 2025); NASA says use with caution"),
]
FOV_RELIABLE_FROM = datetime(2024, 10, 24)  # orbit 35724
FOV_FALSE_POSITIVE = (datetime(2024, 12, 15), datetime(2025, 1, 1))  # "late December 2024"


def check(time, fov_obstruction=None):
    """List of (level, message) for a scene time and its FieldOfViewObstruction value."""
    out = []
    if time is None:
        return out
    for a, b, level, msg in WINDOWS:
        if a <= time < b:
            out.append((level, msg))
    if fov_obstruction:
        if time < FOV_RELIABLE_FROM:
            out.append(("note", "FieldOfViewObstruction is set, but the field was unreliable before 2024-10-24"))
        elif FOV_FALSE_POSITIVE[0] <= time < FOV_FALSE_POSITIVE[1]:
            out.append(("caution", "ISS solar array may obstruct the view (late December 2024 has false positives)"))
        else:
            out.append(("caution", "ISS solar array obstructs part of the view (FieldOfViewObstruction)"))
    return out
