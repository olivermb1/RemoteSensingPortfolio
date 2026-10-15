"""Per-class spectral signatures from an image and a land cover map.

Pure numpy, so the same code runs standalone (via classspectra.io, rasterio)
and inside QGIS (via the Processing script, GDAL). Inputs are already aligned:

    image   float array (bands, rows, cols), reflectance, NaN where invalid
    labels  int array (rows, cols), land cover class per pixel

The steps that make signatures trustworthy when the map is noisy:
  1. border erosion: drop pixels within `erosion` pixels of another class
     (mixed pixels and misregistration live on class edges)
  2. purity: optional per-pixel fraction of the class inside a coarse pixel
     (for 10 m maps on 30 m HLS); keep only near-pure pixels
  3. spectral outlier trimming: robust z-score against the class median
  4. robust statistics: median and percentiles, not mean +/- std
"""

import numpy as np

STAT_NAMES = ["median", "p10", "p25", "p75", "p90", "mean", "std"]


def interior_mask(labels, radius, ignore=None):
    """True where every pixel within `radius` (square window) has the same label."""
    if radius <= 0:
        return np.ones(labels.shape, bool)
    pad = np.pad(labels, radius, mode="edge")
    rows, cols = labels.shape
    keep = np.ones(labels.shape, bool)
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if dy == 0 and dx == 0:
                continue
            shifted = pad[radius + dy: radius + dy + rows, radius + dx: radius + dx + cols]
            keep &= shifted == labels
    return keep


def robust_z(samples):
    """Per-pixel RMS of robust z-scores across bands. samples: (n, bands)."""
    med = np.median(samples, axis=0)
    mad = 1.4826 * np.median(np.abs(samples - med), axis=0)
    mad = np.where(mad > 1e-6, mad, 1e-6)
    z = (samples - med) / mad
    return np.sqrt(np.mean(z ** 2, axis=1))


def _stats(samples):
    q = np.percentile(samples, [50, 10, 25, 75, 90], axis=0)
    return {
        "median": q[0], "p10": q[1], "p25": q[2], "p75": q[3], "p90": q[4],
        "mean": samples.mean(axis=0), "std": samples.std(axis=0),
    }


def class_signatures(image, labels, classes=None, erosion=1, purity=None,
                     min_purity=0.0, outlier_z=3.5, min_pixels=30,
                     max_samples=100_000, red_nir=None, seed=0, valid=None):
    """Compute signatures for every class present in `labels`.

    Returns a dict {class_value: result}. Each result has counts at each
    filtering step, per-band statistics, an NDVI summary (when red_nir is a
    (red_index, nir_index) pair) and `samples` (cleaned pixels, kept for
    separability). Classes with fewer than `min_pixels` after filtering are
    returned with `stats=None` and a warning.
    """
    rng = np.random.default_rng(seed)
    labels = np.asarray(labels)
    if valid is None:
        valid = np.all(np.isfinite(image), axis=0)
    else:
        valid = valid & np.all(np.isfinite(image), axis=0)
    interior = interior_mask(labels, erosion)
    if classes is None:
        classes = [int(c) for c in np.unique(labels[valid])]

    results = {}
    for c in classes:
        in_class = (labels == c) & valid
        n_total = int(in_class.sum())
        res = {"class": int(c), "n_total": n_total, "warnings": []}
        mask = in_class & interior
        res["n_after_erosion"] = int(mask.sum())
        if erosion > 0 and res["n_after_erosion"] < min_pixels <= n_total:
            # Rare or linear class (roads, rivers): erosion would delete it.
            mask = in_class
            res["warnings"].append("erosion skipped: class too small or thin")
        if purity is not None and min_purity > 0:
            mask = mask & (purity >= min_purity)
        res["n_after_purity"] = int(mask.sum())

        idx = np.flatnonzero(mask)
        if idx.size > max_samples:
            idx = rng.choice(idx, max_samples, replace=False)
        samples = image.reshape(image.shape[0], -1)[:, idx].T  # (n, bands)

        if outlier_z and samples.shape[0] >= min_pixels:
            z = robust_z(samples)
            keep = z <= outlier_z
            res["outlier_share"] = float(1 - keep.mean())
            samples = samples[keep]
        else:
            res["outlier_share"] = 0.0
        res["n_used"] = int(samples.shape[0])

        if samples.shape[0] < min_pixels:
            res["stats"] = None
            res["samples"] = samples
            res["warnings"].append(f"only {samples.shape[0]} clean pixels (< {min_pixels})")
            results[int(c)] = res
            continue

        st = _stats(samples)
        res["stats"] = st
        res["spread"] = float(np.median((st["p75"] - st["p25"]) / np.maximum(np.abs(st["median"]), 1e-3)))
        if red_nir is not None:
            r, n = samples[:, red_nir[0]], samples[:, red_nir[1]]
            ndvi = (n - r) / np.where(np.abs(n + r) > 1e-6, n + r, np.nan)
            ndvi = ndvi[np.isfinite(ndvi)]
            res["ndvi"] = {k: float(v) for k, v in zip(
                ["median", "p25", "p75"], np.percentile(ndvi, [50, 25, 75]))}
        res["samples"] = samples
        results[int(c)] = res
    return results


