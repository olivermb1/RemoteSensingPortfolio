"""Tables, JSON and one-page charts for Drought Check and the greenness link."""
from __future__ import annotations

import csv
import json
import os

import numpy as np

from . import greenness as G
from .indices import CLASS_LABELS

INK, INK2, MUTED, GRID, SURF = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#fcfcfb"
DRY, WET, MID = "#c0392b", "#2a78d6", "#f0efec"
CLASS_COLORS = {-3: "#7f1d12", -2: "#c0392b", -1: "#ec835a", 0: MID, 1: "#86b6ef", 2: "#2a78d6", 3: "#184f95"}
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]


def _clean(v):
    if isinstance(v, (np.floating, float)):
        return None if not np.isfinite(v) else round(float(v), 4)
    if isinstance(v, np.integer):
        return int(v)
    return v


def write_csv(path, rows):
    if not rows:
        return
    keys = list(rows[0].keys())
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: _clean(r.get(k)) for k in keys})


def write_json(path, obj):
    def conv(o):
        if isinstance(o, dict):
            return {str(k): conv(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [conv(v) for v in o]
        return _clean(o)
    with open(path, "w") as f:
        json.dump(conv(obj), f, indent=1)


def _style():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 9, "axes.edgecolor": GRID, "axes.labelcolor": INK2,
                         "xtick.color": MUTED, "ytick.color": MUTED, "axes.titlesize": 10,
                         "axes.titleweight": "bold", "axes.titlelocation": "left",
                         "figure.facecolor": SURF, "axes.facecolor": SURF,
                         "axes.spines.top": False, "axes.spines.right": False})
    return plt


def _dates(months):
    return np.array([np.datetime64(m + "-15") for m in months])


def plot_drought(path, res, title="Drought Check", years_shown=20):
    plt = _style()
    from matplotlib.colors import ListedColormap, BoundaryNorm
    from matplotlib.patches import Patch
    sc = res["info"]["class_scale"]
    months = res["months"]
    d = _dates(months)
    start = max(0, len(months) - 12 * years_shown)
    z = np.array([r[f"spi{sc}_aoi"] for r in res["area"]], dtype=float)

    fig = plt.figure(figsize=(11, 8.2))
    gs = fig.add_gridspec(3, 3, height_ratios=[1.1, 1, 1.5], hspace=0.55, wspace=0.25)
    ax = fig.add_subplot(gs[0, :])
    zz = z[start:]
    ax.bar(d[start:], np.where(zz < 0, zz, 0), width=26, color=DRY, label="Drier than normal")
    ax.bar(d[start:], np.where(zz >= 0, zz, 0), width=26, color=WET, label="Wetter than normal")
    for e in res["events"]:
        if e["end"] >= start:
            ax.axvspan(d[max(e["start"], start)] - np.timedelta64(15, "D"), d[e["end"]] + np.timedelta64(15, "D"),
                       color=DRY, alpha=0.08, lw=0)
    for y in (-1, -1.5, -2):
        ax.axhline(y, color=GRID, lw=0.8, zorder=0)
    ax.axhline(0, color="#c3c2b7", lw=0.8)
    ax.set_ylabel(f"SPI-{sc}")
    ax.set_title(f"Area-wide SPI-{sc} (from the area-mean rainfall); shaded spans are drought events")
    ax.legend(loc="lower left", frameon=False, ncol=2)

    ax2 = fig.add_subplot(gs[1, :], sharex=ax)
    for key, col, lab in (("pct_area_moderate_or_worse", "#ec835a", "Moderate or worse (SPI ≤ -1)"),
                          ("pct_area_severe_or_worse", "#c0392b", "Severe or worse (≤ -1.5)"),
                          ("pct_area_extreme", "#7f1d12", "Extreme (≤ -2)")):
        v = np.array([r[key] for r in res["area"]], dtype=float)[start:]
        ax2.fill_between(d[start:], 0, v, color=col, lw=0, step="mid", label=lab)
    ax2.set_ylim(0, 140); ax2.set_yticks([0, 25, 50, 75, 100]); ax2.set_ylabel("% of area")
    ax2.set_title(f"Share of pixels in drought (pixel SPI-{sc})")
    ax2.legend(loc="upper left", frameon=False, ncol=3)

    codes = sorted(CLASS_COLORS)
    cmap = ListedColormap([CLASS_COLORS[c] for c in codes])
    norm = BoundaryNorm(np.arange(-3.5, 4.5), cmap.N)
    lat = res["latest"]
    a3 = fig.add_subplot(gs[2, 0])
    cls = np.where(lat["cls"] == -99, np.nan, lat["cls"]).astype(float)
    a3.imshow(cls, cmap=cmap, norm=norm, interpolation="nearest")
    a3.set_title(f"Drought class, {lat['month']}"); a3.set_xticks([]); a3.set_yticks([])
    present = [c for c in codes if np.any(lat["cls"] == c)]
    a3.legend(handles=[Patch(color=CLASS_COLORS[c], label=CLASS_LABELS[c]) for c in present],
              loc="upper center", bbox_to_anchor=(0.5, -0.02), frameon=False, fontsize=7, ncol=2)

    L = res["layers"]
    for i, (key, lab, cm) in enumerate((("current_run", "Months in the current drought spell", "Oranges"),
                                        ("longest", "Longest drought spell (months)", "Reds"))):
        axm = fig.add_subplot(gs[2, i + 1])
        im = axm.imshow(L[key], cmap=cm, interpolation="nearest", vmin=0)
        axm.set_title(lab); axm.set_xticks([]); axm.set_yticks([])
        fig.colorbar(im, ax=axm, orientation="horizontal", fraction=0.05, pad=0.03)
    fig.suptitle(title, x=0.01, ha="left", fontsize=13, fontweight="bold", color=INK)
    fig.savefig(path, dpi=110, bbox_inches="tight")
    plt.close(fig)


