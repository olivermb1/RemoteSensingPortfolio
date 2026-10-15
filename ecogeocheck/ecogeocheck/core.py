"""Check a set of ECOSTRESS files: read NASA's geolocation flags, measure the
real offset where possible, and decide keep / caution / check / drop / fixed."""

import csv
import json
import math
import os
import shutil
from collections import OrderedDict
from datetime import datetime, timedelta

import numpy as np

from . import flags, known_issues, names, shift

DATA_EXT = (".tif", ".tiff")
TARGET_LAYERS = ("LST", "SDS_LST", "LST_K")
# Layers looked up from static maps (water mask, DEM) at each pixel's map position, so they sit in the
# right place even when the observation is shifted. This is an inference from how L2 products are made;
# it is why a scene's own water layer can serve as the reference, and why --fix doesn't move these.
STATIC_LAYERS = ("water", "height")
DEFAULTS = dict(accept=("best", "good"), tolerance_m=140.0, max_shift_m=7700.0, fix=False, rescue=False,
                measure=True, use_water=True, use_stack=True)
DECISIONS = ("keep", "fixed", "caution", "check", "drop")


def get_io(prefer=None):
    if prefer != "gdal":
        try:
            from . import rio_io
            return rio_io
        except ImportError:
            if prefer == "rasterio":
                raise
    from . import gdal_io
    return gdal_io


# ---------------------------------------------------------------- collecting files

def collect(inputs):
    """Group files into scenes. Returns (scenes OrderedDict, geo_flags dict, warnings)."""
    paths = []
    for p in inputs:
        if os.path.isdir(p):
            for root, _, files in os.walk(p):
                paths += [os.path.join(root, f) for f in sorted(files)]
        elif os.path.exists(p):
            paths.append(p)
    scenes, geo, sidecars, warnings = OrderedDict(), {}, {}, []
    for p in sorted(paths):
        low = p.lower()
        info = names.parse(p)
        if info is None:
            if low.endswith(DATA_EXT + (".h5",)):
                warnings.append(f"skipped (name not recognised as ECOSTRESS): {os.path.basename(p)}")
            continue
        key = names.scene_key(info)
        if low.endswith((".json", ".xml")):
            sidecars.setdefault(key, []).append(p)
            continue
        if names.is_geo_file(info) and low.endswith(".h5"):
            rec = flags.from_hdf5(p)
            if rec:
                geo[key] = rec
            else:
                warnings.append(f"no geolocation fields found in {os.path.basename(p)}")
            continue
        if not low.endswith(DATA_EXT + (".h5",)):
            continue
        skey = key + ((info.get("tile") or ""),)
        sc = scenes.setdefault(skey, {"key": key, "orbit": info["orbit"], "scene": info["scene"],
                                      "tile": info.get("tile") or "", "time": info["time"],
                                      "product": info["product"], "layers": OrderedDict(), "h5": []})
        if low.endswith(".h5"):
            sc["h5"].append(p)
        else:
            sc["layers"][info.get("layer") or os.path.basename(p)] = p
    for sc in scenes.values():
        sc["sidecars"] = sidecars.get(sc["key"], [])
    return scenes, geo, warnings


def _summary_lookup(table, sc):
    if not table:
        return None
    if sc["key"] in table:
        return table[sc["key"]]
    t = sc["time"]  # AppEEARS files: match on time, within a minute
    for dm in (0, -1, 1):
        k = ("t", (t + timedelta(minutes=dm)).strftime("%Y%m%dT%H%M"))
        if k in table:
            return table[k]
    return None


def scene_flags(sc, geo, table, io):
    """All flag records found for a scene, most trusted first."""
    found = []
    if sc["key"] in geo:
        found.append(geo[sc["key"]])
    for h in sc["h5"]:
        r = flags.from_hdf5(h)
        if r:
            r["source"] = f"metadata in {os.path.basename(h)}"
            found.append(r)
    target = _target_layer(sc)
    if target:
        try:
            r = flags.from_tags(io.read_tags(target), f"tags in {os.path.basename(target)}")
            if r:
                found.append(r)
        except Exception:
            pass
    for s in sc["sidecars"]:
        r = flags.from_sidecar(s)
        if r:
            found.append(r)
    r = _summary_lookup(table, sc)
    if r:
        found.append(r)
    return found


