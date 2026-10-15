"""Finding dated scenes in a folder, independent of the raster library.

Recognised layouts (searched recursively, mixed freely):
  NASA HLS v2.0     HLS.S30.T37MCV.2024092T074619.v2.0.B04.tif (+ .Fmask.tif)
  Sentinel-2 L2A    a folder named like S2A_37MCV_20240303_0_L2A holding B04.tif ... SCL.tif
                    (the AWS Open Data / Element 84 layout)
  Landsat C2 L2     LC09_L2SP_168060_20240305_20240306_02_T1_SR_B4.TIF (+ _QA_PIXEL.TIF)
  Any GeoTIFF       with a date in its name (20240303, 2024-03-03 or 2024063). Bands are
                    named from their descriptions (red, nir, B04 ...) or the TP_BANDS tag,
                    otherwise b1, b2, ... A companion file <name>_Fmask.tif, _SCL.tif,
                    _QA_PIXEL.tif or _mask.tif (non-zero = clear) is used as its mask.
                    `timeprofile fetch-s2` writes files of this kind.
"""

import datetime as dt
import glob
import json
import os
import re
from collections import defaultdict

from .sensors import HLS_BANDS, LANDSAT_BANDS, NODATA, S2_BANDS, SCALE, landsat_family

HLS_RE = re.compile(r"HLS\.(?P<prod>[LS]30)\.T(?P<tile>\w{5})\.(?P<y>\d{4})(?P<doy>\d{3})T\d{6}"
                    r"\.v[\d.]+\.(?P<band>\w+)\.tif$", re.I)
S2DIR_RE = re.compile(r"^(?P<sat>S2[ABCD])_(?P<tile>\d{2}[A-Z]{3})_(?P<date>\d{8})_\d+_L2A$")
LANDSAT_RE = re.compile(r"^(?P<sensor>L[COTEM]0\d)_L2S[PR]_(?P<path>\d{6})_(?P<date>\d{8})_\d{8}_\d{2}_T[12RT]"
                        r"_(?P<band>SR_B\d|QA_PIXEL)\.tif$", re.I)
DATE8_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})-?(0[1-9]|1[0-2])-?(0[1-9]|[12]\d|3[01])(?!\d)")
DATE7_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})(00[1-9]|0[1-9]\d|[12]\d{2}|3[0-5]\d|36[0-6])(?!\d)")
MASK_SUFFIX = {"_fmask": "fmask", ".fmask": "fmask", "_scl": "scl", "_qa_pixel": "qa_pixel", "_mask": "binary"}

# Band descriptions that name a common band. Sentinel-2 / Landsat codes are mapped too.
_DESC = {name: name for name in ("coastal", "blue", "green", "red", "rededge1", "rededge2", "rededge3",
                                 "nir", "nirn", "nirb", "swir1", "swir2")}
_DESC.update({"nir08": "nirn", "swir16": "swir1", "swir22": "swir2", "b02": "blue", "b03": "green",
              "b04": "red", "b05": "rededge1", "b06": "rededge2", "b07": "rededge3", "b08": "nir",
              "b8a": "nirn", "b11": "swir1", "b12": "swir2"})


class Scene:
    """One acquisition. bands: {common name: (path, band index)}; mask: (path, band, kind) or None."""

    def __init__(self, id, date, sensor, bands, mask=None, scale=1.0, offset=0.0, nodata=None, tile=""):
        self.id, self.date, self.sensor, self.tile = id, date, sensor, tile
        self.bands, self.mask = bands, mask
        self.scale, self.offset, self.nodata = scale, offset, nodata

    def __repr__(self):
        return f"Scene({self.id}, {self.date}, {self.sensor}, {sorted(self.bands)})"


def parse_date(name):
    """A date from a file name: 20240303, 2024-03-03, or year+day-of-year 2024063."""
    for m in DATE8_RE.finditer(name):
        try:
            return dt.date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            pass
    m = DATE7_RE.search(name)
    if m:
        return dt.date(int(m[1]), 1, 1) + dt.timedelta(int(m[2]) - 1)
    return None


