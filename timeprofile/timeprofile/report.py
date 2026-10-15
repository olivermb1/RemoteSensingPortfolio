"""Outputs: series.csv, seasons.csv, run.json, and charts (matplotlib, optional)."""

import csv
import datetime as dt
import json
import os

from . import smooth
from .extract import FIELDS

# Categorical palette, fixed order (validated for colour-vision deficiency on adjacent pairs)
PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
INK, INK2, GRID = "#1f1f1e", "#6b6a64", "#e6e5e0"


def marker_for(sensor):
    s = sensor.upper()
    if s.startswith(("HLS.L30", "LC", "LT", "LE", "LANDSAT")):
        return "^"
    if s.startswith(("S2", "HLS.S30")):
        return "o"
    return "s"


def series(rows, feature, index, status="clear"):
    rs = [r for r in rows if r["feature"] == feature and r["index"] == index and r["status"] == status]
    return [dt.date.fromisoformat(r["date"]) for r in rs], [r["value"] for r in rs], rs


def postprocess(rows, spike_threshold=0.1, lam=1000.0, max_gap=60, season_start=1):
    """Flag spikes in place; return {(feature, index): {'curve': segments, 'seasons': [...]}}."""
    out = {}
    keys = sorted({(r["feature"], r["index"]) for r in rows})
    for k in keys:
        d, v, rs = series(rows, *k)
        spikes = set(smooth.flag_spikes(d, v, spike_threshold)) if spike_threshold else set()
        for i in spikes:
            rs[i]["flag"] = "spike"
        keep = [i for i in range(len(v)) if i not in spikes]
        dk, vk = [d[i] for i in keep], [v[i] for i in keep]
        curve = smooth.whittaker(dk, vk, lam, max_gap) if lam else []
        out[k] = {"curve": curve, "seasons": smooth.seasons(dk, vk, curve, season_start)}
    return out


def write_csv(path, rows, fields=FIELDS):
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: (round(v, 5) if isinstance(v, float) else v) for k, v in r.items()})


def read_csv(path):
    rows = []
    with open(path, newline="") as fh:
        for r in csv.DictReader(fh):
            for k in ("value", "median", "std", "p10", "p90", "clear_pct"):
                r[k] = float(r[k]) if r.get(k) not in (None, "") else None
            for k in ("year", "doy", "n_pixels", "n_valid", "n_clear"):
                if r.get(k) not in (None, ""):
                    r[k] = int(r[k])
            rows.append(r)
    return rows


def write_seasons(path, post):
    fields = ["feature", "index", "season", "n_clear", "first", "last", "mean", "peak", "peak_date",
              "low", "low_date", "from"]
    rows = [{"feature": f, "index": i, **s} for (f, i), p in sorted(post.items()) for s in p["seasons"]]
    write_csv(path, rows, fields)
    return rows


def _style(ax):
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(INK2)
    ax.tick_params(colors=INK2, labelsize=8)