def plot_greenness(path, res, title="Greenness link", top_classes=4):
    plt = _style()
    from matplotlib.colors import ListedColormap, BoundaryNorm
    from matplotlib.patches import Patch
    months = res["months"]; d = _dates(months)
    rows = sorted(res["class_rows"], key=lambda r: -r["pixels"])[:top_classes]
    s = res["scale"]

    fig = plt.figure(figsize=(11, 3 + 1.9 * len(rows)))
    gs = fig.add_gridspec(len(rows) + 1, 3, height_ratios=[1] * len(rows) + [2.2], hspace=0.6, wspace=0.25)
    for i, r in enumerate(rows):
        ax = fig.add_subplot(gs[i, :])
        ser = res["series"][r["class_code"]]
        z = ser[f"spi{s}"]
        ax.bar(d, np.where(z < 0, z, 0), width=26, color=DRY, alpha=0.35, label=f"SPI-{s}")
        ax.bar(d, np.where(z >= 0, z, 0), width=26, color=WET, alpha=0.35)
        ax.plot(d, ser["ndvi"], color=INK, lw=1.6, label="NDVI anomaly")
        ax.axhline(0, color="#c3c2b7", lw=0.8)
        ax.axvspan(np.datetime64(res["recent"][0] + "-01"), d[months.index(res["target"])] + np.timedelta64(15, "D"),
                   color=GRID, alpha=0.5, lw=0)
        ax.set_ylim(-3.2, 3.2)
        ax.set_title(f"{r['class_name']}  ({r['pixels']} px, r = {r['best_r']:.2f} at SPI-{r['best_scale']} "
                     f"lag {r['best_lag']})", fontsize=9)
        if i == 0:
            ax.legend(loc="upper left", frameon=False, ncol=2)
    codes = [0, 1, 4, 2, 3]
    order = {-1: -1, 0: 0, 1: 1, 4: 2, 2: 3, 3: 4}
    dm = np.vectorize(lambda v: order.get(int(v), -1) if np.isfinite(v) else -1)(res["layers"]["diagnosis_target"])
    cmap = ListedColormap([G.DIAG_COLORS[c] for c in [-1, 0, 1, 4, 2, 3]])
    norm = BoundaryNorm(np.arange(-1.5, 5.5), cmap.N)
    a = fig.add_subplot(gs[-1, 0])
    a.imshow(dm, cmap=cmap, norm=norm, interpolation="nearest")
    a.set_title(f"Diagnosis, {res['target']}"); a.set_xticks([]); a.set_yticks([])
    a.legend(handles=[Patch(color=G.DIAG_COLORS[c], label=G.DIAG[c]) for c in codes],
             loc="upper center", bbox_to_anchor=(0.5, -0.02), frameon=False, fontsize=7, ncol=2)
    b = fig.add_subplot(gs[-1, 1])
    im = b.imshow(res["layers"]["unexplained_recent"], cmap="RdBu", vmin=-2, vmax=2, interpolation="nearest")
    b.set_title(f"Unexplained greenness, {res['recent'][0]} to {res['target']}", fontsize=9)
    b.set_xticks([]); b.set_yticks([])
    fig.colorbar(im, ax=b, orientation="horizontal", fraction=0.05, pad=0.03, label="SD browner (-) / greener (+) than rain predicts")
    c = fig.add_subplot(gs[-1, 2])
    im = c.imshow(res["layers"]["r"], cmap="viridis", vmin=-0.2, vmax=0.8, interpolation="nearest")
    c.set_title(f"Rain sensitivity (r with SPI-{s}, lag {res['lag']})", fontsize=9)
    c.set_xticks([]); c.set_yticks([])
    fig.colorbar(im, ax=c, orientation="horizontal", fraction=0.05, pad=0.03)
    fig.suptitle(title, x=0.01, ha="left", fontsize=13, fontweight="bold", color=INK)
    fig.savefig(path, dpi=110, bbox_inches="tight")
    plt.close(fig)