def _hls(paths):
    gran = defaultdict(dict)
    for p in paths:
        m = HLS_RE.search(os.path.basename(p))
        gid = os.path.basename(p)[: m.start("band") - 1]
        gran[gid]["_m"] = m
        gran[gid][m["band"]] = p
    out = []
    for gid, files in gran.items():
        m = files.pop("_m")
        bands = {c: (files[code], 1) for c, code in HLS_BANDS[m["prod"].upper()].items() if code in files}
        if not bands:
            continue
        date = dt.date(int(m["y"]), 1, 1) + dt.timedelta(int(m["doy"]) - 1)
        mask = (files["Fmask"], 1, "fmask") if "Fmask" in files else None
        out.append(Scene(gid, date, "HLS." + m["prod"].upper(), bands, mask, *SCALE["HLS"], NODATA["HLS"], m["tile"]))
    return out


def _s2_offset(folder, date):
    """(scale, offset) for an Element 84 S2 L2A folder, from its STAC item if present."""
    items = glob.glob(os.path.join(folder, "*.json"))
    for item in items:
        try:
            props = json.load(open(item)).get("properties", {})
        except (OSError, ValueError):
            continue
        pb = float(props.get("s2:processing_baseline", "0") or 0)
        if props.get("earthsearch:boa_offset_applied"):  # Element 84 already removed the offset
            return SCALE["S2"]
        if "s2:processing_baseline" in props:
            return SCALE["S2_PB04"] if pb >= 4 else SCALE["S2"]
    # No item JSON. Element 84 harmonises everything it serves, so assume no offset; other
    # sources of raw baseline 04.00+ files need --offset -0.1 (or put the item JSON beside them).
    return SCALE["S2"]


def _s2_folder(folder):
    m = S2DIR_RE.match(os.path.basename(folder.rstrip("/")))
    files = {os.path.splitext(f)[0].upper(): os.path.join(folder, f) for f in os.listdir(folder)
             if f.lower().endswith((".tif", ".tiff"))}
    bands = {c: (files[code], 1) for c, code in S2_BANDS.items() if code in files}
    if not bands:
        return None
    date = dt.datetime.strptime(m["date"], "%Y%m%d").date()
    mask = (files["SCL"], 1, "scl") if "SCL" in files else None
    return Scene(os.path.basename(folder.rstrip("/")), date, m["sat"], bands, mask,
                 *_s2_offset(folder, date), NODATA["S2"], m["tile"])


def _landsat(paths):
    groups = defaultdict(dict)
    for p in paths:
        m = LANDSAT_RE.match(os.path.basename(p))
        sid = os.path.basename(p)[: m.start("band") - 1]
        groups[sid]["_m"] = m
        groups[sid][m["band"].upper()] = p
    out = []
    for sid, files in groups.items():
        m = files.pop("_m")
        sensor = m["sensor"].upper()
        bands = {c: (files[code], 1) for c, code in LANDSAT_BANDS[landsat_family(sensor)].items() if code in files}
        if not bands:
            continue
        date = dt.datetime.strptime(m["date"], "%Y%m%d").date()
        mask = (files["QA_PIXEL"], 1, "qa_pixel") if "QA_PIXEL" in files else None
        out.append(Scene(sid, date, sensor, bands, mask, *SCALE["LANDSAT"], NODATA["LANDSAT"], m["path"]))
    return out


def _generic(path, info_fn, band_names=None, scale=None, offset=None, masks=None):
    name = os.path.basename(path)
    stem = os.path.splitext(name)[0]
    inf = info_fn(path)
    tags = {k.upper(): v for k, v in (inf.tags or {}).items()}
    date = parse_date(tags.get("TP_DATE", "")) or parse_date(stem)
    if date is None:
        return None
    if band_names:
        names = list(band_names)
    elif tags.get("TP_BANDS"):
        names = [b.strip() for b in tags["TP_BANDS"].split(",")]
    else:
        names = [_DESC.get((d or "").strip().lower(), (d or "").strip().lower()
                           if (d or "").strip().lower() in ("scl", "fmask", "qa_pixel") else "")
                 for d in inf.descriptions]
    bands, mask = {}, None
    for i in range(inf.count):
        n = names[i] if i < len(names) and names[i] else f"b{i + 1}"
        if n.lower() in ("scl", "fmask", "qa_pixel"):
            mask = (path, i + 1, n.lower())
        else:
            bands[n] = (path, i + 1)
    if mask is None and masks:
        mask = masks.get(stem.lower())
    sc = scale if scale is not None else float(tags.get("TP_SCALE", 1.0))
    off = offset if offset is not None else float(tags.get("TP_OFFSET", 0.0))
    nod = next((v for v in inf.nodata if v is not None), None)
    tile = tags.get("TP_TILE", "")
    sensor = tags.get("TP_SENSOR") or (stem[:3] if re.match(r"S2[ABCD]_", stem) else "file")
    return Scene(stem, date, sensor, bands, mask, sc, off, nod, tile)


