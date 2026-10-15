"""Measure how far an ECOSTRESS image sits from where it should be.

The idea follows NASA JPL's ECOSTRESS geolocation tutorials, which line LST
up against a water mask: lake shores and coastlines show up as sharp
temperature edges, and a water mask says where those edges really are.
Here both images are turned into smoothed edge-strength images and compared
with a masked normalised cross-correlation (Padfield 2012), so clouds and
no-data are left out properly and it does not matter whether water is
colder (day) or warmer (night) than land. Only numpy is needed.

The result is a single translation (dx, dy) for the whole image, so it
cannot fix rotation or warping inside a scene. A tiled product is a small
piece of one scene, where a translation is usually a fair approximation.
"""

import numpy as np


def _box(a, r):
    """Mean filter with a (2r+1)^2 window, edges handled by shrinking the window."""
    if r <= 0:
        return a
    p = np.pad(a, r, mode="edge")
    c = p.cumsum(0).cumsum(1)
    c = np.pad(c, ((1, 0), (1, 0)))
    k = 2 * r + 1
    s = c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]
    return s / (k * k)


def edges(img, valid, smooth=2):
    """Smoothed gradient magnitude, standardised over valid pixels."""
    valid = valid & np.isfinite(img)
    a = np.where(valid, img, 0.0).astype("float64")
    # Fill small gaps (speckled cloud) from valid neighbours, so they don't create false edges.
    num, den = _box(a, 2), _box(valid.astype("float64"), 2)
    fill = np.median(a[valid]) if valid.any() else 0.0
    a = np.where(valid, a, np.where(den > 0, num / np.maximum(den, 1e-9), fill))
    a = _box(a, 1)
    gy, gx = np.gradient(a)
    g = _box(np.hypot(gx, gy), smooth)
    # Use pixels whose neighbourhood is mostly clear; large gaps and their borders drop out.
    v = _box(valid.astype("float64"), 2 + smooth) >= 0.85
    if v.sum() < 10:
        return np.zeros_like(g), v
    m, s = g[v].mean(), g[v].std()
    return np.where(v, (g - m) / (s if s > 0 else 1.0), 0.0), v


def _xcorr(a, b, shape):
    """sum_x a(x) b(x+s) for every shift s, via FFT on a zero-padded grid."""
    fa = np.fft.rfft2(a, shape)
    fb = np.fft.rfft2(b, shape)
    return np.fft.irfft2(np.conj(fa) * fb, shape)


def masked_ncc(ref, rmask, tgt, tmask, max_shift):
    """Masked NCC of tgt against ref for shifts up to max_shift pixels.

    Returns (ncc array of shape (2*max_shift+1,)*2 indexed [dy+max, dx+max], overlap fraction array).
    A peak at (dy, dx) means tgt's content sits dy rows down and dx columns right of ref's.
    """
    h, w = ref.shape
    shape = (h + max_shift + 1, w + max_shift + 1)
    rm, tm = rmask.astype("float64"), tmask.astype("float64")
    f, m = ref * rm, tgt * tm
    n = _xcorr(rm, tm, shape)
    sf = _xcorr(f, tm, shape)
    sm = _xcorr(rm, m, shape)
    sff = _xcorr(f * f, tm, shape)
    smm = _xcorr(rm, m * m, shape)
    sfm = _xcorr(f, m, shape)
    idx = np.r_[np.arange(-max_shift, max_shift + 1)]
    take = lambda a: a[np.ix_(idx % shape[0], idx % shape[1])]  # noqa: E731
    n, sf, sm, sff, smm, sfm = map(take, (n, sf, sm, sff, smm, sfm))
    n = np.round(n)
    with np.errstate(invalid="ignore", divide="ignore"):
        num = sfm - sf * sm / n
        den = np.sqrt(np.clip(sff - sf * sf / n, 0, None) * np.clip(smm - sm * sm / n, 0, None))
        ncc = num / den
    frac = n / max(min(rmask.sum(), tmask.sum()), 1)
    ncc[~np.isfinite(ncc)] = np.nan
    return ncc, frac


def _subpixel(c, i, j):
    def fit(a, b, d):
        den = a - 2 * b + d
        return 0.0 if not np.isfinite(den) or den >= 0 else 0.5 * (a - d) / den
    dy = fit(c[i - 1, j], c[i, j], c[i + 1, j]) if 0 < i < c.shape[0] - 1 else 0.0
    dx = fit(c[i, j - 1], c[i, j], c[i, j + 1]) if 0 < j < c.shape[1] - 1 else 0.0
    return float(np.clip(dy, -0.5, 0.5)), float(np.clip(dx, -0.5, 0.5))


def measure(ref, ref_valid, tgt, tgt_valid, max_shift=110, smooth=2, min_overlap=0.3, exclude=6):
    """Estimate the offset of tgt relative to ref (same grid).

    max_shift default 110 px = 7.7 km at 70 m, just over NASA's 7 km worst case.
    Returns a dict: dx, dy (pixels; +dx east, +dy south), peak (NCC at the peak),
    second (best NCC more than `exclude` px away), distinct (peak / second),
    edge_px (pixels with edges used), ok (whether the match looks trustworthy).
    """
    max_shift = int(min(max_shift, ref.shape[0] // 2 - 1, ref.shape[1] // 2 - 1))
    e_ref, v_ref = edges(ref, ref_valid, smooth)
    e_tgt, v_tgt = edges(tgt, tgt_valid, smooth)
    used = int(min(v_ref.sum(), v_tgt.sum()))
    res = {"dx": None, "dy": None, "peak": None, "second": None, "distinct": None, "edge_px": used,
           "max_shift_px": max_shift, "ok": False, "why": ""}
    if used < 500 or max_shift < 3:
        res["why"] = "too few clear pixels to match"
        return res
    if np.abs(e_ref[v_ref]).max() == 0:
        res["why"] = "reference has no edges (no water or texture in view)"
        return res
    ncc, frac = masked_ncc(e_ref, v_ref, e_tgt, v_tgt, max_shift)
    ncc = np.where(frac >= min_overlap, ncc, np.nan)
    if not np.isfinite(ncc).any():
        res["why"] = "images overlap too little at every shift"
        return res
    i, j = np.unravel_index(np.nanargmax(ncc), ncc.shape)
    peak = float(ncc[i, j])
    yy, xx = np.ogrid[: ncc.shape[0], : ncc.shape[1]]
    far = (yy - i) ** 2 + (xx - j) ** 2 > exclude ** 2
    second = float(np.nanmax(np.where(far, ncc, np.nan))) if np.isfinite(ncc[far]).any() else 0.0
    sy, sx = _subpixel(np.nan_to_num(ncc, nan=-1), i, j)
    dy, dx = i - max_shift + sy, j - max_shift + sx
    distinct = peak / second if second > 0 else float("inf")
    on_edge = abs(i - max_shift) >= max_shift - 1 or abs(j - max_shift) >= max_shift - 1
    ok = peak >= 0.2 and distinct >= 1.25 and not on_edge
    why = "" if ok else ("peak at the search limit" if on_edge else
                         "weak match" if peak < 0.2 else "two similar matches (ambiguous)")
    res.update(dx=float(dx), dy=float(dy), peak=round(peak, 3), second=round(second, 3),
               distinct=round(distinct, 2), ok=bool(ok), why=why)
    return res


def corrected_geotransform(gt, dx, dy):
    """Geotransform that puts the content back: content sits (dx, dy) px off, so move the origin back."""
    return (gt[0] - dx * gt[1] - dy * gt[2], gt[1], gt[2], gt[3] - dx * gt[4] - dy * gt[5], gt[4], gt[5])
