"""Find NASA's geolocation quality fields for a scene, wherever they are.

The fields (from the ECO_L1B_GEO v002 and ECO_L2T_LSTE v002 product pages):
  GeolocationAccuracyQA      "best", "good", "suspect" or "poor"
                             NASA recommends only best and good where geolocation matters.
  OrbitCorrectionPerformed   "True": image matching worked, better than 50 m.
                             "False": not corrected, up to 7 km error.
  FieldOfViewObstruction     ISS solar array in view. Only reliable from 2024-10-24 (orbit 35724).

They always live in the L1B GEO file (group L1GEOMetadata). NASA says they
are not yet carried into every higher-level product, and also publishes a
summary text file listing the flag for every scene since launch. So this
module reads, in order of trust: L1B GEO files, the granule's own metadata
(GeoTIFF tags, a sidecar .json/.xml, or CMR UMM-G attributes), and the
summary table.
"""

import csv
import io
import json
import os
import re

FIELDS = ("GeolocationAccuracyQA", "GeolocationAccuracyQAExplanation", "OrbitCorrectionPerformed",
          "FieldOfViewObstruction")
QA_LEVELS = ("best", "good", "suspect", "poor")
# Expected error per level, from NASA's pages and the LP DAAC forum (p=24716).
QA_ERROR = {"best": "< 50 m", "good": "about 50 m (corrected from a nearby matched scene)",
            "suspect": "about 2 to 4 km", "poor": "up to 7 km"}


def norm_qa(v):
    if v is None:
        return None
    s = _text(v).strip().lower()
    for lvl in QA_LEVELS:
        if s == lvl or s.startswith(lvl):
            return lvl
    if s in ("no match", "nomatch", "uncorrected"):
        return "poor"
    return None


def norm_bool(v):
    if v is None:
        return None
    s = _text(v).strip().lower()
    if s in ("true", "t", "1", "yes", "y"):
        return True
    if s in ("false", "f", "0", "no", "n"):
        return False
    return None


def _text(v):
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    if hasattr(v, "tolist"):
        v = v.tolist()
    if isinstance(v, (list, tuple)):
        return _text(v[0]) if v else ""
    return str(v)


def _pick(items):
    """items: iterable of (key, value). Returns {field: raw value} for the fields we know."""
    out = {}
    for k, v in items:
        # Keys arrive as "L1GEOMetadata/GeolocationAccuracyQA" (h5py), "L1GEOMetadata_GeolocationAccuracyQA"
        # (GDAL) or plain names, so match on the end of the key.
        for f in FIELDS:
            if str(k).lower().endswith(f.lower()):
                out.setdefault(f, _text(v))
    return out


def to_record(raw, source):
    """Normalise a {field: raw} dict to the fields used downstream."""
    if not raw:
        return None
    rec = {
        "geo_qa": norm_qa(raw.get("GeolocationAccuracyQA")),
        "geo_qa_note": raw.get("GeolocationAccuracyQAExplanation") or "",
        "orbit_corrected": norm_bool(raw.get("OrbitCorrectionPerformed")),
        "fov_obstruction": norm_bool(raw.get("FieldOfViewObstruction")),
        "source": source,
    }
    if rec["geo_qa"] is None and rec["orbit_corrected"] is None and rec["fov_obstruction"] is None:
        return None
    return rec


# ---------------------------------------------------------------- readers

def from_hdf5(path):
    """Read the fields from an L1B GEO (or any ECOSTRESS) HDF5 file: h5py first, then GDAL.

    path can also be an open file object (h5py reads remote files that way)."""
    items = []
    try:
        import h5py
        with h5py.File(path, "r") as f:
            def visit(name, obj):
                for ak, av in obj.attrs.items():
                    items.append((f"{name}/{ak}", av))
                if isinstance(obj, h5py.Dataset) and name.split("/")[-1] in FIELDS:
                    items.append((name, obj[()]))
            for ak, av in f.attrs.items():
                items.append((ak, av))
            f.visititems(visit)
    except ImportError:
        try:
            items = _gdal_hdf5_items(path)
        except Exception:
            return None
    except OSError:
        return None
    return to_record(_pick(items), "L1B_GEO file")


def _gdal_hdf5_items(path):
    """Walk the file with GDAL's multidimensional API: scalar string datasets and attributes.
    (Classic gdal.Open metadata does not show scalar string datasets.)"""
    from osgeo import gdal
    gdal.UseExceptions()
    items = []
    ds = gdal.OpenEx(path, gdal.OF_MULTIDIM_RASTER)

    def walk(g, prefix):
        for a in g.GetAttributes() or []:
            items.append((f"{prefix}/{a.GetName()}", a.Read()))
        for n in g.GetMDArrayNames() or []:
            if n in FIELDS:
                arr = g.OpenMDArray(n)
                items.append((f"{prefix}/{n}", arr.Read() if arr.GetDataType().GetClass() == gdal.GEDTC_STRING
                              else arr.ReadAsArray()))
        for n in g.GetGroupNames() or []:
            walk(g.OpenGroup(n), f"{prefix}/{n}")
    walk(ds.GetRootGroup(), "")
    return items


def from_tags(tags, source="file metadata"):
    return to_record(_pick(tags.items()), source)


