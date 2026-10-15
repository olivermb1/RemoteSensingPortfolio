"""Pixel rules for new shelter areas. Pure numpy (scipy optional for labelling).

Signal: plastic sheeting, tents and metal roofs are grey-white; the Sahelian
and savanna soils around them are red. A pixel filling up with shelters gets a
higher blue/red ratio and a brighter blue band than the same calendar month in a
baseline year. Comparing like months removes most of the seasonal colour change
of soil; the area-wide median change is also subtracted each month.
"""

import numpy as np

SCL_CLEAR = (2, 4, 5, 6, 7)

DEFAULTS = dict(
    t_ratio=0.07,        # blue/red rise above the same month of the baseline year
    t_blue=0.015,        # and blue reflectance rise
    max_ndvi=0.30,       # ignore green pixels (crops, grass in the rains)
    min_area_ha=5.0,     # automatic areas smaller than this are dropped
    join_px=2,           # pixels this far apart belong to the same area
    persist=0.5,         # first seen = first month after which the pixel is shelter in >= 50 % of months
)
DRY_MONTHS = (11, 12, 1, 2, 3, 4, 5)  # Sahel default; set per region


def indices(dn, scl, scale=1e-4, offset=0.0):
    """One Sentinel-2 scene (DN stack blue, green, red, nir, ... + SCL) -> (ratio, blue, ndvi), NaN where not clear."""
    x = dn.astype("float32") * scale + offset
    bad = ~np.isin(scl, SCL_CLEAR) | (dn[0] == 0)
    with np.errstate(all="ignore"):
        ratio = x[0] / x[2]
        ndvi = (x[3] - x[2]) / (x[3] + x[2])
    out = np.stack([ratio, x[0], ndvi]).astype("float32")
    out[:, bad] = np.nan
    return out


def median(stack):
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmedian(stack, 0)


def shelter_month(cur, base, p=None):
    """cur, base: (3, r, c) monthly composites (ratio, blue, ndvi). Returns float array 1/0, NaN = not seen."""
    p = {**DEFAULTS, **(p or {})}
    dr = cur[0] - base[0]
    db = cur[1] - base[1]
    seen = np.isfinite(dr) & np.isfinite(db)
    if seen.any():
        dr = dr - np.median(dr[seen])
        db = db - np.median(db[seen])
    s = (dr >= p["t_ratio"]) & (db >= p["t_blue"]) & (cur[2] <= p["max_ndvi"])
    return np.where(seen, s, np.nan).astype("float32")


def smooth(S):
    """Majority of each month with its neighbouring months (only months that saw the pixel count)."""
    out = np.full_like(S, np.nan)
    for t in range(len(S)):
        w = S[max(t - 1, 0):t + 2]
        n = np.isfinite(w).sum(0)
        with np.errstate(all="ignore"):
            frac = np.nansum(w, 0) / n
        out[t] = np.where(np.isfinite(S[t]), frac > 0.5, np.nan)
    return out


def first_seen(P, persist=0.5):
    """Index of the first month that is shelter and stays shelter in >= persist of the later months; -1 = never."""
    first = np.full(P.shape[1:], -1, "int16")
    for t in range(len(P)):
        with np.errstate(all="ignore"):
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                later = np.nanmean(P[t:], 0)
        m = (first < 0) & (P[t] == 1) & (later >= persist)
        first[m] = t
    return first


def label(mask, join_px=2):
    """Connected areas after growing by join_px pixels; labels are returned on the original mask only."""
    g = mask.copy()
    for _ in range(join_px):
        h = g.copy()
        h[1:] |= g[:-1]
        h[:-1] |= g[1:]
        h[:, 1:] |= g[:, :-1]
        h[:, :-1] |= g[:, 1:]
        g = h
    try:
        from scipy import ndimage
        lab, n = ndimage.label(g, structure=np.ones((3, 3)))
    except ImportError:
        lab, n = _label_py(g)
    return np.where(mask, lab, 0), n


def _label_py(mask):
    """8-connected labelling without scipy (union-find over pixels; fine for a few million pixels)."""
    r, c = mask.shape
    idx = np.flatnonzero(mask.ravel())
    parent = {int(i): int(i) for i in idx}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for i in idx:
        y, x = divmod(int(i), c)
        for dy, dx in ((-1, -1), (-1, 0), (-1, 1), (0, -1)):
            yy, xx = y + dy, x + dx
            if 0 <= yy < r and 0 <= xx < c and mask[yy, xx]:
                a, b = find(int(i)), find(yy * c + xx)
                if a != b:
                    parent[max(a, b)] = min(a, b)
    lab = np.zeros(r * c, "int32")
    roots = {}
    for i in idx:
        lab[i] = roots.setdefault(find(int(i)), len(roots) + 1)
    return lab.reshape(r, c), len(roots)


def area_series(P, unit_ids, n_units, first=None, px_ha=0.01):
    """Hectares per unit per month (rows = months, cols = unit 0..n). With first given, a pixel counts
    from its first-seen month on (cumulative footprint); otherwise the month's own shelter pixels."""
    T = len(P)
    out = np.zeros((T, n_units + 1))
    obs = np.zeros((T, n_units + 1))
    for t in range(T):
        m = (first >= 0) & (first <= t) if first is not None else (P[t] == 1)
        out[t] = np.bincount(unit_ids[m], minlength=n_units + 1)[:n_units + 1] * px_ha
        seen = np.isfinite(P[t]) & (unit_ids > 0)
        tot = np.bincount(unit_ids[unit_ids > 0], minlength=n_units + 1)[:n_units + 1]
        with np.errstate(all="ignore"):
            obs[t] = np.bincount(unit_ids[seen], minlength=n_units + 1)[:n_units + 1] / tot * 100
    return out, obs
