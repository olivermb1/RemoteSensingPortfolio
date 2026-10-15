"""Composite Check maths: numpy only, no file I/O.

A stack is T scenes on one grid. Everything here takes plain arrays so the
same code runs from the command line, from QGIS and from tests.

Per-pixel layers follow the spirit of FORCE's INF product (count, selected
date, distance to target date, sensor) and of Francini et al. 2023 criteria
1 (valid observations and gaps), 4 (distance to target date) and 5
(selected-date spread). Scene dominance, the scene outlier screen and the
Landsat vs Sentinel-2 checks are additions of this tool.
"""

from dataclasses import dataclass, field

import numpy as np

NO_SOURCE = -1

# Ju et al. 2025 (RSE 324:114723): after BRDF and bandpass adjustment, HLS v2.0
# Landsat vs Sentinel-2 residual differences were below 4.2% for red, NIR,
# SWIR1 and SWIR2. Used here as the reference envelope.
JU2025_THRESHOLD = 0.042
JU2025_BANDS = ("red", "nir", "swir1", "swir2")


@dataclass
class Stack:
    """Scenes on one grid.

    refl: int16 (T, B, H, W) scaled reflectance; nodata where no data.
    clear: bool (T, H, W), True where the pixel is usable.
    dates: datetime64[D] (T,), sorted ascending.
    sensors: per-scene labels such as 'L8', 'L9', 'S2A', 'S2B'.
    aerosol_high: optional bool (T, H, W), HLS Fmask aerosol level 3.
    """
    refl: np.ndarray
    clear: np.ndarray
    dates: np.ndarray
    sensors: list
    ids: list
    band_names: list
    scale: float = 1e-4
    nodata: int = -9999
    aerosol_high: np.ndarray = None
    meta: dict = field(default_factory=dict)

    @property
    def T(self):
        return self.refl.shape[0]

    @property
    def shape(self):
        return self.refl.shape[2:]

    @property
    def family(self):
        """'L' for Landsat scenes, 'S' for Sentinel-2."""
        return np.array(["L" if s.upper().startswith(("L", "OLI")) else "S" for s in self.sensors])

    def band(self, b, scenes=None):
        """Reflectance of band b as float32 (T, H, W), NaN where not clear."""
        if isinstance(b, str):
            b = self.band_names.index(b)
        sel = slice(None) if scenes is None else scenes
        raw = self.refl[sel, b]
        out = raw.astype("float32") * self.scale
        out[(raw == self.nodata) | ~self.clear[sel]] = np.nan
        return out


# --- masks -------------------------------------------------------------------

def fmask_clear(fmask, bits=(0, 1, 2, 3), nodata=255):
    """Clear = data present and none of the given HLS Fmask bits set.

    HLS v2.0 Fmask bits: 0 cirrus (reserved), 1 cloud, 2 adjacent to cloud or
    shadow, 3 cloud shadow, 4 snow/ice, 5 water, 6-7 aerosol level.
    """
    m = 0
    for b in bits:
        m |= 1 << int(b)
    return (fmask != nodata) & ((fmask.astype(np.int64) & m) == 0)


def fmask_aerosol_high(fmask, nodata=255):
    return (fmask != nodata) & (((fmask.astype(np.int64) >> 6) & 3) == 3)


def dilate(mask, n):
    """Binary dilation by n pixels (square), without scipy."""
    if n <= 0:
        return mask
    out = mask.copy()
    for _ in range(n):
        m = out.copy()
        m[1:, :] |= out[:-1, :]
        m[:-1, :] |= out[1:, :]
        m[:, 1:] |= out[:, :-1]
        m[:, :-1] |= out[:, 1:]
        out = m
    return out


# --- criterion 1: observations and gaps --------------------------------------

def clear_count(clear):
    return clear.sum(axis=0).astype("int16")


