"""Pixel rules for fields left unplanted. Pure numpy.

For each season, a pixel's peak greenness is the 90th percentile of its clear
NDVI values (robust to a single noisy image). A field counts as farmed in normal
years when the median peak over the baseline seasons is high; it counts as not
farmed in the target season when the peak stayed low and fell well below that
median. The same test, run on each baseline season against the others, gives
the rate of "not farmed" seen in ordinary years: the false-alarm floor.
"""

import warnings

import numpy as np

SCL_CLEAR = (4, 5)  # vegetation, bare soil: fields only; water, dark areas, clouds and shadows are dropped

DEFAULTS = dict(
    min_base=0.40,     # median baseline peak NDVI for "farmed in normal years"
    max_target=0.30,   # target peak NDVI below this ...
    min_drop=0.15,     # ... and at least this far below the baseline median -> not farmed
    min_obs=3,         # clear observations needed in the target season
    pctl=90,           # percentile used as the season peak
)


def ndvi(dn, scl, scale=1e-4, offset=0.0):
    """Sentinel-2 DN stack (blue, green, red, nir, ...) + SCL -> NDVI with NaN where not clear."""
    x = dn[[2, 3]].astype("float32") * scale + offset
    with np.errstate(all="ignore"):
        v = (x[1] - x[0]) / (x[1] + x[0])
    v[~np.isin(scl, SCL_CLEAR) | (dn[0] == 0)] = np.nan
    return v


def season_peak(stack, pctl=90):
    """(n_images, r, c) NDVI -> (peak, n_clear)."""
    n = np.isfinite(stack).sum(0).astype("int16")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanpercentile(stack, pctl, axis=0).astype("float32"), n


def classify(target, baseline, n_target=None, p=None):
    """target: (r, c) peak; baseline: (Y, r, c) peaks of normal seasons.

    Returns uint8 classes: 0 not farmed in baseline / not cropland, 1 farmed as usual,
    2 reduced (dropped by min_drop but still green), 3 not farmed, 255 not enough data."""
    p = {**DEFAULTS, **(p or {})}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        base = np.nanmedian(baseline, 0)
    farmed = base >= p["min_base"]
    drop = base - target
    cls = np.zeros(target.shape, "uint8")
    cls[farmed] = 1
    cls[farmed & (drop >= p["min_drop"])] = 2
    cls[farmed & (drop >= p["min_drop"]) & (target < p["max_target"])] = 3
    bad = ~np.isfinite(target) | ~np.isfinite(base)
    if n_target is not None:
        bad |= n_target < p["min_obs"]
    cls[bad & (farmed | ~np.isfinite(base))] = 255
    return cls


def leave_one_out(peaks, n_obs=None, p=None):
    """Classes for each baseline season against the other baseline seasons: what ordinary years look like."""
    out = []
    for y in range(len(peaks)):
        others = np.delete(peaks, y, axis=0)
        out.append(classify(peaks[y], others, None if n_obs is None else n_obs[y], p))
    return out


def unit_table(unit_ids, n_units, cls, crop=None, px_ha=0.01):
    """Per-unit hectares: farmed_base, as_usual, reduced, not_farmed, no_data; index = unit id."""
    m = unit_ids > 0
    if crop is not None:
        m &= crop
    def ha(code):
        return np.bincount(unit_ids[m & (cls == code)], minlength=n_units + 1)[:n_units + 1] * px_ha
    t = dict(as_usual_ha=ha(1), reduced_ha=ha(2), not_farmed_ha=ha(3), no_data_ha=ha(255))
    t["farmed_base_ha"] = t["as_usual_ha"] + t["reduced_ha"] + t["not_farmed_ha"] + t["no_data_ha"]
    seen = t["farmed_base_ha"] - t["no_data_ha"]
    with np.errstate(all="ignore"):
        t["not_farmed_pct"] = np.where(seen > 0, 100 * t["not_farmed_ha"] / seen, np.nan)
        t["reduced_pct"] = np.where(seen > 0, 100 * t["reduced_ha"] / seen, np.nan)
        t["observed_pct"] = np.where(t["farmed_base_ha"] > 0, 100 * seen / t["farmed_base_ha"], np.nan)
    return t


def field_contrast(peak, k=5):
    """|peak - local k x k mean|: high where neighbouring fields differ (crops, fallow, sowing dates),
    low where one cover spreads over everything (weeds or grass on unmanaged land)."""
    x = np.where(np.isfinite(peak), peak, np.nanmean(peak)).astype("float32")
    pad = np.pad(x, k // 2, mode="edge")
    c = np.cumsum(np.cumsum(pad, 0), 1)
    c = np.pad(c, ((1, 0), (1, 0)))
    r, cc = x.shape
    loc = (c[k:k + r, k:k + cc] - c[:r, k:k + cc] - c[k:k + r, :cc] + c[:r, :cc]) / (k * k)
    out = np.abs(x - loc)
    out[~np.isfinite(peak)] = np.nan
    return out


def unit_mean(unit_ids, n_units, img, mask=None):
    m = (unit_ids > 0) & np.isfinite(img)
    if mask is not None:
        m &= mask
    s = np.bincount(unit_ids[m], weights=img[m], minlength=n_units + 1)[:n_units + 1]
    c = np.bincount(unit_ids[m], minlength=n_units + 1)[:n_units + 1]
    with np.errstate(all="ignore"):
        return s / c


def pattern_ratios(contrasts, target_idx):
    """Per-unit contrast of the target season divided by the median of the other seasons,
    plus the same ratio for each other season against the rest (normal-year spread).
    contrasts: (Y, n_units + 1) unit means, target last."""
    def ratio(y, others):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            return contrasts[y] / np.nanmedian(contrasts[others], 0)
    Y = len(contrasts)
    base = [y for y in range(Y) if y != target_idx]
    target = ratio(target_idx, base)
    normal = np.stack([ratio(y, [b for b in base if b != y]) for y in base])
    return target, normal
