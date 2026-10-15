"""growth.png (footprint per area over time) and map.png (first-seen month over a recent image)."""

import numpy as np


def growth_png(path, months, foot, units, top=8):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import datetime as dt
    x = [dt.date(int(m[:4]), int(m[4:]), 15) for m in months]
    fig, ax = plt.subplots(figsize=(10, 5.5))
    for _, u in units.head(top).iterrows():
        name = u["place"] if isinstance(u.get("place"), str) else f"area {u.unit_id}"
        ax.plot(x, foot[:, u.unit_id], marker="o", ms=3, label=f"{name} (#{u.unit_id})")
    ax.set_ylabel("New shelter footprint (ha)")
    ax.set_title("Camp Growth Watch: new shelter area since the baseline year (dry-season months only)")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, loc="upper left")
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def _latest_rgb(scenes, grid, months):
    """True colour of the clearest scene in the last analysed month."""
    import os
    import re
    import rasterio
    from rasterio.warp import reproject, Resampling
    last = months[-1]
    best, best_clear = None, -1
    for f in scenes:
        m = re.search(r"(20\d{6})", os.path.basename(f))
        if m and m[1][:6] == last:
            with rasterio.open(f) as s:
                c = float(s.tags().get("TP_CLEAR_AOI", 0))
            if c > best_clear:
                best, best_clear = f, c
    with rasterio.open(best) as s:
        a = s.read([3, 2, 1]).astype("float32")
        if (s.crs, s.transform, (s.height, s.width)) != grid:
            dst = np.zeros((3,) + grid[2], "float32")
            reproject(a, dst, src_transform=s.transform, src_crs=s.crs, dst_transform=grid[1], dst_crs=grid[0],
                      resampling=Resampling.nearest)
            a = dst
    return np.clip(np.moveaxis(a, 0, -1) * 1e-4 * 3.0, 0, 1), best


def map_png(path, fs, months, units, grid, scenes):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import geopandas as gpd
    rgb, src = _latest_rgb(scenes, grid, months)
    h, w = fs.shape
    fig, ax = plt.subplots(1, 2, figsize=(18, 9 * h / w + 1.2))
    ax[0].imshow(rgb)
    ax[0].set_title(f"Sentinel-2 {months[-1][:4]}-{months[-1][4:]}")
    ax[1].imshow(rgb * 0.45)
    idx = np.full(fs.shape, np.nan)
    for k, m in enumerate(months):
        idx[fs == int(m)] = k
    im = ax[1].imshow(idx, cmap="plasma", vmin=0, vmax=len(months) - 1, interpolation="nearest")
    cb = fig.colorbar(im, ax=ax[1], fraction=0.035)
    ticks = list(range(0, len(months), max(len(months) // 8, 1)))
    cb.set_ticks(ticks)
    cb.set_ticklabels([f"{months[t][:4]}-{months[t][4:]}" for t in ticks])
    ax[1].set_title("Month new shelter pixels first appeared (and stayed)")
    inv = ~grid[1]
    g = gpd.GeoSeries(units.geometry.values, crs=units.crs).to_crs(grid[0])
    for (_, u), geom in zip(units.iterrows(), g):
        for poly in getattr(geom, "geoms", [geom]):
            xs, ys = poly.exterior.coords.xy
            c, r = inv * (np.asarray(xs), np.asarray(ys))
            ax[1].plot(c, r, color="cyan", lw=0.8)
        c0, r0 = inv * (geom.centroid.x, geom.centroid.y)
        name = u["place"] if isinstance(u.get("place"), str) else ""
        ax[1].text(c0, r0, f"#{u.unit_id} {name}\n{u.footprint_ha:.0f} ha", color="white", fontsize=7, ha="center")
    for a in ax:
        a.set_xticks([]), a.set_yticks([])
    fig.tight_layout()
    fig.savefig(path, dpi=100)
    plt.close(fig)
