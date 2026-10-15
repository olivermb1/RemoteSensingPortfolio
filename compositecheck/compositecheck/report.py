"""Outputs: CSV tables, JSON report, plain-language findings and a one-page chart."""

import csv
import json
import os
import textwrap

import numpy as np

from .core import JU2025_BANDS, JU2025_THRESHOLD
from .sensors import LAYER_DOC

LANDSAT_COLOR = "#2a78d6"   # categorical slot 1
S2_COLOR = "#eb6834"        # categorical slot 2
FLAG_COLOR = "#e34948"      # status: critical
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"


def findings(rep, scenes):
    """Plain-language findings, most serious first: (level, check, text)."""
    out = []
    c1 = rep["criterion1_observations"]
    if c1["share_below_5"] > 0.05:
        out.append(("warn", "observations", f"{c1['share_below_5']:.0%} of pixels have fewer than 5 clear observations."))
    if c1["share_gap_over_60_days"] > 0.05:
        out.append(("warn", "gaps", f"{c1['share_gap_over_60_days']:.0%} of pixels go more than 60 days without a clear view."))
    dom = rep["dominance"]
    if dom["top_scene"]:
        msg = (f"The largest single scene ({dom['top_scene']}) supplies {dom['top_share']:.0%} of the composite; "
               f"the composite behaves like {dom['effective_scenes']:.1f} equal scenes.")
        if dom["dominated"] and dom["top_scene_suspect"]:
            out.insert(0, ("fail", "dominance", msg + " That scene is also flagged as a likely residual-cloud or haze scene."))
        elif dom["dominated"]:
            out.append(("warn", "dominance", msg))
        elif dom["top_scene_suspect"]:
            out.append(("warn", "dominance", msg + " That scene is flagged as suspect."))
        else:
            out.append(("ok", "dominance", msg))
    sus = [s for s in scenes if s["suspect"] and s["contribution_share"] > 0]
    share_sus = sum(s["contribution_share"] for s in sus)
    if share_sus > 0.05:
        noun = "scene that fails" if len(sus) == 1 else "scenes that fail"
        out.append(("warn", "suspect scenes", f"{share_sus:.0%} of composite pixels come from {len(sus)} {noun} the outlier screen."))
    so = rep["selected_outliers"]["share_of_pixels"]
    if so > 0.01:
        out.append(("warn", "outliers", f"{so:.1%} of composite pixels are robust outliers against their own time series."))
    ls = rep["landsat_vs_sentinel2"]
    pairs = [p for p in ls["pairs"] if p["clean"]]
    if pairs:
        good = sum(p["within_envelope"] for p in pairs)
        worst = {b: float(np.median([p[f"{b}_rel_diff"] for p in pairs])) for b in JU2025_BANDS}
        txt = ", ".join(f"{b} {v:.1%}" for b, v in worst.items())
        lvl = "ok" if good == len(pairs) else ("fail" if good == 0 else "warn")
        out.append((lvl, "Landsat vs Sentinel-2",
                    f"{good} of {len(pairs)} clean near-same-day Landsat/Sentinel-2 pairs fall inside the HLS v2.0 envelope "
                    f"(< {JU2025_THRESHOLD:.1%}, Ju et al. 2025). Median difference across pairs: {txt}."))
    elif ls["pairs"]:
        out.append(("info", "Landsat vs Sentinel-2", f"{len(ls['pairs'])} near-same-day pairs, but none share enough clear area to judge."))
    elif ls["composite_level"]:
        out.append(("info", "Landsat vs Sentinel-2", "No near-same-day pairs; only the composite-level comparison is available."))
    sens = rep["sensor"]
    if pairs and sens["composite_from_landsat"] not in (0, 1):
        out.append(("info", "sensor mix", f"{sens['composite_from_landsat']:.0%} of composite pixels come from Landsat, "
                    f"so any sensor difference shows up as a patchwork."))
    order = {"fail": 0, "warn": 1, "info": 2, "ok": 3}
    return sorted(out, key=lambda f: order[f[0]])


