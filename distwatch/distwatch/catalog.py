"""Find DIST-ALERT granules in a local folder and pick the newest per tile."""

import datetime as dt
import os

from . import products as P


def scan(folder):
    """{granule_id: {"tile", "sensing", "production", "sensor", "layers": {layer: path}}}"""
    out = {}
    for root, _, files in os.walk(folder):
        for f in files:
            d = P.parse_name(f)
            if not d:
                continue
            g = out.setdefault(d["granule"], {k: d[k] for k in ("granule", "tile", "sensing", "production",
                                                              "sensor", "version")} | {"layers": {}})
            g["layers"][d["layer"]] = os.path.join(root, f)
    return out


def latest_per_tile(folder, as_of=None, tiles=None):
    """Newest complete granule per MGRS tile, sensed on or before as_of.

    DIST-ALERT is cumulative: each granule carries the status of every
    disturbance found so far, so the newest granule per tile is all you need.
    """
    if isinstance(as_of, str):
        as_of = dt.datetime.fromisoformat(as_of)
    if isinstance(as_of, dt.date) and not isinstance(as_of, dt.datetime):
        as_of = dt.datetime.combine(as_of, dt.time.max)
    best, skipped = {}, []
    for g in scan(folder).values():
        missing = [l for l in P.REQUIRED if l not in g["layers"]]
        if missing:
            skipped.append((g["granule"], "missing " + ", ".join(missing)))
            continue
        if as_of and g["sensing"] > as_of:
            continue
        if tiles and g["tile"] not in tiles:
            continue
        cur = best.get(g["tile"])
        if cur is None or (g["sensing"], g["production"]) > (cur["sensing"], cur["production"]):
            best[g["tile"]] = g
    return dict(sorted(best.items())), skipped