def merge_flags(found):
    out = {"geo_qa": None, "geo_qa_source": "", "geo_qa_note": "", "orbit_corrected": None,
           "fov_obstruction": None, "conflict": ""}
    for r in found:
        if out["geo_qa"] is None and r["geo_qa"]:
            out["geo_qa"], out["geo_qa_source"], out["geo_qa_note"] = r["geo_qa"], r["source"], r["geo_qa_note"]
        elif r["geo_qa"] and out["geo_qa"] and r["geo_qa"] != out["geo_qa"] and not out["conflict"]:
            out["conflict"] = f"{r['source']} says '{r['geo_qa']}'"
        if out["orbit_corrected"] is None and r["orbit_corrected"] is not None:
            out["orbit_corrected"] = r["orbit_corrected"]
        if out["fov_obstruction"] is None and r["fov_obstruction"] is not None:
            out["fov_obstruction"] = r["fov_obstruction"]
    return out


def _target_layer(sc):
    for k in TARGET_LAYERS:
        if k in sc["layers"]:
            return sc["layers"][k]
    for k, v in sc["layers"].items():
        if "LST" in k and "err" not in k.lower():
            return v
    return None


# ---------------------------------------------------------------- measuring

def _load_target(sc, io):
    lst, grid, _ = io.read(_target_layer(sc))
    valid = np.isfinite(lst) & (lst > 150) & (lst < 400)  # Kelvin; 0 and fill values drop out
    if "cloud" in sc["layers"]:
        c, _, _ = io.read(sc["layers"]["cloud"])
        if c.shape == lst.shape:
            valid &= ~(c == 1)
    return lst, valid, grid


def _metres_per_pixel(grid, io):
    if "GEOGCS" in grid.wkt[:10] or "GEOGCRS" in grid.wkt[:10]:
        lat = math.radians((grid.bounds[1] + grid.bounds[3]) / 2)
        return abs(grid.gt[1]) * 111320 * math.cos(lat), abs(grid.gt[5]) * 110574
    return abs(grid.gt[1]), abs(grid.gt[5])


def measure_scene(sc, io, reference=None, stack=None, opts=DEFAULTS):
    """Measure the scene's offset. Returns a dict (see shift.measure) plus metres and the reference used."""
    if not _target_layer(sc):
        return {"ok": False, "why": "no LST GeoTIFF layer to match", "reference": ""}
    lst, valid, grid = _load_target(sc, io)
    mx, my = _metres_per_pixel(grid, io)
    max_px = int(opts["max_shift_m"] / max(mx, my))
    ref = ref_valid = None
    used = ""
    if reference:
        ref = io.read_on_grid(reference, grid)
        ref_valid, used = np.isfinite(ref), f"reference {os.path.basename(reference)}"
    elif opts.get("use_water", True) and "water" in sc["layers"]:
        w, wgrid, _ = io.read(sc["layers"]["water"])
        if w.shape != lst.shape or not np.allclose(wgrid.gt, grid.gt):
            w = io.read_on_grid(sc["layers"]["water"], grid, "nearest")
        wv = np.isfinite(w) & (w <= 1)
        frac = float((w[wv] == 1).mean()) if wv.any() else 0.0
        if w.shape == lst.shape and 0.005 <= frac <= 0.9:
            ref, ref_valid, used = (w == 1).astype("float64"), wv, f"own water layer ({frac:.1%} water)"
    if ref is None and stack is not None:
        ref, ref_valid, used = stack["image"], np.isfinite(stack["image"]), stack["label"]
    if ref is None:
        return {"ok": False, "why": "no reference: no water in view, no --reference, and no 'best' scenes "
                                    "of this tile to compare with", "reference": ""}
    r = shift.measure(ref, ref_valid, lst, valid, max_shift=max_px)
    r["reference"] = used
    r["grid_gt"] = list(grid.gt)
    if r["dx"] is not None:
        r["dx_m"], r["dy_m"] = r["dx"] * mx, r["dy"] * my
        r["offset_m"] = math.hypot(r["dx_m"], r["dy_m"])
    return r