def jeffries_matusita(a, b, max_n=5000, seed=0):
    """JM distance (0..2) between two sample sets, Gaussian assumption."""
    rng = np.random.default_rng(seed)
    if a.shape[0] > max_n:
        a = a[rng.choice(a.shape[0], max_n, replace=False)]
    if b.shape[0] > max_n:
        b = b[rng.choice(b.shape[0], max_n, replace=False)]
    ma, mb = a.mean(0), b.mean(0)
    eye = np.eye(a.shape[1]) * 1e-6
    ca, cb = np.cov(a, rowvar=False) + eye, np.cov(b, rowvar=False) + eye
    cm = (ca + cb) / 2
    d = ma - mb
    term1 = d @ np.linalg.solve(cm, d) / 8
    _, ld_m = np.linalg.slogdet(cm)
    _, ld_a = np.linalg.slogdet(ca)
    _, ld_b = np.linalg.slogdet(cb)
    term2 = 0.5 * (ld_m - 0.5 * (ld_a + ld_b))
    bhat = term1 + term2
    return float(2 * (1 - np.exp(-bhat)))


def separability_matrix(results):
    """Pairwise JM for classes that have stats. Returns (classes, matrix)."""
    ok = [c for c, r in results.items() if r["stats"] is not None]
    m = np.full((len(ok), len(ok)), np.nan)
    for i, ci in enumerate(ok):
        m[i, i] = 0.0
        for j in range(i + 1, len(ok)):
            m[i, j] = m[j, i] = jeffries_matusita(results[ci]["samples"], results[ok[j]]["samples"])
    return ok, m


def to_broad(labels, mapping, codes, nodata=0):
    """Recode a map to shared broad classes. mapping: value -> broad name,
    codes: broad name -> int code."""
    out = np.full(labels.shape, nodata, dtype=np.int16)
    for value, name in mapping.items():
        out[labels == value] = codes[name]
    return out


def map_agreement(broad_a, broad_b, classes, valid=None):
    """For each broad class: pixels in A, in B, and share of A that B agrees on."""
    if valid is None:
        valid = np.ones(broad_a.shape, bool)
    rows = {}
    for c in classes:
        in_a = (broad_a == c) & valid
        in_b = (broad_b == c) & valid
        n_a = int(in_a.sum())
        rows[c] = {
            "pixels_a": n_a,
            "pixels_b": int(in_b.sum()),
            "agree": int((in_a & in_b).sum()),
            "share_of_a_agreed": float((in_a & in_b).sum() / n_a) if n_a else float("nan"),
        }
    return rows


def spectral_angle(a, b):
    """Angle in degrees between two spectra."""
    cos = float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))
    return float(np.degrees(np.arccos(np.clip(cos, -1, 1))))
