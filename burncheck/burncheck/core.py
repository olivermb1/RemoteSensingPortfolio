"""Pixel and per-settlement rules. Pure numpy (scipy optional), so the CLI, the
QGIS script and the tests all share exactly the same logic.

Arrays are reflectance stacks shaped (6, rows, cols) in the band order
blue, green, red, nir, swir1, swir2, with NaN where a pixel was not observed.
"""

import numpy as np

BANDS = ["blue", "green", "red", "nir", "swir1", "swir2"]
SCL_CLEAR = (2, 4, 5, 6, 7)  # dark area, vegetation, bare soil, water, unclassified (low-probability cloud)

DEFAULTS = dict(
    t_dnbr=0.10,          # dNBR above the local building background
    t_dark=0.05,          # and the pixel got at least 5 % darker (ash, charred roofs, removed shelters)
    max_mndwi=0.0,        # and is not water after the event (MNDWI <= 0): flooded pits and ponds also darken
    bg_block=100,         # local background: median building dNBR in 100 px (1 km at 10 m) blocks
    min_clear_pct=50.0,   # a unit needs half of its building pixels seen clear on both dates
    likely_pct=20.0, likely_px=8,      # >= 20 % of building pixels and >= 8 px (0.08 ha) -> likely burned
    possible_pct=7.0, possible_px=4,   # >= 7 % and >= 4 px -> possible
    ring_pct=20.0,        # >= 20 % of the open land around the unit burned -> landscape fire nearby
)

CLASSES = {0: "no sign", 1: "possible", 2: "likely burned", 9: "not enough clear data"}


def composite(stacks):
    """Median of a list of (6, r, c) reflectance stacks (NaN = not seen). Returns (median, n_clear)."""
    a = np.stack(stacks).astype("float32")
    n = np.isfinite(a[:, 0]).sum(0)
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            med = np.nanmedian(a, 0)
    return med, n.astype("int16")


def scl_to_nan(dn, scl, scale=1e-4, offset=0.0):
    """Sentinel-2 L2A DN stack + SCL -> reflectance with clouds, shadows, snow and nodata as NaN."""
    x = dn.astype("float32") * scale + offset
    bad = ~np.isin(scl, SCL_CLEAR) | (dn[0] == 0)
    x[:, bad] = np.nan
    return x


def nbr(x):
    with np.errstate(all="ignore"):
        return (x[3] - x[5]) / (x[3] + x[5])


def brightness(x):
    """Mean of visible + SWIR reflectance (NIR left out so greening does not mask darkening)."""
    return np.mean(x[[0, 1, 2, 4, 5]], axis=0)


