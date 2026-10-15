"""One DIST Watch run: read the newest granule per tile, report only new loss, update state."""

import csv
import json
import os

import numpy as np

from . import catalog, core
from . import products as P
from .state import State


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


def load_areas(path, name_field=None):
    """Read a GeoJSON FeatureCollection in lon/lat. Returns (features, names)."""
    with open(path) as f:
        fc = json.load(f)
    feats = [f for f in fc["features"] if f.get("geometry")]
    names = []
    for i, f in enumerate(feats):
        props = f.get("properties") or {}
        key = name_field or next((k for k in ("name", "Name", "NAME", "id", "ID") if k in props), None)
        names.append(str(props[key]) if key and props.get(key) is not None else f"area_{i + 1}")
    return feats, names


def run(data_dir, areas_path, state_dir, out_dir, *, level="confirmed", min_loss=50, since="2020-12-31",
        min_patch_px=3, forest_mask=None, as_of=None, tiles=None, name_field=None, dry_run=False,
        io=None, log=print):
    io = io or get_io()
    rules = {"level": level, "min_loss": min_loss, "since": since, "min_patch_px": min_patch_px,
             "forest_mask": os.path.basename(forest_mask) if forest_mask else None}
    st = State(state_dir)
    run_no = st.run_number
    changes = st.rule_changes(rules)
    if changes:
        log("WARNING: rules changed since the last run, so some 'new' loss may come from the change: "
            + "; ".join(f"{k} {a} -> {b}" for k, (a, b) in changes.items()))

    granules, skipped = catalog.latest_per_tile(data_dir, as_of, tiles)
    for g, why in skipped:
        log(f"skipped {g}: {why}")
    if not granules:
        raise SystemExit(f"No complete DIST-ALERT granules found in {data_dir}")
    feats, names = load_areas(areas_path, name_field)
    last = st.last_run or {}
    prev_granules = last.get("granules", {})

    # Read every tile first: the overlap rule needs all tile centres.
    tiles_data = {}
    for t, g in granules.items():
        status, grid = io.read(g["layers"]["VEG-DIST-STATUS"])
        anom, _ = io.read(g["layers"]["VEG-ANOM-MAX"])
        ddate, _ = io.read(g["layers"]["VEG-DIST-DATE"])
        conf = io.read(g["layers"]["VEG-DIST-CONF"])[0] if "VEG-DIST-CONF" in g["layers"] else None
        tiles_data[t] = dict(g=g, grid=grid, status=status, anom=anom, ddate=ddate, conf=conf,
                             center=io.tile_center(grid))

    os.makedirs(out_dir, exist_ok=True)
    area_parts = {i: [] for i in range(len(feats))}
    area_patches = {i: 0 for i in range(len(feats))}
    patch_feats, tile_rows, new_states, maps = [], [], {}, {}
    for t, d in tiles_data.items():
        g, grid = d["g"], d["grid"]
        others = [o["center"] for k, o in tiles_data.items() if k != t]
        forest = io.read_on_grid(forest_mask, grid) > 0 if forest_mask else None
        qual = core.qualifying(d["status"], d["anom"], d["ddate"], level=level, min_loss=min_loss,
                               since=since, forest=forest)
        reported = st.tile(t, grid)
        # Size filter on whole loss patches (old + new pixels), so growth at the edge of
        # an earlier clearing is reported even when the added strip is thin.
        sized = core.drop_small(core.label(qual)[0], min_patch_px)[0] > 0
        new, old, withdrawn = core.diff(qual, reported)
        labels, n = core.label(new & sized)
        kept = labels > 0

        # Ownership in the tile overlap, computed only where loss is.
        owned = np.zeros(qual.shape, bool)
        if others:
            rr, cc = np.nonzero(qual)
            lon, lat = io.lonlat(grid, rr, cc)
            owned[rr, cc] = core.owner_mask(lon, lat, d["center"], others)
        else:
            owned[:] = True

        stats = core.patch_stats(labels, n, d["anom"], d["ddate"], d["conf"])
        # A patch in the overlap belongs to the tile that owns most of its pixels.
        own_px = np.bincount(labels[kept], weights=owned[kept], minlength=n + 1)
        all_px = np.bincount(labels[kept], minlength=n + 1)
        own_patch = {s["patch"]: bool(own_px[s["patch"]] * 2 >= all_px[s["patch"]]) for s in stats}

        patch_areas = {}
        for i, (r0, r1, c0, c1), m in io.area_windows(feats, grid):
            win = np.s_[r0:r1, c0:c1]
            area_parts[i].append(core.area_counts(m, kept[win], sized[win], d["anom"][win], d["ddate"][win],
                                                  owned[win]))
            for p in np.unique(labels[win][m & kept[win]]):
                if own_patch.get(int(p)):
                    patch_areas.setdefault(int(p), []).append(names[i])
                    area_patches[i] += 1

        geoms = io.polygonize(labels, grid) if n else {}
        for s in stats:
            if not own_patch[s["patch"]]:
                continue
            lon, lat = io.lonlat(grid, [s["row"]], [s["col"]])
            props = {"tile": t, "granule": g["granule"], "run": run_no} | {
                k: v for k, v in s.items() if k not in ("row", "col")}
            props |= {"lon": round(float(lon[0]), 6), "lat": round(float(lat[0]), 6),
                      "areas": "; ".join(patch_areas.get(s["patch"], []))}
            patch_feats.append({"type": "Feature", "geometry": geoms[s["patch"]], "properties": props})

        # Map: 1 new this run, 2 reported on an earlier run, 3 loss in patches below the size limit.
        out = np.zeros(qual.shape, "uint8")
        out[qual & ~sized] = 3
        out[old & sized] = 2
        out[kept] = 1
        out[d["status"] == P.STATUS_NODATA] = 255
        io.write(os.path.join(out_dir, f"new_loss_{t}.tif"), out, grid, nodata=255)
        maps[t] = (out, grid)

        rep = reported.copy()
        rep[kept] = run_no
        new_states[t] = (rep, grid)
        tile_rows.append({
            "tile": t, "granule": g["granule"], "sensing": g["sensing"].isoformat(),
            "unchanged_since_last_run": prev_granules.get(t) == g["granule"],
            "new_patches": n, "new_loss_ha": round(kept.sum() * P.PIXEL_HA, 2),
            "below_min_patch_ha": round((qual & ~sized).sum() * P.PIXEL_HA, 2),
            "earlier_reported_ha": round((old & sized).sum() * P.PIXEL_HA, 2),
            "withdrawn_ha": round(withdrawn.sum() * P.PIXEL_HA, 2),
            "valid_pct": round(100 * float((d["status"] != P.STATUS_NODATA).mean()), 1),
        })

    rows = []
    for i, nm in enumerate(names):
        counts = core.merge_counts(area_parts[i])
        rows.append(core.area_row(nm, io.area_ha(feats[i]["geometry"]), counts, area_patches[i])
                    | {"covered": bool(area_parts[i])})
    rows.sort(key=lambda r: -r["new_loss_ha"])

    _write_csv(os.path.join(out_dir, "area_summary.csv"), rows)
    _write_csv(os.path.join(out_dir, "tiles.csv"), tile_rows)
    with open(os.path.join(out_dir, "new_loss.geojson"), "w") as f:
        json.dump({"type": "FeatureCollection", "features": patch_feats}, f)
    record = {"rules": rules, "as_of": str(as_of) if as_of else None,
              "granules": {t: d["g"]["granule"] for t, d in tiles_data.items()},
              "new_patches": len(patch_feats), "new_loss_ha": round(sum(p["properties"]["area_ha"] for p in patch_feats), 2),
              "new_loss_in_areas_ha": round(sum(p["properties"]["area_ha"] for p in patch_feats if p["properties"]["areas"]), 2),
              "areas_with_new_loss": sum(1 for r in rows if r["new_loss_ha"] > 0)}
    report = _report(run_no, record, rows, tile_rows, changes, last)
    with open(os.path.join(out_dir, "summary.md"), "w") as f:
        f.write(report)
    with open(os.path.join(out_dir, "run.json"), "w") as f:
        json.dump(record | {"run": run_no, "tiles": tile_rows, "rule_changes": changes,
                            "io": io.NAME, "dry_run": dry_run}, f, indent=1, default=str)
    try:
        from . import quicklook
        quicklook.draw(os.path.join(out_dir, "quicklook.png"), maps, feats, names, io,
                       f"DIST Watch run {run_no}: {record['new_loss_ha']} ha new loss",
                       [(f["properties"]["lon"], f["properties"]["lat"]) for f in patch_feats])
    except ImportError:
        pass
    if not dry_run:
        for t, (rep, grid) in new_states.items():
            st.set_tile(t, rep, grid)
        st.add_run(record)
    log(report)
    return record, rows, tile_rows


