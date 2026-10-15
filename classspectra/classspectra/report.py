"""CSV, JSON and chart outputs."""

import csv
import json

import numpy as np

from .core import STAT_NAMES
from .legends import class_colour, class_name


def write_signatures_csv(path, results, band_names, wavelengths, legend, map_label="", append=False):
    with open(path, "a" if append else "w", newline="") as f:
        w = csv.writer(f)
        if not append:
            w.writerow(["map", "class", "class_name", "band", "wavelength_nm", "n_used"] + STAT_NAMES)
        for c, r in sorted(results.items()):
            if r["stats"] is None:
                continue
            for i, b in enumerate(band_names):
                w.writerow([map_label, c, class_name(legend, c), b,
                            wavelengths[i] if wavelengths else ""] + [r["n_used"]] +
                           [round(float(r["stats"][s][i]), 5) for s in STAT_NAMES])


def summary_rows(results, legend):
    rows = []
    for c, r in sorted(results.items()):
        rows.append({
            "class": c, "class_name": class_name(legend, c),
            "pixels": r["n_total"], "after_erosion": r["n_after_erosion"],
            "after_purity": r["n_after_purity"], "used": r["n_used"],
            "outlier_share": round(r["outlier_share"], 4),
            "spread": round(r.get("spread", float("nan")), 4),
            "ndvi_median": round(r["ndvi"]["median"], 3) if "ndvi" in r else None,
            "warnings": "; ".join(r["warnings"]),
        })
    return rows


def write_summary_csv(path, rows):
    if not rows:
        return
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def write_separability_csv(path, classes, matrix, legend):
    names = [class_name(legend, c) for c in classes]
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([""] + names)
        for n, row in zip(names, matrix):
            w.writerow([n] + [round(float(v), 3) for v in row])


def write_json(path, obj):
    def clean(o):
        if isinstance(o, dict):
            return {str(k): clean(v) for k, v in o.items() if k != "samples"}
        if isinstance(o, (list, tuple)):
            return [clean(v) for v in o]
        if isinstance(o, np.ndarray):
            return [round(float(v), 5) for v in o]
        if isinstance(o, (np.floating, float)):
            return None if not np.isfinite(o) else round(float(o), 5)
        if isinstance(o, np.integer):
            return int(o)
        return o
    with open(path, "w") as f:
        json.dump(clean(obj), f, indent=2)


def plot_signatures(path, results, band_names, wavelengths, legend, title="",
                    band="iqr", compare=None, compare_label=("Map A", "Map B")):
    """One panel per class (small multiples) or a single overlay chart.

    band: "iqr" shades p25-p75, "p10p90" shades p10-p90.
    compare: optional second results dict (same classes keyed the same way)
    drawn dashed on the same panels, for map-vs-map comparison.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    x = np.asarray(wavelengths if wavelengths else range(len(band_names)), float)
    lo, hi = ("p25", "p75") if band == "iqr" else ("p10", "p90")
    classes = [c for c, r in sorted(results.items()) if r["stats"] is not None]
    if not classes:
        return

    # Overlay panel on the left, small multiples on the right
    n = len(classes)
    ncol = min(4, n)
    nrow = int(np.ceil(n / ncol))
    fig = plt.figure(figsize=(4.2 + 2.6 * ncol, max(4.2, 2.3 * nrow)), constrained_layout=True)
    gs = fig.add_gridspec(nrow, ncol + 2)
    ax0 = fig.add_subplot(gs[:, :2])
    ymax = 0
    for c in classes:
        st = results[c]["stats"]
        col = class_colour(legend, c)
        ax0.plot(x, st["median"], color=col, lw=2, label=f"{class_name(legend, c)} (n={results[c]['n_used']:,})")
        ax0.fill_between(x, st[lo], st[hi], color=col, alpha=0.12, lw=0)
        ymax = max(ymax, float(np.nanmax(st[hi])))
    ax0.set_xlabel("Wavelength (nm)" if wavelengths else "Band")
    ax0.set_ylabel("Surface reflectance")
    ax0.set_title("All classes: median, shaded " + ("IQR" if band == "iqr" else "10th-90th pct"), fontsize=10)
    ax0.legend(fontsize=7, frameon=False, loc="upper left")
    ax0.grid(alpha=0.25)
    ax0.set_ylim(0, ymax * 1.08)

    for k, c in enumerate(classes):
        ax = fig.add_subplot(gs[k // ncol, 2 + k % ncol])
        st = results[c]["stats"]
        col = class_colour(legend, c)
        ax.fill_between(x, st[lo], st[hi], color=col, alpha=0.25, lw=0)
        ax.plot(x, st["median"], color=col, lw=1.8)
        if compare and c in compare and compare[c]["stats"] is not None:
            ax.plot(x, compare[c]["stats"]["median"], color="#222222", lw=1.2, ls="--")
        ax.set_title(class_name(legend, c), fontsize=9)
        ax.set_ylim(0, ymax * 1.08)
        ax.tick_params(labelsize=7)
        ax.grid(alpha=0.25)
        r = results[c]
        note = f"n={r['n_used']:,}  outliers {r['outlier_share']*100:.0f}%"
        ax.text(0.02, 0.97, note, transform=ax.transAxes, fontsize=6.5, va="top", color="#444444")
    if compare:
        fig.text(0.99, 0.005, f"solid: {compare_label[0]}   dashed: {compare_label[1]}",
                 ha="right", fontsize=7, color="#444444")
    if title:
        fig.suptitle(title, fontsize=11)
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_separability(path, classes, matrix, legend, title="Jeffries-Matusita separability (0-2)"):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    names = [class_name(legend, c) for c in classes]
    fig, ax = plt.subplots(figsize=(1.2 + 0.75 * len(names), 1.0 + 0.6 * len(names)), constrained_layout=True)
    im = ax.imshow(matrix, vmin=0, vmax=2, cmap="viridis")
    ax.set_xticks(range(len(names)), names, rotation=45, ha="right", fontsize=8)
    ax.set_yticks(range(len(names)), names, fontsize=8)
    for i in range(len(names)):
        for j in range(len(names)):
            v = matrix[i, j]
            ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=7,
                    color="white" if v < 1.3 else "black")
    fig.colorbar(im, ax=ax, shrink=0.8)
    ax.set_title(title, fontsize=10)
    fig.savefig(path, dpi=150)
    plt.close(fig)