def from_umm(umm, source="CMR granule metadata"):
    """CMR UMM-G JSON: AdditionalAttributes [{Name, Values}]."""
    items = [(a.get("Name", ""), (a.get("Values") or [None])[0]) for a in umm.get("AdditionalAttributes", [])]
    return to_record(_pick(items), source)


def from_sidecar(path):
    """A .json (UMM-G or plain) or .xml (ECHO10 or ISO) file next to the data."""
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return None
    if path.lower().endswith(".json"):
        try:
            d = json.loads(text)
        except ValueError:
            return None
        if isinstance(d, dict) and "AdditionalAttributes" in d:
            return from_umm(d, f"sidecar {os.path.basename(path)}")
        items = []

        def walk(o, k=""):
            if isinstance(o, dict):
                for kk, vv in o.items():
                    walk(vv, kk)
            elif isinstance(o, list) and o and not isinstance(o[0], (dict, list)):
                items.append((k, o[0]))
            elif isinstance(o, list):
                for vv in o:
                    walk(vv, k)
            else:
                items.append((k, o))
        walk(d)
        return to_record(_pick(items), f"sidecar {os.path.basename(path)}")
    items = []
    for f in FIELDS:
        # ECHO10: <Name>F</Name><Values><Value>x</Value>; also <F>x</F>
        m = re.search(rf"<Name>\s*{f}\s*</Name>.*?<Value>\s*([^<]+?)\s*</Value>", text, re.S)
        m = m or re.search(rf"<{f}>\s*([^<]+?)\s*</{f}>", text)
        if m:
            items.append((f, m.group(1)))
    return to_record(_pick(items), f"sidecar {os.path.basename(path)}")


# ---------------------------------------------------------------- summary table

def read_summary(path, columns=None):
    """Read a table of per-scene geolocation flags (NASA's summary file or your own).

    NASA's file layout was not seen when this was written, so the reader guesses:
    the delimiter (comma, tab, |, ; or spaces), a header row, then which columns
    hold the orbit, the scene, the time and the QA word. Pass columns=
    {"orbit": name, "scene": name, "qa": name, "time": name, "granule": name}
    to override. A granule-name column (e.g. ECOv002_L1B_GEO_33138_005_...) is
    enough on its own. Returns (lookup dict, description of what was detected).
    """
    from . import names
    text = open(path, encoding="utf-8", errors="replace").read()
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    if not lines:
        return {}, "empty"
    head = lines[0]
    delim = None
    for d in (",", "\t", "|", ";"):
        if d in head:
            delim = d
            break
    rows = list(csv.reader(io.StringIO("\n".join(lines)), delimiter=delim)) if delim else [ln.split() for ln in lines]
    rows = [[c.strip() for c in r] for r in rows]
    header = rows[0]
    has_header = not any(re.fullmatch(r"\d+", c) for c in header)
    data = rows[1:] if has_header else rows
    hl = [h.lower() for h in header] if has_header else []

    def find(*keys):
        for i, h in enumerate(hl):
            if any(k in h for k in keys):
                return i
        return None

    cols = {}
    if columns:
        for k, v in columns.items():
            cols[k] = hl.index(v.lower()) if isinstance(v, str) and v.lower() in hl else int(v)
    cols.setdefault("orbit", find("orbit"))
    cols.setdefault("scene", find("scene"))
    cols.setdefault("granule", find("granule", "filename", "file", "producer"))
    cols.setdefault("time", find("time", "date", "start"))
    cols.setdefault("qa", find("geolocationaccuracyqa", "accuracyqa", "geoqa", "geo_qa", "quality", "qa", "flag"))
    cols.setdefault("corrected", find("orbitcorrection", "corrected"))
    if cols["qa"] is None and data:  # find a column whose values are QA words
        for i in range(len(data[0])):
            if sum(norm_qa(r[i]) is not None for r in data[:50] if i < len(r)) >= min(len(data), 50) * 0.8:
                cols["qa"] = i
                break
    if not has_header and data and cols["orbit"] is None:  # headerless: first two integer columns
        ints = [i for i, c in enumerate(data[0]) if re.fullmatch(r"\d{1,6}", c)]
        if len(ints) >= 2:
            cols["orbit"], cols["scene"] = ints[0], ints[1]

    out = {}
    for r in data:
        def g(k):
            i = cols.get(k)
            return r[i] if i is not None and i < len(r) else None
        rec = to_record({"GeolocationAccuracyQA": g("qa"), "OrbitCorrectionPerformed": g("corrected")},
                        f"summary table {os.path.basename(path)}")
        if not rec:
            continue
        key = None
        if g("orbit") and g("scene") and g("orbit").isdigit() and g("scene").isdigit():
            key = (int(g("orbit")), int(g("scene")))
        elif g("granule"):
            info = names.parse(g("granule"))
            if info:
                key = names.scene_key(info)
        if key is None and g("time"):
            t = re.sub(r"[^0-9]", "", g("time"))[:12]
            if len(t) == 12:
                key = ("t", f"{t[:8]}T{t[8:12]}")
        if key is not None:
            out[key] = rec
    used = ", ".join(f"{k}={header[v] if has_header else v}" for k, v in cols.items() if v is not None)
    return out, f"{len(out)} scenes; columns {used}; delimiter {delim or 'spaces'}"