def max_gap_days(clear, dates, start, end):
    """Longest run of days with no clear observation, per pixel.

    Counts the stretch from the period start to the first clear observation
    and from the last one to the period end, so a pixel with no clear
    observation gets the whole period length.
    """
    start, end = np.datetime64(start, "D"), np.datetime64(end, "D")
    last = np.full(clear.shape[1:], 0, "int32")  # days since start of last clear obs
    gap = np.zeros(clear.shape[1:], "int32")
    for t in range(clear.shape[0]):
        d = int((dates[t] - start).astype(int))
        c = clear[t]
        gap = np.where(c, np.maximum(gap, d - last), gap)
        last = np.where(c, d, last)
    total = int((end - start).astype(int))
    return np.maximum(gap, total - last).astype("int16")


# --- compositing and the source scene ----------------------------------------

def per_band_median(stack):
    return np.stack([np.nanmedian(stack.band(b), axis=0) for b in range(len(stack.band_names))])


def nearest_observation(stack, target):
    """Index of the clear observation spectrally closest to target (B, H, W).

    This is the proxy source scene for median-type composites (median,
    geomedian, GeoMAD), which have no single source scene per pixel.
    """
    best = np.full(stack.shape, np.inf, "float32")
    idx = np.full(stack.shape, NO_SOURCE, "int16")
    for t in range(stack.T):
        d = np.zeros(stack.shape, "float32")
        for b in range(len(stack.band_names)):
            x = stack.band(b, scenes=slice(t, t + 1))[0]
            d += (x - target[b]) ** 2
        d[~np.isfinite(d)] = np.inf
        better = d < best
        best[better] = d[better]
        idx[better] = t
    return idx


def closest_to_date(stack, target_date):
    """Index of the clear observation closest in time to target_date."""
    dd = np.abs((stack.dates - np.datetime64(target_date, "D")).astype(int))
    best = np.full(stack.shape, np.iinfo("int32").max, "int32")
    idx = np.full(stack.shape, NO_SOURCE, "int16")
    for t in np.argsort(dd, kind="stable"):
        better = stack.clear[t] & (dd[t] < best)
        best[better] = dd[t]
        idx[better] = t
    return idx


def take(stack, idx):
    """Composite values (B, H, W) from the scene index per pixel."""
    out = np.full((len(stack.band_names),) + stack.shape, np.nan, "float32")
    ok = idx >= 0
    rows, cols = np.nonzero(ok)
    t = idx[ok]
    for b in range(len(stack.band_names)):
        v = stack.refl[t, b, rows, cols].astype("float32") * stack.scale
        out[b, rows, cols] = v
    return out


def build_composite(stack, method="medoid", target_date=None):
    """Return (composite (B,H,W), source index (H,W), exact_source flag).

    median  per-band median; source is a proxy (closest observation).
    medoid  the observation closest to the per-band median (a common, cheap
            stand-in for the true medoid); source is exact.
    target  the clear observation closest to target_date, a minimal
            best-available-pixel rule; source is exact.
    """
    if method == "median":
        comp = per_band_median(stack)
        return comp, nearest_observation(stack, comp), False
    if method == "medoid":
        idx = nearest_observation(stack, per_band_median(stack))
        return take(stack, idx), idx, True
    if method == "target":
        idx = closest_to_date(stack, target_date)
        return take(stack, idx), idx, True
    raise ValueError(f"unknown method {method}")


# --- criteria 4 and 5: dates of the selected observations --------------------

def selection_dates(idx, dates, target_date):
    """Selected day of year and distance in days to the target date."""
    ok = idx >= 0
    doy = np.zeros(idx.shape, "int16")
    doyd = np.full(idx.shape, -1, "int16")
    sel = dates[np.where(ok, idx, 0)]
    years = sel.astype("datetime64[Y]")
    doy[ok] = ((sel - years).astype(int) + 1)[ok]
    doyd[ok] = np.abs((sel - np.datetime64(target_date, "D")).astype(int))[ok]
    return doy, doyd


