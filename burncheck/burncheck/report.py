"""Overview map and before/after picture chips (matplotlib)."""

import numpy as np

COLORS = {"likely burned": "#c0392b", "possible": "#e67e22", "no sign": "#7f8c8d", "not enough clear data": "#2980b9"}


def _rgb(x, gain=3.3):
    with np.errstate(all="ignore"):
        return np.clip(np.nan_to_num(np.dstack([x[2], x[1], x[0]]) * gain), 0, 1)


def _pix(geom, grid, crs):
    """Unit geometry -> list of (cols, rows) rings in pixel coordinates of the grid."""
    import geopandas as gpd
    g = gpd.GeoSeries([geom], crs=crs).to_crs(grid[0]).iloc[0]
    inv = ~grid[1]
    out = []
    for poly in getattr(g, "geoms", [g]):
        xs, ys = poly.exterior.coords.xy
        c, r = inv * (np.asarray(xs), np.asarray(ys))
        out.append((c, r))
    return out


def map_png(path, B, A, lay, units, grid, crs, info):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    h, w = lay.shape
    fig, ax = plt.subplots(1, 2, figsize=(16, 8 * h / w + 1))
    ax[0].imshow(_rgb(A))
    ax[0].set_title(f"After ({info['after_dates'][0]} .. {info['after_dates'][-1]}), settlement units by class")
    for _, u in units.iterrows():
        for c, r in _pix(u.geometry, grid, crs):
            col = COLORS[u["class"]]
            if u["class"] in ("likely burned", "possible"):
                ax[0].fill(c, r, color=col, alpha=0.45, lw=0)
            ax[0].plot(c, r, color=col, lw=0.6 if u["class"] == "no sign" else 1.2)
    ax[0].legend(handles=[Patch(color=v, label=f"{k} ({info['unit_counts'][k]})") for k, v in COLORS.items()],
                 loc="lower left", fontsize=8)
    base = _rgb(B) * 0.55
    over = base.copy()
    over[lay == 1] = [0.85, 0.85, 0.85]
    over[lay == 3] = [0.9, 0.1, 0.1]
    over[lay == 2] = [1.0, 0.75, 0.0]
    ax[1].imshow(over)
    ax[1].set_title("Pixels: building no change (grey), building burned (red), open land burned (amber)")
    for a in ax:
        a.set_xticks([]), a.set_yticks([])
    fig.suptitle(f"Burned Settlement Check: {info['unit_counts']['likely burned']} likely burned, "
                 f"{info['unit_counts']['possible']} possible, {info['burned_ha_total']:.1f} ha of building pixels burned",
                 fontsize=12)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def chips_png(path, B, A, anom, order, grid, crs, n=12, pad=25):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    top = order[order["class"].isin(["likely burned", "possible"])].head(n)
    if len(top) == 0:
        top = order.head(min(n, 4))
    fig, ax = plt.subplots(3, len(top), figsize=(2.6 * len(top), 8.2), squeeze=False)
    for k, (_, u) in enumerate(top.iterrows()):
        rings = _pix(u.geometry, grid, crs)
        c0 = int(max(min(r[0].min() for r in rings) - pad, 0))
        c1 = int(min(max(r[0].max() for r in rings) + pad, A.shape[2]))
        r0 = int(max(min(r[1].min() for r in rings) - pad, 0))
        r1 = int(min(max(r[1].max() for r in rings) + pad, A.shape[1]))
        for row, img in enumerate([_rgb(B[:, r0:r1, c0:c1]), _rgb(A[:, r0:r1, c0:c1]), anom[r0:r1, c0:c1]]):
            a = ax[row, k]
            if row < 2:
                a.imshow(img)
            else:
                a.imshow(img, vmin=-0.2, vmax=0.3, cmap="RdYlGn_r")
            for c, r in rings:
                a.plot(c - c0, r - r0, color="cyan" if row < 2 else "k", lw=0.8)
            a.set_xticks([]), a.set_yticks([])
        name = u["place"] if isinstance(u["place"], str) else f"unit {u.unit_id}"
        ax[0, k].set_title(f"{name}\n#{u.unit_id} {u['class']}\n{u.burned_pct:.0f}% of bld px", fontsize=8)
    ax[0, 0].set_ylabel("before")
    ax[1, 0].set_ylabel("after")
    ax[2, 0].set_ylabel("dNBR anomaly")
    fig.tight_layout()
    fig.savefig(path, dpi=100)
    plt.close(fig)
