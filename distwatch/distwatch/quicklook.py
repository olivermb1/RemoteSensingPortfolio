"""Optional quicklook PNG of a run (needs matplotlib)."""

import numpy as np

COLORS = {1: (0.84, 0.15, 0.16), 2: (0.55, 0.55, 0.55), 3: (0.95, 0.75, 0.3)}
LABELS = {1: "new this run", 2: "reported earlier", 3: "below patch size"}


def draw(path, tiles, feats, names, io, title, new_points=()):
    """tiles: {tile: (map array, grid)}. Plots in lon/lat using each tile's corner coordinates."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    fig, ax = plt.subplots(figsize=(11, 6), dpi=110)
    exts = []
    for t, (arr, grid) in tiles.items():
        rgba = np.zeros(arr.shape + (4,))
        for v, c in COLORS.items():
            rgba[arr == v] = c + (1.0,)
        rgba[arr == 255] = (0.2, 0.2, 0.2, 0.25)
        lon, lat = io.lonlat(grid, [-0.5, grid.height - 0.5], [-0.5, grid.width - 0.5])
        ext = (lon[0], lon[1], lat[1], lat[0])
        exts.append(ext)
        ax.imshow(rgba, extent=ext, interpolation="nearest", zorder=2)
        ax.plot([ext[0], ext[1], ext[1], ext[0], ext[0]], [ext[2], ext[2], ext[3], ext[3], ext[2]],
                color="0.6", lw=0.8, ls="--", zorder=1)
        ax.text(ext[0], ext[3], f" {t}", va="bottom", fontsize=8, color="0.4")
    e = np.array(exts)
    pad = 0.02 * (e[:, 1].max() - e[:, 0].min())
    x0, x1, y0, y1 = e[:, 0].min() - pad, e[:, 1].max() + pad, e[:, 2].min() - pad, e[:, 3].max() + pad
    for f, n in zip(feats, names):
        g = f["geometry"]
        polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        for p in polys:
            ring = np.array(p[0])
            ax.plot(ring[:, 0], ring[:, 1], color="#1f5f8b", lw=1.2, zorder=3)
        lx, ly = ring[:, 0].mean(), ring[:, 1].min()
        if x0 < lx < x1 and y0 < ly < y1:
            ax.text(lx, ly, n, fontsize=7, color="#1f5f8b", ha="center", va="top", zorder=4)
    if len(new_points):
        pts = np.array(new_points)
        ax.scatter(pts[:, 0], pts[:, 1], s=160, facecolors="none", edgecolors=COLORS[1], lw=1.2, zorder=5)
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.legend(handles=[Patch(color=COLORS[k], label=LABELS[k]) for k in COLORS], loc="upper left",
              bbox_to_anchor=(1.01, 1), fontsize=8, title="circles: new patches", title_fontsize=8)
    ax.set_title(title, fontsize=10)
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    ax.set_aspect(1 / np.cos(np.radians(np.mean(ax.get_ylim()))))
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