def write_drought_outputs(out, res, findings, prof, write_raster):
    os.makedirs(out, exist_ok=True)
    for s, z in res["spi"].items():
        write_raster(os.path.join(out, f"spi_{s}.tif"), z, res["months"])
    for s, z in res["spei"].items():
        write_raster(os.path.join(out, f"spei_{s}.tif"), z, res["months"])
    if res["pet"] is not None:
        write_raster(os.path.join(out, "pet_mm.tif"), res["pet"], res["months"])
    lat = res["latest"]
    write_raster(os.path.join(out, "drought_class_latest.tif"),
                 np.stack([lat["z"], np.where(lat["cls"] == -99, np.nan, lat["cls"])]),
                 [f"SPI-{lat['scale']} {lat['month']}", f"class {lat['month']} (-3 extreme drought .. 3 extremely wet)"])
    keys = list(res["layers"])
    write_raster(os.path.join(out, "drought_events.tif"), np.stack([res["layers"][k] for k in keys]), keys)
    write_csv(os.path.join(out, "area_timeseries.csv"), res["area"])
    write_csv(os.path.join(out, "events.csv"), [{k: e[k] for k in ("start_month", "end_month", "peak_month",
                                                                     "duration", "magnitude", "intensity", "peak")}
                                                 for e in res["events"]])
    write_json(os.path.join(out, "report.json"), dict(info=res["info"], findings=findings,
                                                      latest_class_counts={CLASS_LABELS[c]: int(np.sum(lat["cls"] == c))
                                                                           for c in CLASS_LABELS},
                                                      events=res["events"]))
    plot_drought(os.path.join(out, "report.png"), res)


def write_greenness_outputs(out, res, findings, write_raster):
    os.makedirs(out, exist_ok=True)
    keys = list(res["layers"])
    write_raster(os.path.join(out, "greenness_layers.tif"), np.stack([res["layers"][k] for k in keys]), keys)
    write_csv(os.path.join(out, "class_link.csv"), res["class_rows"])
    write_csv(os.path.join(out, "lag_table.csv"), res["lag_rows"])
    srows = []
    for i, m in enumerate(res["months"]):
        row = {"month": m}
        for c in res["classes"]:
            nm = res["legend"].get(c, (f"class {c}",))[0]
            row[f"{nm} NDVI anom"] = res["series"][c]["ndvi"][i]
            row[f"{nm} SPI-{res['scale']}"] = res["series"][c][f"spi{res['scale']}"][i]
        srows.append(row)
    write_csv(os.path.join(out, "class_series.csv"), srows)
    write_json(os.path.join(out, "greenness.json"), dict(target=res["target"], recent=res["recent"],
                                                         spi_scale=res["scale"], lag=res["lag"],
                                                         findings=findings, classes=res["class_rows"],
                                                         diagnosis_codes=G.DIAG))
    plot_greenness(os.path.join(out, "greenness.png"), res)