def local_background(d, mask, block=100):
    """Smooth local median of d over pixels in mask, in block x block cells.

    Settlements green up or dry out with the season as a whole; burned
    neighbourhoods stand out against that. Cells with too few masked pixels
    take the overall median. The block grid is smoothed with a 3x3 mean and
    resampled bilinearly so neighbouring cells do not step."""
    r, c = d.shape
    ok = mask & np.isfinite(d)
    overall = float(np.nanmedian(d[ok])) if ok.any() else 0.0
    nr, nc = -(-r // block), -(-c // block)
    grid = np.full((nr, nc), overall, "float32")
    for i in range(nr):
        for j in range(nc):
            sub = d[i * block:(i + 1) * block, j * block:(j + 1) * block]
            m = ok[i * block:(i + 1) * block, j * block:(j + 1) * block]
            if m.sum() >= 50:
                grid[i, j] = np.median(sub[m])
    pad = np.pad(grid, 1, mode="edge")
    grid = sum(pad[a:a + nr, b:b + nc] for a in range(3) for b in range(3)) / 9.0
    # bilinear upsample of cell centres to pixels
    yi = np.clip((np.arange(r) + 0.5) / block - 0.5, 0, nr - 1)
    xi = np.clip((np.arange(c) + 0.5) / block - 0.5, 0, nc - 1)
    y0, x0 = np.floor(yi).astype(int), np.floor(xi).astype(int)
    y1, x1 = np.minimum(y0 + 1, nr - 1), np.minimum(x0 + 1, nc - 1)
    fy, fx = (yi - y0)[:, None], (xi - x0)[None, :]
    g = grid
    return ((g[y0][:, x0] * (1 - fx) + g[y0][:, x1] * fx) * (1 - fy)
            + (g[y1][:, x0] * (1 - fx) + g[y1][:, x1] * fx) * fy).astype("float32")


def burn_layers(before, after, buildings, p=None):
    """Per-pixel layers. buildings: bool mask of building pixels.

    Returns dict with dnbr, background, anomaly, darkening, clear, burned
    (burned is evaluated on every clear pixel; callers restrict it to
    buildings or to open land as needed)."""
    p = {**DEFAULTS, **(p or {})}
    clear = np.isfinite(before).all(0) & np.isfinite(after).all(0)
    dnbr = nbr(before) - nbr(after)
    bg = local_background(dnbr, buildings & clear, p["bg_block"])
    anom = dnbr - bg
    with np.errstate(all="ignore"):
        bb, ba = brightness(before), brightness(after)
        dark = (ba - bb) / bb
        mndwi = (after[1] - after[4]) / (after[1] + after[4])
    dry = mndwi <= p["max_mndwi"]
    burned = clear & dry & (anom >= p["t_dnbr"]) & (dark <= -p["t_dark"])
    # open land: landscape fire uses raw dNBR (fields and bush have their own background)
    burned_open = clear & dry & (dnbr - np.nanmedian(dnbr[clear & ~buildings]) >= p["t_dnbr"]) & (dark <= -p["t_dark"]) \
        if (clear & ~buildings).any() else np.zeros_like(clear)
    return dict(dnbr=dnbr, background=bg, anomaly=anom, darkening=dark, clear=clear,
                burned=burned, burned_open=burned_open)


def unit_stats(unit_ids, n_units, buildings, layers, ring_ids=None):
    """Per-unit counts. unit_ids: int raster, 0 = outside, 1..n_units = unit. Returns dict of arrays (index = unit id)."""
    def count(ids, m):
        return np.bincount(ids[m].ravel(), minlength=n_units + 1)[:n_units + 1]
    inside = unit_ids > 0
    bld = inside & buildings
    out = dict(
        bld_px=count(unit_ids, bld),
        bld_clear_px=count(unit_ids, bld & layers["clear"]),
        burned_px=count(unit_ids, bld & layers["burned"]),
        unit_px=count(unit_ids, inside),
        unit_burned_px=count(unit_ids, inside & layers["clear"] & layers["burned"]),
    )
    a = np.where(bld & layers["clear"], layers["anomaly"], np.nan)
    s = np.bincount(unit_ids[np.isfinite(a)], weights=a[np.isfinite(a)], minlength=n_units + 1)[:n_units + 1]
    with np.errstate(all="ignore"):
        out["mean_anomaly"] = s / out["bld_clear_px"]
    if ring_ids is not None:
        open_ = (ring_ids > 0) & ~buildings & layers["clear"]
        out["ring_clear_px"] = count(ring_ids, open_)
        out["ring_burned_px"] = count(ring_ids, open_ & layers["burned_open"])
    return out


def classify(stats, p=None):
    """Class code per unit (index 0 unused) plus burned and clear percentages."""
    p = {**DEFAULTS, **(p or {})}
    with np.errstate(all="ignore"):
        clear_pct = np.where(stats["bld_px"] > 0, 100.0 * stats["bld_clear_px"] / stats["bld_px"], 0.0)
        burned_pct = np.where(stats["bld_clear_px"] > 0, 100.0 * stats["burned_px"] / stats["bld_clear_px"], 0.0)
        ring_pct = (np.where(stats["ring_clear_px"] > 0, 100.0 * stats["ring_burned_px"] / stats["ring_clear_px"], 0.0)
                    if "ring_clear_px" in stats else np.zeros_like(clear_pct))
    cls = np.zeros(len(clear_pct), "int16")
    cls[(burned_pct >= p["possible_pct"]) & (stats["burned_px"] >= p["possible_px"])] = 1
    cls[(burned_pct >= p["likely_pct"]) & (stats["burned_px"] >= p["likely_px"])] = 2
    cls[clear_pct < p["min_clear_pct"]] = 9
    landscape = ring_pct >= p["ring_pct"]
    return cls, burned_pct, clear_pct, ring_pct, landscape