def build_stacks(scenes, results, io):
    """Per tile: median of standardised LST from scenes flagged 'best' (and not measured off)."""
    stacks = {}
    by_tile = {}
    for skey, sc in scenes.items():
        res = results[skey]
        if res["geo_qa"] == "best" and res["orbit_corrected"] is not False and _target_layer(sc) \
                and not (res.get("m_ok") and res.get("offset_m", 0) > DEFAULTS["tolerance_m"]):
            by_tile.setdefault(sc["tile"], []).append(skey)
    for tile, keys in by_tile.items():
        imgs, shape = {}, None
        for k in keys:
            lst, valid, grid = _load_target(scenes[k], io)
            if shape is None:
                shape = lst.shape
            if lst.shape != shape or valid.sum() < 100:
                continue
            z = np.where(valid, (lst - np.nanmean(lst[valid])) / (np.nanstd(lst[valid]) or 1), np.nan)
            imgs[k] = z
        if imgs:
            stacks[tile] = imgs
    return stacks


def stack_for(stacks, sc, skey):
    imgs = {k: v for k, v in stacks.get(sc["tile"], {}).items() if k != skey}
    if not imgs:
        return None
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            med = np.nanmedian(np.stack(list(imgs.values())), axis=0)
    return {"image": med, "label": f"median of {len(imgs)} 'best' scene(s) of tile {sc['tile']}"}


# ---------------------------------------------------------------- deciding

def decide(res, opts=DEFAULTS):
    """Fill res['decision'] and res['reasons'] from the flags and the measurement."""
    accept = set(opts["accept"])
    reasons = []
    qa = res["geo_qa"]
    if qa is None and res["orbit_corrected"] is False:
        qa = "poor"
        reasons.append("OrbitCorrectionPerformed=False: not corrected, up to 7 km off")
    elif qa is None and res["orbit_corrected"] is True:
        qa = "good"
        reasons.append("no QA word, but OrbitCorrectionPerformed=True")
    res["geo_qa_effective"] = qa
    if qa in accept:
        base = "keep"
        reasons.append(f"NASA flag '{qa}' ({flags.QA_ERROR[qa]})")
    elif qa in flags.QA_LEVELS:
        base = "drop"
        reasons.append(f"NASA flag '{qa}' ({flags.QA_ERROR[qa]})")
    else:
        base = "check"
        reasons.append("no geolocation flag found for this scene")
    if res.get("conflict"):
        reasons.append(f"flags disagree: {res['conflict']}")

    m_ok, off = res.get("m_ok"), res.get("offset_m")
    tol = opts["tolerance_m"]
    decision = base
    if m_ok:
        big = off > tol
        txt = f"measured offset {off:.0f} m ({res['dx_m']:+.0f} m E, {-res['dy_m']:+.0f} m N) against {res['reference']}"
        if big and opts["fix"]:
            decision = "fixed"
            reasons.append(txt + "; shifted copy written")
        elif big:
            decision = "drop"
            reasons.append(txt + f", over the {tol:.0f} m tolerance")
        else:
            reasons.append(txt + ", within tolerance")
            if base == "check":
                decision = "keep"
            elif base == "drop" and opts["rescue"]:
                decision = "keep"
                reasons.append("kept despite the flag because the measurement is within tolerance (--rescue)")
    elif res.get("m_why"):
        reasons.append(f"offset not measured: {res['m_why']}")
    for level, msg in res["issues"]:
        if level == "caution" and decision == "keep":
            decision = "caution"
        reasons.append(msg)
    res["decision"], res["reasons"] = decision, reasons
    return res


