"""Outputs: per-zone CSV and GeoJSON, run.json, and a one-page PNG."""
import csv
import json
import os

import numpy as np

from . import core

COLS = ["zone"] + core.SUMMARY_FIELDS


def _r(v):
    return round(v, 2) if isinstance(v, float) else v


def write_tables(res, out_dir):
    rows = sorted(res["rows"], key=lambda r: -r["flooded_crop_ha"]) + [res["whole"]]
    with open(os.path.join(out_dir, "summary.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        for r in rows:
            w.writerow({k: _r(r[k]) for k in COLS})
    if res["geoms"]:
        feats = []
        for geom, props, r in res["geoms"]:
            p = {k: v for k, v in props.items() if isinstance(v, (str, int, float, bool)) or v is None}
            p.update({k: _r(v) for k, v in r.items()})
            feats.append({"type": "Feature", "geometry": geom, "properties": p})
        fc = {"type": "FeatureCollection", "features": feats}
        zc = res.get("zones_crs")
        if zc and zc not in ("EPSG:4326", "OGC:CRS84"):
            fc["crs"] = {"type": "name", "properties": {"name": zc}}
        with open(os.path.join(out_dir, "zones_summary.geojson"), "w") as fh:
            json.dump(fc, fh)
    with open(os.path.join(out_dir, "run.json"), "w") as fh:
        json.dump(res["meta"], fh, indent=2, default=str)


def plot(res, out_dir, title="Flooded cropland", max_bars=15):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.colors import ListedColormap
        from matplotlib.patches import Patch
    except ImportError:
        return None
    g = res["grid"]
    t = g.transform
    ext = (t.c, t.c + t.a * g.width, t.f + t.e * g.height, t.f)
    flood, crop = res["flood"], np.nan_to_num(res["crop"])
    # 0 background, 1 cropland, 2 standing water, 3 flood (non-crop), 4 flooded cropland,
    # 5 partial water on cropland, 6 unobserved
    img = np.zeros(flood.shape, np.uint8)
    img[crop >= 0.5] = 1
    img[flood == core.F_STANDING] = 2
    new = flood == core.F_NEW_WATER
    img[new] = 3
    img[new & (crop >= 0.5)] = 4
    img[(flood == core.F_NEW_PARTIAL) & (crop >= 0.5)] = 5
    img[flood == core.F_UNOBSERVED] = 6
    cmap = ListedColormap(["#f4f1ea", "#c9dba3", "#2c5d8f", "#86b9e0", "#d6336c", "#f2a7c0", "#bdbdbd"])

    rows = sorted(res["rows"], key=lambda r: -r["flooded_crop_ha"])[:max_bars]
    fig = plt.figure(figsize=(14, 7.5))
    ax = fig.add_axes([0.03, 0.08, 0.55, 0.84])
    ax.imshow(img, cmap=cmap, vmin=0, vmax=6, extent=ext, interpolation="nearest")
    if res["geoms"]:
        from rasterio.warp import transform_geom
        for geom, props, r in res["geoms"]:
            gg = transform_geom(res.get("zones_crs") or "EPSG:4326", g.crs, geom)
            polys = gg["coordinates"] if gg["type"] == "MultiPolygon" else [gg["coordinates"]]
            for poly in polys:
                xy = np.asarray(poly[0])
                ax.plot(xy[:, 0], xy[:, 1], color="#333", lw=0.7)
        ax.set_xlim(ext[0], ext[1])
        ax.set_ylim(ext[2], ext[3])
    ax.set_title(title, fontsize=11, loc="left")
    ax.tick_params(labelsize=8)
    ax.legend(handles=[Patch(color=c, label=l) for c, l in zip(
        cmap.colors[1:], ["cropland (>=50% of pixel)", "water before event / permanent", "new water, not cropland",
                          "flooded cropland (open water)", "partial water on cropland", "not observed"])], loc="lower left", fontsize=8, framealpha=0.9)
    if rows:
        bx = fig.add_axes([0.70, 0.08, 0.27, 0.84])
        names = [r["zone"] for r in rows][::-1]
        bx.barh(names, [r["flooded_crop_ha"] for r in rows][::-1], color="#d6336c", label="open water")
        bx.barh(names, [r["flooded_crop_partial_ha"] for r in rows][::-1],
                left=[r["flooded_crop_ha"] for r in rows][::-1], color="#f2a7c0", label="partial water")
        for i, r in enumerate(rows[::-1]):
            bx.text(r["flooded_crop_ha"] + r["flooded_crop_partial_ha"], i,
                    f"  {r['flooded_crop_ha']:,.0f} ha ({r['flooded_crop_pct']:.1f}%)", va="center", fontsize=7.5)
        bx.set_xlabel("flooded cropland (ha)", fontsize=9)
        bx.tick_params(labelsize=8)
        bx.spines[["top", "right"]].set_visible(False)
        bx.legend(fontsize=8, loc="lower right", frameon=False)
        bx.margins(x=0.5)
    w = res["whole"]
    fig.text(0.03, 0.02, f"Whole area: {w['flooded_crop_ha']:,.0f} ha of {w['crop_ha']:,.0f} ha cropland newly under open water "
             f"({w['flooded_crop_pct']:.1f}% of observed cropland), plus {w['flooded_crop_partial_ha']:,.0f} ha partial water. "
             f"{w['crop_observed_pct']:.0f}% of cropland observed.", fontsize=8.5)
    p = os.path.join(out_dir, "map.png")
    fig.savefig(p, dpi=110)
    plt.close(fig)
    return p