def doy_spread(doy, idx, block=None):
    """Francini criterion 5: standard deviation of selected DOY over the area
    (or per block of `block` pixels)."""
    ok = idx >= 0
    if block is None:
        return float(np.std(doy[ok])) if ok.any() else float("nan")
    h, w = doy.shape
    out = np.full(((h + block - 1) // block, (w + block - 1) // block), np.nan, "float32")
    for i in range(out.shape[0]):
        for j in range(out.shape[1]):
            s = (slice(i * block, (i + 1) * block), slice(j * block, (j + 1) * block))
            v = doy[s][ok[s]]
            if v.size > 1:
                out[i, j] = v.std()
    return out


# --- scene dominance (new) ---------------------------------------------------

def scene_contribution(idx, T):
    """Share of composited pixels that each scene supplied."""
    ok = idx >= 0
    counts = np.bincount(idx[ok].astype(int), minlength=T)
    n = counts.sum()
    return counts / n if n else counts.astype(float)


def dominance(shares, threshold=0.5):
    """Summary of how concentrated the composite is on few scenes.

    top_share: share of the area from the single largest scene.
    effective_scenes: 1 / sum(share^2) (inverse Herfindahl index): the number
    of equally sized scenes that would give the same concentration.
    """
    s = np.asarray(shares, float)
    hhi = float((s ** 2).sum()) if s.sum() else float("nan")
    top = int(np.argmax(s)) if s.size else -1
    return {
        "top_scene_index": top,
        "top_share": float(s[top]) if s.size else float("nan"),
        "effective_scenes": 1 / hhi if hhi and np.isfinite(hhi) else float("nan"),
        "scenes_used": int((s > 0).sum()),
        "dominated": bool(s.size and s[top] > threshold),
        "threshold": threshold,
    }


def source_scene_share(idx, shares):
    """Per pixel: the area share of the scene this pixel came from."""
    out = np.full(idx.shape, np.nan, "float32")
    ok = idx >= 0
    out[ok] = np.asarray(shares, "float32")[idx[ok]]
    return out


# --- scene outlier screen (new) ----------------------------------------------

def robust_stats(stack, min_obs=5):
    """Per-pixel median and scaled MAD of each band across clear observations."""
    med, mad = [], []
    enough = stack.clear.sum(0) >= min_obs
    for b in range(len(stack.band_names)):
        x = stack.band(b)
        m = np.nanmedian(x, axis=0)
        s = 1.4826 * np.nanmedian(np.abs(x - m), axis=0)
        m[~enough] = np.nan
        med.append(m)
        mad.append(s)
    return np.stack(med), np.stack(mad)


def scene_outliers(stack, med, mad, z=3.5, bands=("blue", "green", "red"), floor=0.005):
    """Per scene: share of its clear pixels that are robust outliers, and the
    median robust z-score in the blue band.

    Undetected haze and thin cloud brighten the visible bands, so a scene
    with many visible-band outliers, or a positive median blue z, is a
    candidate for residual contamination. MAD is floored at `floor`
    reflectance so very stable pixels don't produce huge z-scores.

    Also returns a per-pixel bool layer for each scene (T, H, W): outlier.
    """
    bi = [stack.band_names.index(b) for b in bands if b in stack.band_names]
    outlier = np.zeros(stack.clear.shape, bool)
    zblue = np.full(stack.T, np.nan)
    share = np.full(stack.T, np.nan)
    blue = stack.band_names.index("blue") if "blue" in stack.band_names else bi[0]
    zmax = np.zeros(stack.clear.shape, "float32")
    for b in bi:
        zb = (stack.band(b) - med[b]) / np.maximum(mad[b], floor)
        np.fmax(zmax, np.abs(zb), out=zmax)
        if b == blue:
            zbl = zb
    valid = stack.clear & np.isfinite(med[blue])[None]
    outlier = valid & (zmax > z)
    for t in range(stack.T):
        v = valid[t]
        if v.sum() >= 100:
            share[t] = outlier[t][v].mean()
            zblue[t] = np.nanmedian(zbl[t][v])
    return share, zblue, outlier


def selected_is_outlier(idx, outlier):
    """Per pixel: 1 if the composite's source observation is itself an outlier."""
    out = np.full(idx.shape, 255, "uint8")
    ok = idx >= 0
    r, c = np.nonzero(ok)
    out[r, c] = outlier[idx[ok], r, c].astype("uint8")
    return out


# --- sensors and Landsat vs Sentinel-2 checks (new) -----------------------------

def landsat_share(stack):
    fam = stack.family
    n = stack.clear.sum(0)
    nl = stack.clear[fam == "L"].sum(0)
    out = np.full(stack.shape, np.nan, "float32")
    out[n > 0] = nl[n > 0] / n[n > 0]
    return out


def source_sensor(stack, idx):
    """1 = Landsat, 2 = Sentinel-2, 0 = none."""
    code = np.where(stack.family == "L", 1, 2).astype("uint8")
    out = np.zeros(idx.shape, "uint8")
    ok = idx >= 0
    out[ok] = code[idx[ok]]
    return out


def sensor_composites(stack, min_obs=3):
    """Per-band medians of Landsat-only and Sentinel-2-only clear observations,
    NaN where a sensor has fewer than min_obs clear observations."""
    fam = stack.family
    out = {}
    for f in ("L", "S"):
        sel = np.nonzero(fam == f)[0]
        if sel.size == 0:
            out[f] = None
            continue
        n = stack.clear[sel].sum(0)
        comp = np.stack([np.nanmedian(stack.band(b, scenes=sel), axis=0) for b in range(len(stack.band_names))])
        comp[:, n < min_obs] = np.nan
        out[f] = comp
    return out["L"], out["S"]


def relative_difference(a, b):
    """(a - b) / mean(a, b), elementwise."""
    with np.errstate(invalid="ignore", divide="ignore"):
        return (a - b) / ((a + b) / 2)


def composite_consistency(stack, comp_l, comp_s, bands=JU2025_BANDS, threshold=JU2025_THRESHOLD):
    """Compare a Landsat-only and a Sentinel-2-only composite.

    Area statistics per band (pair_stats) over pixels both composites cover.
    The two composites draw on different dates, so phenology adds to the
    sensor difference here; the near-coincident pair check separates them.
    Per pixel: the largest |relative difference| across `bands`.
    """
    if comp_l is None or comp_s is None:
        return None, {}
    stats = {}
    worst = np.full(stack.shape, np.nan, "float32")
    both = np.all(np.isfinite(comp_l), 0) & np.all(np.isfinite(comp_s), 0)
    for name in stack.band_names:
        b = stack.band_names.index(name)
        l, s = comp_l[b][both], comp_s[b][both]
        if l.size == 0:
            continue
        rd, bias, gain, off = pair_stats(l, s)
        stats[name] = {
            "rel_diff": rd, "bias_s_minus_l": bias, "gain": gain, "offset": off,
            "pixels": int(l.size),
            "checked": name in bands,
            "within_envelope": bool(rd < threshold) if name in bands else None,
        }
        if name in bands:
            rd = np.abs(relative_difference(comp_l[b], comp_s[b]))
            worst = np.where(both, np.fmax(worst, rd), worst)
    return worst, stats


def pair_stats(l, s):
    """Robust agreement of two co-registered samples.

    rel_diff: median |S - L| / median((S + L) / 2), robust to the odd
    undetected cloud in one of the two scenes.
    bias: median(S - L) / median((S + L) / 2), the systematic part.
    gain, offset: least-squares fit S = gain * L + offset on the 1-99th
    percentile range, to tell additive (atmospheric) from multiplicative
    (bandpass, calibration) differences.
    """
    m = float(np.median((l + s) / 2))
    rd = float(np.median(np.abs(s - l)) / m)
    bias = float(np.median(s - l) / m)
    lo, hi = np.percentile(l, [1, 99])
    k = (l >= lo) & (l <= hi)
    if k.sum() > 10 and np.ptp(l[k]) > 0:
        gain, off = np.polyfit(l[k], s[k], 1)
    else:
        gain, off = np.nan, np.nan
    return rd, bias, float(gain), float(off)


def near_coincident_pairs(stack, max_days=1, min_pixels=1000, min_share=0.5,
                          bands=JU2025_BANDS, threshold=JU2025_THRESHOLD):
    """Compare each Landsat scene with each Sentinel-2 scene within max_days,
    over pixels clear in both. This mirrors how Ju et al. 2025 validated HLS
    (same-day pairs), so it is the fairer test of sensor consistency.

    A pair is 'clean' when the shared clear area is at least min_share of the
    grid. Pairs from mostly cloudy scenes share only cloud edges, where
    missed cloud and shadow dominate the difference, so the summary uses
    clean pairs only.
    """
    fam = stack.family
    rows = []
    for i in np.nonzero(fam == "L")[0]:
        for j in np.nonzero(fam == "S")[0]:
            dt = abs(int((stack.dates[i] - stack.dates[j]).astype(int)))
            if dt > max_days:
                continue
            both = stack.clear[i] & stack.clear[j]
            n = int(both.sum())
            if n < min_pixels:
                continue
            row = {"landsat": stack.ids[i], "sentinel2": stack.ids[j], "days_apart": dt, "pixels": n,
                   "shared_clear_share": n / both.size, "clean": n / both.size >= min_share,
                   "landsat_clear_share": float(stack.clear[i].mean()), "sentinel2_clear_share": float(stack.clear[j].mean())}
            ok = True
            for name in stack.band_names:
                b = stack.band_names.index(name)
                l = stack.refl[i, b][both].astype("float32") * stack.scale
                s = stack.refl[j, b][both].astype("float32") * stack.scale
                rd, bias, gain, off = pair_stats(l, s)
                row[f"{name}_rel_diff"] = rd
                row[f"{name}_bias"] = bias
                row[f"{name}_gain"] = gain
                row[f"{name}_offset"] = off
                if name in bands and rd >= threshold:
                    ok = False
            row["within_envelope"] = ok
            rows.append(row)
    return rows


# --- aerosol (inferred) --------------------------------------------------------

def aerosol_high_share(stack):
    """Share of clear observations flagged high aerosol in Fmask bits 6-7.

    Only meaningful where the input carries aerosol QA (HLS, Landsat C2).
    High-aerosol retrievals are less reliable; their link to composite error
    is inferred, not validated.
    """
    if stack.aerosol_high is None:
        return None
    n = stack.clear.sum(0)
    hi = (stack.aerosol_high & stack.clear).sum(0)
    out = np.full(stack.shape, np.nan, "float32")
    out[n > 0] = hi[n > 0] / n[n > 0]
    return out


# --- per-scene table ---------------------------------------------------------

def scene_table(stack, shares, out_share, zblue, outlier_threshold=0.2, zblue_threshold=2.0):
    valid = (stack.refl[:, 0] != stack.nodata)
    rows = []
    for t in range(stack.T):
        nv = int(valid[t].sum())
        suspect = bool((np.isfinite(out_share[t]) and out_share[t] > outlier_threshold)
                       or (np.isfinite(zblue[t]) and zblue[t] > zblue_threshold))
        rows.append({
            "index": t + 1, "scene_id": stack.ids[t], "date": str(stack.dates[t]), "sensor": stack.sensors[t],
            "data_share": nv / valid[t].size,
            "clear_share": float(stack.clear[t].sum() / valid[t].size),
            "contribution_share": float(shares[t]),
            "outlier_share": float(out_share[t]), "median_z_blue": float(zblue[t]),
            "suspect": suspect,
        })
    return rows


def run_checks(stack, start, end, target_date, method="medoid", composite=None,
               dominance_threshold=0.5, pair_days=1, pair_min_share=0.5, min_sensor_obs=3, outlier_z=3.5):
    """Run every check. Returns (layers dict of 2-D arrays, composite, report dict).

    If `composite` (B, H, W reflectance) is given, it is assessed instead of
    building one; its source scene is the spectrally closest observation.
    """
    layers = {}
    layers["nclear"] = clear_count(stack.clear)
    layers["max_gap"] = max_gap_days(stack.clear, stack.dates, start, end)
    if composite is None:
        comp, idx, exact = build_composite(stack, method, target_date)
    else:
        comp, idx, exact = composite, nearest_observation(stack, composite), False
        method = "external"
    layers["src_scene"] = (idx + 1).astype("int16")  # 0 = none, else 1-based scene number
    doy, doyd = selection_dates(idx, stack.dates, target_date)
    layers["src_doy"], layers["doyd"] = doy, doyd
    layers["src_sensor"] = source_sensor(stack, idx)
    layers["landsat_share"] = landsat_share(stack)
    shares = scene_contribution(idx, stack.T)
    layers["src_scene_share"] = source_scene_share(idx, shares)
    med, mad = robust_stats(stack)
    out_share, zblue, outlier = scene_outliers(stack, med, mad, z=outlier_z)
    layers["src_outlier"] = selected_is_outlier(idx, outlier)
    comp_l, comp_s = sensor_composites(stack, min_sensor_obs)
    worst, ls_stats = composite_consistency(stack, comp_l, comp_s)
    if worst is not None:
        layers["ls_rel_diff"] = worst
    aer = aerosol_high_share(stack)
    if aer is not None:
        layers["aerosol_high_share"] = aer
    pairs = near_coincident_pairs(stack, pair_days, min_share=pair_min_share)
    scenes = scene_table(stack, shares, out_share, zblue)
    dom = dominance(shares, dominance_threshold)
    dom["top_scene"] = scenes[dom["top_scene_index"]]["scene_id"] if dom["top_scene_index"] >= 0 else None
    dom["top_scene_suspect"] = scenes[dom["top_scene_index"]]["suspect"] if dom["top_scene_index"] >= 0 else None

    has = layers["nclear"] > 0
    n = layers["nclear"][has]
    so = layers["src_outlier"]
    report = {
        "method": method, "source_is_exact": exact,
        "period": [str(start), str(end)], "target_date": str(target_date),
        "scenes": stack.T, "landsat_scenes": int((stack.family == "L").sum()),
        "sentinel2_scenes": int((stack.family == "S").sum()),
        "pixels": int(has.size), "pixels_with_no_clear_obs": int((~has).sum()),
        "criterion1_observations": {
            "median_clear": float(np.median(n)) if n.size else 0,
            "p10_clear": float(np.percentile(n, 10)) if n.size else 0,
            "share_below_5": float((layers["nclear"] < 5).mean()),
            "median_max_gap_days": float(np.median(layers["max_gap"][has])) if n.size else None,
            "share_gap_over_60_days": float((layers["max_gap"] > 60).mean()),
        },
        "criterion4_target_distance": {
            "mean_doyd": float(doyd[doyd >= 0].mean()) if (doyd >= 0).any() else None,
            "median_doyd": float(np.median(doyd[doyd >= 0])) if (doyd >= 0).any() else None,
        },
        "criterion5_doy_spread": {"doy_sd_area": doy_spread(doy, idx)},
        "dominance": dom,
        "selected_outliers": {
            "share_of_pixels": float((so == 1).sum() / max((so != 255).sum(), 1)),
            "z_threshold": outlier_z,
        },
        "sensor": {
            "median_landsat_share": float(np.nanmedian(layers["landsat_share"])) if has.any() else None,
            "composite_from_landsat": float((layers["src_sensor"] == 1).sum() / max(has.sum(), 1)),
        },
        "landsat_vs_sentinel2": {
            "reference": "Ju et al. 2025, RSE 324:114723: HLS v2.0 residual differences < 4.2% for red, NIR, SWIR1, SWIR2",
            "threshold": JU2025_THRESHOLD,
            "composite_level": ls_stats,
            "share_pixels_over_threshold": float(np.nanmean(worst[np.isfinite(worst)] > JU2025_THRESHOLD))
            if worst is not None and np.isfinite(worst).any() else None,
            "pairs_max_days": pair_days, "pairs_min_shared_clear": pair_min_share,
            "pairs": pairs,
        },
    }
    if aer is not None:
        report["aerosol"] = {"median_high_aerosol_share": float(np.nanmedian(aer)),
                             "note": "inferred quality signal, not validated"}
    return layers, comp, report, scenes
