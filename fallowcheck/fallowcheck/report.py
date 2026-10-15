"""map.png: peak greenness per season, field classes, and per-unit field-pattern ratio."""

import numpy as np


def map_png(path, peaks, years, lay, units, grid, info):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap
    from matplotlib.patches import Patch

    h, w = lay.shape
    ny = len(years)
    fig, ax = plt.subplots(1, ny + 2, figsize=(4.2 * (ny + 2), 4.2 * h / w + 1))
    for k, y in enumerate(years):
        ax[k].imshow(peaks[y], vmin=0.1, vmax=0.8, cmap="YlGn")
        ax[k].set_title(f"Peak NDVI {y}" + (" (target)" if y == info["target_year"] else ""))
    cmap = ListedColormap(["#f2f2f2", "#4daf4a", "#ff9f1c", "#c0392b", "#9e9e9e"])
    img = np.select([lay == 0, lay == 1, lay == 2, lay == 3], [0, 1, 2, 3], 4)
    ax[ny].imshow(img, cmap=cmap, vmin=0, vmax=4, interpolation="nearest")
    ax[ny].set_title(f"{info['target_year']} vs {min(info['baseline_years'])}-{max(info['baseline_years'])}")
    ax[ny].legend(handles=[Patch(color=c, label=l) for c, l in zip(
        ["#4daf4a", "#ff9f1c", "#c0392b", "#9e9e9e"], ["farmed as usual", "reduced", "not farmed", "no clear data"])],
        loc="lower left", fontsize=7)
    pct = np.full(lay.shape, np.nan)
    from rasterio.features import rasterize
    g = units.to_crs(grid[0])
    vals = [(geom, float(v)) for geom, v in zip(g.geometry, g.pattern_ratio) if np.isfinite(v)]
    if vals:
        pct = rasterize(vals, out_shape=lay.shape, transform=grid[1], fill=np.nan, dtype="float32")
    im = ax[ny + 1].imshow(pct, vmin=0.4, vmax=1.4, cmap="RdYlGn")
    fig.colorbar(im, ax=ax[ny + 1], fraction=0.04)
    ax[ny + 1].set_title(f"Field pattern ratio ({int(units.pattern_lost.sum())} of {len(units)} cells lost)")
    for a in ax:
        a.set_xticks([]), a.set_yticks([])
    t = info["target"]
    fig.suptitle(f"Abandoned Fields: {t['not_farmed_ha']:.0f} ha ({t['not_farmed_pct']:.0f} %) of normally farmed "
                 f"cropland not farmed in {info['target_year']}; normal years: "
                 + ", ".join(f"{y} {v['not_farmed_pct']:.0f} %" for y, v in info["normal_years"].items()))
    fig.tight_layout()
    fig.savefig(path, dpi=100)
    plt.close(fig)