def chart_time(path, rows, post, title=None, max_features=8):
    """One panel per index; one colour per feature; dots = clear observations
    (marker by sensor, hollow = flagged spike), line = smooth curve."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    feats = list(dict.fromkeys(r["feature"] for r in rows))[:max_features]
    idxs = list(dict.fromkeys(r["index"] for r in rows))
    fig, axes = plt.subplots(len(idxs), 1, figsize=(10, 2.9 * len(idxs) + 0.9), sharex=True, squeeze=False)
    sensors = set()
    for ax, idx in zip(axes[:, 0], idxs):
        _style(ax)
        for fi, f in enumerate(feats):
            col = PALETTE[fi]
            d, v, rs = series(rows, f, idx)
            for seg_d, seg_v in post.get((f, idx), {}).get("curve", []):
                ax.plot(seg_d, seg_v, color=col, linewidth=2, zorder=2)
            for dd, vv, r in zip(d, v, rs):
                m = marker_for(r["sensor"])
                sensors.add(m)
                spike = r.get("flag") == "spike"
                ax.scatter([dd], [vv], s=26, marker=m, zorder=3, linewidths=1.2,
                           facecolors="white" if spike else col, edgecolors=col if spike else "white")
        ax.set_ylabel(idx, color=INK, fontsize=10)
    ax = axes[-1, 0]
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=4, maxticks=10))
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(ax.xaxis.get_major_locator()))
    handles = [Line2D([], [], color=PALETTE[i], linewidth=2, marker="o", markersize=5, label=f)
               for i, f in enumerate(feats)]
    names = {"o": "Sentinel-2", "^": "Landsat", "s": "other"}
    handles += [Line2D([], [], color=INK2, linestyle="", marker=m, markersize=5, label=names[m])
                for m in ("o", "^", "s") if m in sensors]
    handles.append(Line2D([], [], color=INK2, linestyle="", marker="o", markerfacecolor="white",
                          markersize=5, label="flagged spike"))
    ncol = len(handles) if len(handles) <= 7 else (len(handles) + 1) // 2
    nrows = (len(handles) + ncol - 1) // ncol
    head = 0.2 * nrows + 0.25 * (title is not None) - 0.15  # inches above the panels
    H = fig.get_figheight()
    if title:
        fig.suptitle(title, x=0.01, y=1 - 0.08 / H, ha="left", va="top", fontsize=11, color=INK)
    fig.legend(handles=handles, loc="upper left", ncol=ncol, frameon=False, fontsize=8,
               bbox_to_anchor=(0.005, 1 - (0.12 + 0.3 * (title is not None)) / H))
    fig.tight_layout(rect=(0, 0, 1, 1 - head / H))
    fig.savefig(path, dpi=130)
    plt.close(fig)


def chart_seasons(path, rows, post, index, season_start=1, max_features=8, max_seasons=8):
    """Small multiples, one per feature: each season as its own line against the
    month of the season, so years can be compared."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    feats = list(dict.fromkeys(r["feature"] for r in rows if r["index"] == index))[:max_features]
    seas = sorted({smooth.season_of(dt.date.fromisoformat(r["date"]), season_start)
                   for r in rows if r["index"] == index and r["status"] == "clear"})
    shown = seas[-max_seasons:]
    colour = {s: PALETTE[i] for i, s in enumerate(shown)}
    n = len(feats)
    ncol = 1 if n == 1 else 2
    nrow = (n + ncol - 1) // ncol
    fig, axes = plt.subplots(nrow, ncol, figsize=(5.2 * ncol, 2.8 * nrow + 0.8), sharex=True, sharey=True,
                             squeeze=False)

    def x_of(d):
        s0 = dt.date(d.year if d.month >= season_start else d.year - 1, season_start, 1)
        return (d - s0).days

    for k, f in enumerate(feats):
        ax = axes[k // ncol, k % ncol]
        _style(ax)
        ax.set_title(f, fontsize=9, color=INK, loc="left")
        d, v, rs = series(rows, f, index)
        for seg_d, seg_v in post.get((f, index), {}).get("curve", []):
            by = {}
            for dd, vv in zip(seg_d, seg_v):
                by.setdefault(smooth.season_of(dd, season_start), ([], []))
                by[smooth.season_of(dd, season_start)][0].append(x_of(dd))
                by[smooth.season_of(dd, season_start)][1].append(vv)
            for s, (xs, ys) in by.items():
                ax.plot(xs, ys, color=colour.get(s, "#c3c2b7"), linewidth=2, zorder=2 if s in colour else 1)
        for dd, vv, r in zip(d, v, rs):
            s = smooth.season_of(dd, season_start)
            c = colour.get(s, "#c3c2b7")
            spike = r.get("flag") == "spike"
            ax.scatter([x_of(dd)], [vv], s=14, zorder=3, facecolors="white" if spike else c,
                       edgecolors=c if spike else "white", linewidths=0.8)
    for k in range(n, nrow * ncol):
        axes[k // ncol, k % ncol].set_visible(False)
    months = [(dt.date(2001 if m >= season_start else 2002, m, 1) - dt.date(2001, season_start, 1)).days
              for m in range(1, 13)]
    ticks = sorted(zip(months, ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"]))
    for ax in axes[-1]:
        ax.set_xticks([t[0] for t in ticks])
        ax.set_xticklabels([t[1] for t in ticks])
        ax.set_xlim(0, 366)
    for row in axes:
        row[0].set_ylabel(index, color=INK, fontsize=9)
    handles = [Line2D([], [], color=colour[s], linewidth=2, label=s) for s in shown]
    if len(seas) > len(shown):
        handles.append(Line2D([], [], color="#c3c2b7", linewidth=2, label="earlier"))
    fig.legend(handles=handles, loc="upper center", ncol=min(len(handles), 9), frameon=False, fontsize=8)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(path, dpi=130)
    plt.close(fig)


def write_run(path, info):
    with open(path, "w") as fh:
        json.dump(info, fh, indent=2, default=str)


def outputs(out_dir, rows, notes, settings, season_start=1, lam=1000.0, spike_threshold=0.1, charts=True,
            title=None):
    """Write everything for one run. Returns a dict of paths written."""
    os.makedirs(out_dir, exist_ok=True)
    post = postprocess(rows, spike_threshold, lam, season_start=season_start)
    paths = {"series": os.path.join(out_dir, "series.csv"), "seasons": os.path.join(out_dir, "seasons.csv"),
             "run": os.path.join(out_dir, "run.json")}
    write_csv(paths["series"], rows)
    seas = write_seasons(paths["seasons"], post)
    if charts and any(r["status"] == "clear" for r in rows):
        try:
            paths["chart"] = os.path.join(out_dir, "chart.png")
            chart_time(paths["chart"], rows, post, title)
            for idx in dict.fromkeys(r["index"] for r in rows):
                p = os.path.join(out_dir, f"seasons_{idx}.png")
                chart_seasons(p, rows, post, idx, season_start)
                paths[f"seasons_{idx}"] = p
        except ImportError:
            notes.append("matplotlib not installed: no chart images (the CSVs are complete)")
            paths.pop("chart", None)
    clear = sum(r["status"] == "clear" for r in rows)
    write_run(paths["run"], {"settings": settings, "notes": notes, "observations": len(rows), "clear": clear,
                             "spikes_flagged": sum(r.get("flag") == "spike" for r in rows), "seasons": seas,
                             "outputs": paths})
    return paths