def write_tables(out, rep, scenes, layer_names):
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "scenes.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(scenes[0]))
        w.writeheader()
        for s in scenes:
            w.writerow({k: (round(v, 5) if isinstance(v, float) else v) for k, v in s.items()})
    pairs = rep["landsat_vs_sentinel2"]["pairs"]
    if pairs:
        with open(os.path.join(out, "pairs.csv"), "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(pairs[0]))
            w.writeheader()
            for p in pairs:
                w.writerow({k: (round(v, 5) if isinstance(v, float) else v) for k, v in p.items()})
    rep = dict(rep)
    rep["findings"] = [{"level": l, "check": c, "text": t} for l, c, t in findings(rep, scenes)]
    rep["layers"] = {n.upper(): LAYER_DOC.get(n, "") for n in layer_names}
    with open(os.path.join(out, "report.json"), "w") as fh:
        json.dump(rep, fh, indent=1, default=str)
    return rep


def plot(out, layers, rep, scenes, title="Composite Check"):
    """One-page PNG: four maps, the scene timeline and the sensor pairs."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
    except ImportError:
        return None
    plt.rcParams.update({"font.size": 9, "axes.edgecolor": GRID, "axes.labelcolor": INK2,
                         "xtick.color": INK2, "ytick.color": INK2, "text.color": INK})
    fig = plt.figure(figsize=(13, 11.5), facecolor="white")
    gs = fig.add_gridspec(4, 4, height_ratios=[0.75, 1, 0.9, 0.9], hspace=0.55, wspace=0.3)

    # findings header
    ax = fig.add_subplot(gs[0, :])
    ax.axis("off")
    ax.text(0, 1, title, fontsize=14, weight="bold", va="top")
    sub = (f"{rep['period'][0]} to {rep['period'][1]} · target {rep['target_date']} · method {rep['method']} · "
           f"{rep['landsat_scenes']} Landsat + {rep['sentinel2_scenes']} Sentinel-2 scenes")
    ax.text(0, 0.78, sub, color=INK2, va="top")
    mark = {"fail": "FAIL", "warn": "WARN", "info": "INFO", "ok": "OK"}
    y = 0.6
    for lvl, check, text in findings(rep, scenes)[:5]:
        ax.text(0, y, f"{mark[lvl]:<4}", weight="bold", va="top", family="monospace",
                color=FLAG_COLOR if lvl in ("fail", "warn") else INK2)
        lines = textwrap.wrap(f"{check}: {text}", 165)
        ax.text(0.045, y, "\n".join(lines), va="top", linespacing=1.3)
        y -= 0.115 * len(lines) + 0.03

    def show(pos, arr, label, cmap, vmin=None, vmax=None):
        a = fig.add_subplot(gs[pos])
        im = a.imshow(np.ma.masked_invalid(arr.astype(float)), cmap=cmap, vmin=vmin, vmax=vmax, interpolation="nearest")
        a.set_title(label, fontsize=9, loc="left")
        a.set_xticks([])
        a.set_yticks([])
        for s in a.spines.values():
            s.set_visible(False)
        cb = fig.colorbar(im, ax=a, fraction=0.046, pad=0.02)
        cb.outline.set_visible(False)
        return a

    show((1, 0), layers["nclear"], "Clear observations", "Blues", 0)
    show((1, 1), layers["max_gap"], "Longest gap (days)", "Oranges", 0)
    show((1, 2), np.where(layers["doyd"] >= 0, layers["doyd"], np.nan), "Days from target date", "Purples", 0)
    show((1, 3), layers["src_scene_share"] * 100, "Area share of source scene (%)", "Reds", 0)

    # scene timeline: contribution share per scene, by sensor; suspect scenes outlined
    a = fig.add_subplot(gs[2, :])
    dates = np.array([np.datetime64(s["date"]) for s in scenes]).astype("datetime64[D]").astype(object)
    for s, d in zip(scenes, dates):
        col = LANDSAT_COLOR if s["sensor"].upper().startswith("L") else S2_COLOR
        a.bar(d, s["contribution_share"] * 100, width=1.6, color=col,
              edgecolor=FLAG_COLOR if s["suspect"] else "none", linewidth=1.5 if s["suspect"] else 0)
        if s["suspect"]:
            a.plot(d, -2.5, marker="v", color=FLAG_COLOR, markersize=5)
    a.plot([], [], "s", color=LANDSAT_COLOR, label="Landsat")
    a.plot([], [], "s", color=S2_COLOR, label="Sentinel-2")
    a.plot([], [], "v", color=FLAG_COLOR, label="suspect scene (outlier screen)")
    a.axvline(np.datetime64(rep["target_date"]).astype(object), color=INK2, lw=1, ls="--")
    a.text(np.datetime64(rep["target_date"]).astype(object), a.get_ylim()[1], " target", color=INK2, va="top")
    a.set_ylabel("share of composite (%)")
    a.set_title("Where the composite's pixels came from", fontsize=9, loc="left")
    a.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    a.legend(frameon=False, loc="upper right", ncol=3)
    a.grid(axis="y", color=GRID, lw=0.6)
    a.set_axisbelow(True)
    for s in ("top", "right"):
        a.spines[s].set_visible(False)

    # Landsat vs Sentinel-2 near-coincident pairs
    a = fig.add_subplot(gs[3, :3])
    pairs = rep["landsat_vs_sentinel2"]["pairs"]
    bands = ["blue", "green", "red", "nir", "swir1", "swir2"]
    if pairs:
        x = np.arange(len(bands))
        vals = np.array([[p[f"{b}_rel_diff"] * 100 for b in bands] for p in pairs])
        clean = np.array([p["clean"] for p in pairs])
        for i, row in enumerate(vals):
            a.scatter(x + (i - len(vals) / 2) * 0.02, row, s=22 if clean[i] else 10,
                      color=INK if clean[i] else INK2, alpha=0.8 if clean[i] else 0.2, lw=0)
        a.scatter([], [], s=22, color=INK, label="clean pair (shared clear area ≥ 50%)")
        a.scatter([], [], s=10, color=INK2, alpha=0.3, label="cloudy pair (not used)")
        if clean.any():
            a.scatter(x, np.median(vals[clean], 0), marker="_", s=500, color=LANDSAT_COLOR, lw=2.5, label="median of clean pairs")
        top = np.nanmax(vals[clean]) if clean.any() else np.nanmax(vals)
        a.set_ylim(0, min(top * 1.25, 100))
        a.axhline(JU2025_THRESHOLD * 100, color=FLAG_COLOR, lw=1.2, ls="--")
        a.text(0.01, JU2025_THRESHOLD * 100, "HLS v2.0 envelope 4.2%\n(red, NIR, SWIR; Ju et al. 2025)",
               color=FLAG_COLOR, va="bottom", ha="left", fontsize=8, transform=a.get_yaxis_transform())
        a.set_xticks(x, bands)
        a.set_ylabel("median |S2 − Landsat| / mean (%)")
        a.legend(frameon=False, loc="upper right", fontsize=8)
        a.set_title(f"Landsat vs Sentinel-2, {int(sum(p['clean'] for p in pairs))} clean of {len(pairs)} near-same-day pairs (≤ {rep['landsat_vs_sentinel2']['pairs_max_days']} day apart)",
                    fontsize=9, loc="left")
        a.grid(axis="y", color=GRID, lw=0.6)
        a.set_axisbelow(True)
    else:
        a.axis("off")
        a.text(0, 0.5, "No near-same-day Landsat/Sentinel-2 pairs in this stack.", color=INK2)
    for s in ("top", "right"):
        a.spines[s].set_visible(False)

    src = layers["src_sensor"].astype(float)
    src[src == 0] = np.nan
    a = fig.add_subplot(gs[3, 3])
    from matplotlib.colors import ListedColormap
    a.imshow(np.ma.masked_invalid(src), cmap=ListedColormap([LANDSAT_COLOR, S2_COLOR]), vmin=1, vmax=2, interpolation="nearest")
    a.set_title("Sensor of each composite pixel\n(blue Landsat, orange Sentinel-2)", fontsize=9, loc="left")
    a.set_xticks([])
    a.set_yticks([])
    for s in a.spines.values():
        s.set_visible(False)

    path = os.path.join(out, "report.png")
    fig.savefig(path, dpi=110, bbox_inches="tight")
    plt.close(fig)
    return path
