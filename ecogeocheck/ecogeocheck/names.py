"""Parse ECOSTRESS file and granule names.

Collection 2 (v002) examples:
  ECOv002_L2T_LSTE_33138_005_37MBU_20240505T081052_0712_01_LST.tif   (tiled, one file per layer)
  ECOv002_L2G_LSTE_33138_005_20240505T081052_0712_01.h5             (gridded swath)
  ECOv002_L1B_GEO_33138_005_20240505T081052_0712_01.h5              (geolocation, holds the QA flag)
Collection 1 (v001):
  ECOSTRESS_L1B_GEO_05542_007_20190706T143255_0601_01.h5
AppEEARS outputs lose the orbit and scene numbers but keep the time:
  ECO2LSTE.001_SDS_LST_doy2019189165617_aid0001.tif
  ECO_L2T_LSTE.002_LST_doy2024126081052_aid0001_37N.tif

The orbit + scene pair identifies a scene: every product made from the same
acquisition shares it, which is how a tiled LST file is matched to its L1B
GEO file and to NASA's flag list.
"""

import os
import re
from datetime import datetime, timedelta

_NASA = re.compile(
    r"(?P<prefix>ECOv00\d|ECOSTRESS)_(?P<product>L[0-4][A-Z]?(?:_[A-Z0-9]+)*?)_(?P<orbit>\d{5})_(?P<scene>\d{3})_"
    r"(?:(?P<tile>\d{2}[A-Z]{3})_)?(?P<dt>\d{8}T\d{6})_(?P<build>\d{4})_(?P<iter>\d{2})(?:_(?P<layer>[A-Za-z0-9_]+?))?"
    r"(?:\.(?P<ext>tif|tiff|h5|nc|json|xml|TIF))?$"
)
_APPEEARS = re.compile(r"(?P<product>ECO[\w.]+?)_.*?doy(?P<year>\d{4})(?P<doy>\d{3})(?P<hms>\d{6})_aid\d+")


def parse(name):
    """Dict with orbit, scene, tile, time (datetime), product, layer, collection; or None."""
    base = os.path.basename(str(name))
    stem = re.sub(r"\.(tif|tiff|TIF|h5|nc|json|xml|cmr\.xml)$", "", base)
    m = _NASA.search(stem)
    if m:
        d = m.groupdict()
        return {
            "orbit": int(d["orbit"]),
            "scene": int(d["scene"]),
            "tile": d["tile"],
            "time": datetime.strptime(d["dt"], "%Y%m%dT%H%M%S"),
            "product": d["product"],
            "layer": d["layer"],
            "collection": 2 if d["prefix"].startswith("ECOv002") else 1,
            "build": d["build"],
        }
    m = _APPEEARS.search(stem)
    if m:
        t = datetime(int(m["year"]), 1, 1) + timedelta(days=int(m["doy"]) - 1)
        t = t.replace(hour=int(m["hms"][:2]), minute=int(m["hms"][2:4]), second=int(m["hms"][4:]))
        rest = stem[m.end():]
        tile = re.search(r"_(\d{2}[A-Z])$", rest)
        layer = re.search(r"_(LST_err|LST|QC|cloud|water|EmisWB|height|view_zenith)_", stem)
        return {"orbit": None, "scene": None, "tile": tile.group(1) if tile else None, "time": t,
                "product": m["product"], "layer": layer.group(1) if layer else None,
                "collection": 2 if ".002" in m["product"] else 1, "build": None}
    return None


def scene_key(info):
    """('orbit', 'scene') when known, otherwise the acquisition time to the minute."""
    if info.get("orbit") is not None:
        return (info["orbit"], info["scene"])
    return ("t", info["time"].strftime("%Y%m%dT%H%M"))


def is_geo_file(info):
    return bool(info) and "GEO" in (info.get("product") or "").upper()