def scan(folder, info_fn=None, band_names=None, scale=None, offset=None):
    """All scenes under folder (or one file), sorted by date. info_fn(path) is the
    backend's info(); it is only called for generic GeoTIFFs."""
    if os.path.isfile(folder):
        paths, dirs = [folder], []
    else:
        paths = [p for p in glob.glob(os.path.join(folder, "**", "*"), recursive=True)
                 if p.lower().endswith((".tif", ".tiff"))]
        dirs = [d for d in glob.glob(os.path.join(folder, "**", ""), recursive=True)
                if S2DIR_RE.match(os.path.basename(d.rstrip("/")))]
    scenes, used = [], set()
    hls = [p for p in paths if HLS_RE.search(os.path.basename(p))]
    scenes += _hls(hls)
    used.update(hls)
    for d in dirs:
        s = _s2_folder(d)
        inside = [p for p in paths if os.path.dirname(p).rstrip("/") == d.rstrip("/")]
        used.update(inside)
        if s:
            scenes.append(s)
    ls = [p for p in paths if p not in used and LANDSAT_RE.match(os.path.basename(p))]
    scenes += _landsat(ls)
    used.update(ls)
    rest = [p for p in paths if p not in used]
    masks, data = {}, []
    for p in rest:
        stem = os.path.splitext(os.path.basename(p))[0]
        low = stem.lower()
        suf = next((s for s in MASK_SUFFIX if low.endswith(s)), None)
        if suf:
            masks[low[: -len(suf)]] = (p, 1, MASK_SUFFIX[suf])
        else:
            data.append(p)
    if data and info_fn is None:
        raise ValueError("generic GeoTIFFs found; pass info_fn so their bands can be read")
    for p in data:
        s = _generic(p, info_fn, band_names, scale, offset, masks)
        if s:
            scenes.append(s)
    scenes.sort(key=lambda s: (s.date, s.id))
    return scenes


def filter_scenes(scenes, start=None, end=None, sensors=None, tiles=None):
    """Keep scenes in [start, end] (dates or 'YYYY-MM-DD'), whose sensor starts with
    one of `sensors` (e.g. ['HLS.L30', 'S2']), and on one of `tiles`."""
    def d(x):
        return dt.date.fromisoformat(x) if isinstance(x, str) else x
    start, end = d(start), d(end)
    out = []
    for s in scenes:
        if start and s.date < start or end and s.date > end:
            continue
        if sensors and not any(s.sensor.upper().startswith(x.upper()) for x in sensors):
            continue
        if tiles and s.tile.upper().lstrip("T") not in {t.upper().lstrip("T") for t in tiles}:
            continue
        out.append(s)
    return out


def describe(scenes):
    """Short text summary of a scene list."""
    if not scenes:
        return "no scenes found"
    by = defaultdict(int)
    for s in scenes:
        by[s.sensor] += 1
    bands = sorted(set.intersection(*(set(s.bands) for s in scenes)))
    nm = sum(s.mask is None for s in scenes)
    tiles = sorted({s.tile for s in scenes if s.tile})
    return (f"{len(scenes)} scenes, {scenes[0].date} to {scenes[-1].date}; "
            + ", ".join(f"{k}: {v}" for k, v in sorted(by.items()))
            + (f"; tiles {', '.join(tiles)}" if tiles else "")
            + f"; bands in every scene: {', '.join(bands) or 'none in common'}"
            + (f"; {nm} without a quality mask" if nm else ""))