def _write_csv(path, rows):
    if not rows:
        open(path, "w").close()
        return
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def _report(run_no, rec, rows, tile_rows, changes, last):
    r = rec["rules"]
    lines = [f"# DIST Watch run {run_no}", ""]
    if last:
        lines.append(f"Previous run: {last['run']} at {last['time']}. Only loss not reported then is counted as new.")
    else:
        lines.append("First run: every qualifying loss counts as new. Later runs report only what was added.")
    lines += ["", f"Rules: {r['level']} alerts, at least {r['min_loss']}% vegetation loss, first detected after "
              f"{r['since']}, patches of {r['min_patch_px']}+ pixels ({r['min_patch_px'] * P.PIXEL_HA:.2f} ha)"
              + (f", inside forest mask {r['forest_mask']}" if r["forest_mask"] else "") + "."]
    if changes:
        lines.append("Rules changed since last run: " + "; ".join(f"{k} {a} -> {b}" for k, (a, b) in changes.items()))
    lines += ["", f"**{rec['new_loss_ha']} ha of new loss in {rec['new_patches']} patch{'' if rec['new_patches'] == 1 else 'es'} across the tiles "
              f"({rec['new_loss_in_areas_ha']} ha in patches touching your areas); "
              f"{rec['areas_with_new_loss']} of {len(rows)} areas affected.**",
              "Areas can overlap, so per-area figures need not add up to the total.", "",
              "| Area | New loss (ha) | New patches | Total since cutoff (ha) | First / last new detection |",
              "|---|---:|---:|---:|---|"]
    for a in rows:
        if not a["covered"]:
            lines.append(f"| {a['area']} | no data | | | no DIST tile covers this area |")
            continue
        dates = f"{a['new_first_detected']} / {a['new_last_detected']}" if a["new_first_detected"] else ""
        lines.append(f"| {a['area']} | {a['new_loss_ha']} | {a['new_patches']} | {a['total_loss_ha']} | {dates} |")
    lines += ["", "| Tile | Granule date | Same granule as last run | Valid % | Withdrawn (ha) |", "|---|---|---|---:|---:|"]
    for t in tile_rows:
        lines.append(f"| {t['tile']} | {t['sensing'][:10]} | {'yes' if t['unchanged_since_last_run'] else 'no'} | "
                     f"{t['valid_pct']} | {t['withdrawn_ha']} |")
    return "\n".join(lines) + "\n"