# ---------------------------------------------------------------- run

def run(inputs, out=None, summary=None, summary_columns=None, reference=None, io=None, log=print, **kw):
    opts = dict(DEFAULTS, **kw)
    io = io or get_io()
    scenes, geo, warnings = collect(inputs)
    table, table_desc = ({}, "")
    if summary:
        table, table_desc = flags.read_summary(summary, summary_columns)
        log(f"summary table: {table_desc}")
    log(f"{len(scenes)} scene(s), {len(geo)} L1B GEO file(s) with flags")
    results = OrderedDict()
    for skey, sc in scenes.items():
        f = merge_flags(scene_flags(sc, geo, table, io))
        res = {"orbit": sc["orbit"], "scene": sc["scene"], "tile": sc["tile"],
               "time": sc["time"].strftime("%Y-%m-%dT%H:%M:%S"), "product": sc["product"],
               "layers": list(sc["layers"]), "files": list(sc["layers"].values()) + sc["h5"], **f}
        res["issues"] = known_issues.check(sc["time"], f["fov_obstruction"])
        results[skey] = res

    def apply(skey, m):
        res = results[skey]
        res.update(m_ok=bool(m.get("ok")), m_why=m.get("why", ""), reference=m.get("reference", ""),
                   dx_m=m.get("dx_m"), dy_m=m.get("dy_m"), offset_m=m.get("offset_m"),
                   match_peak=m.get("peak"), match_distinct=m.get("distinct"), _gt=m.get("grid_gt"),
                   _dx=m.get("dx"), _dy=m.get("dy"))

    if opts["measure"]:
        pending = []
        for skey, sc in scenes.items():
            m = measure_scene(sc, io, reference, None, opts)
            if not m.get("ok") and opts["use_stack"] and m.get("why", "").startswith("no reference"):
                pending.append(skey)
            apply(skey, m)
        if pending:
            stacks = build_stacks(scenes, results, io)
            for skey in pending:
                st = stack_for(stacks, scenes[skey], skey)
                if st:
                    apply(skey, measure_scene(scenes[skey], io, None, st, opts))
    for skey in results:
        decide(results[skey], opts)
        log(f"  {_label(results[skey])}: {results[skey]['decision'].upper()}")

    summary_out = {d: sum(r["decision"] == d for r in results.values()) for d in DECISIONS}
    run_info = {"tool": "ecogeocheck", "inputs": list(inputs), "summary_table": summary, "summary_detected": table_desc,
                "reference": reference, "options": {k: (list(v) if isinstance(v, tuple) else v) for k, v in opts.items()},
                "io": io.NAME, "counts": summary_out, "warnings": warnings}
    if out:
        write_outputs(out, scenes, results, run_info, io, opts)
        log(f"outputs in {out}")
    for w in warnings:
        log(f"warning: {w}")
    return results, run_info


def _label(r):
    sid = f"orbit {r['orbit']} scene {r['scene']}" if r["orbit"] is not None else r["time"]
    return f"{sid}{' tile ' + r['tile'] if r['tile'] else ''} ({r['time'][:16]})"


CSV_FIELDS = ["orbit", "scene", "tile", "time", "decision", "geo_qa", "geo_qa_effective", "geo_qa_source",
              "orbit_corrected", "fov_obstruction", "offset_m", "dx_m", "dy_m", "match_peak", "match_distinct",
              "reference", "reasons", "files"]


def write_outputs(out, scenes, results, run_info, io, opts):
    os.makedirs(out, exist_ok=True)
    rows = []
    keep, drop = [], []
    for skey, r in results.items():
        files = r["files"]
        if r["decision"] == "fixed" and r.get("_gt"):
            sdir = os.path.join(out, "shifted")
            os.makedirs(sdir, exist_ok=True)
            gt = shift.corrected_geotransform(r["_gt"], r["_dx"], r["_dy"])
            new = []
            for layer, p in scenes[skey]["layers"].items():
                dst = os.path.join(sdir, os.path.basename(p))
                if layer in STATIC_LAYERS:  # looked up from static maps at the right place: leave as is
                    shutil.copyfile(p, dst)
                else:
                    io.copy_with_geotransform(p, dst, gt)
                new.append(dst)
            r["shifted_files"] = new
            files = new
        (keep if r["decision"] in ("keep", "caution", "fixed") else drop).extend(files)
        row = {k: r.get(k) for k in CSV_FIELDS}
        row["reasons"] = "; ".join(r["reasons"])
        row["files"] = " ".join(os.path.basename(f) for f in files)
        for k in ("offset_m", "dx_m", "dy_m"):
            row[k] = None if row[k] is None else round(row[k], 1)
        if row["dy_m"] is not None:
            row["dy_m"] = -row["dy_m"]  # report north-positive in the table
        rows.append(row)
    with open(os.path.join(out, "scenes.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, CSV_FIELDS)
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(out, "keep.txt"), "w") as f:
        f.write("".join(p + "\n" for p in keep))
    with open(os.path.join(out, "drop.txt"), "w") as f:
        f.write("".join(p + "\n" for p in drop))
    _write_footprints(os.path.join(out, "scenes.geojson"), scenes, results, io)
    clean = [{k: v for k, v in r.items() if not k.startswith("_")} for r in results.values()]
    with open(os.path.join(out, "run.json"), "w") as f:
        json.dump({**run_info, "scenes": clean}, f, indent=1, default=str)
    _write_summary(os.path.join(out, "summary.md"), results, run_info, opts)
    try:
        from . import quicklook
        quicklook.plot(os.path.join(out, "quicklook.png"), list(results.values()), opts["tolerance_m"])
    except ImportError:
        pass


def _write_footprints(path, scenes, results, io):
    feats = []
    for skey, sc in scenes.items():
        t = _target_layer(sc) or next(iter(sc["layers"].values()), None)
        if not t:
            continue
        try:
            _, grid, _ = io.read(t)
            x0, y0, x1, y1 = io.bounds_lonlat(grid)
        except Exception:
            continue
        r = results[skey]
        props = {k: r.get(k) for k in CSV_FIELDS if k not in ("files",)}
        props["reasons"] = "; ".join(r["reasons"])
        feats.append({"type": "Feature", "properties": props, "geometry": {
            "type": "Polygon", "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}})
    with open(path, "w") as f:
        json.dump({"type": "FeatureCollection", "features": feats}, f, default=str)


def _write_summary(path, results, run_info, opts):
    c = run_info["counts"]
    L = ["# ECOSTRESS geolocation check", "",
         f"{len(results)} scenes: **{c['keep']} keep**, {c['caution']} keep with caution, {c['fixed']} shifted back, "
         f"{c['check']} to check by eye, **{c['drop']} drop**.", "",
         f"Accepted NASA flags: {', '.join(opts['accept'])}. Offset tolerance: {opts['tolerance_m']:.0f} m. "
         f"Shift correction: {'on' if opts['fix'] else 'off'}.", "",
         "| Scene | Time (UTC) | Tile | NASA flag | Measured offset | Decision |", "|---|---|---|---|---|---|"]
    for r in results.values():
        sid = f"{r['orbit']}/{r['scene']:03d}" if r["orbit"] is not None else "?"
        off = f"{r['offset_m']:.0f} m" if r.get("m_ok") else ("unreliable" if r.get("offset_m") else "not measured")
        L.append(f"| {sid} | {r['time'][:16].replace('T', ' ')} | {r['tile'] or '-'} | {r['geo_qa'] or 'not found'} "
                 f"| {off} | **{r['decision']}** |")
    L += ["", "## Reasons", ""]
    for r in results.values():
        L.append(f"- **{_label(r)}**: {'; '.join(r['reasons'])}.")
    if run_info["warnings"]:
        L += ["", "## Warnings", ""] + [f"- {w}" for w in run_info["warnings"]]
    open(path, "w").write("\n".join(L) + "\n")
