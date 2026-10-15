"""Flooded Cropland Calculator: the maths, numpy only.

Every water source (OPERA DSWx, Sentinel-1 backscatter, optical reflectance,
or any water mask) is first turned into the same per-pixel class codes:

    DRY 0, WATER 1 (open water), PARTIAL 2 (partial surface water),
    PERM 3 (masked permanent water, e.g. DSWx ocean), NODATA 255 (not observed:
    cloud, fill, layover).

Then: combine dates -> compare event with baseline -> flood classes -> weight
by the cropland fraction and pixel area -> hectares per zone.
"""
import math

import numpy as np

DRY, WATER, PARTIAL, PERM, NODATA = 0, 1, 2, 3, 255

# Flood classes written to flood_classes.tif
F_DRY, F_NEW_WATER, F_NEW_PARTIAL, F_STANDING, F_UNOBSERVED = 0, 1, 2, 3, 255
FLOOD_LABELS = {F_DRY: "dry", F_NEW_WATER: "new open water (flood)", F_NEW_PARTIAL: "new partial water (flood)",
                F_STANDING: "water before the event / permanent", F_UNOBSERVED: "not observed"}

# ---------------------------------------------------------------- DSWx decode

# OPERA DSWx WTR / BWTR layer values (DSWx-HLS and DSWx-S1 product specs).
# 0 not water, 1 open water, 2 partial surface water, 252 snow/ice,
# 253 cloud/cloud shadow, 254 ocean masked, 255 fill. DSWx-S1 also uses
# 250 (HAND masked) and 251 (layover/shadow). Anything else >= 250 is treated
# as not observed. Check against the product spec of the version you download.
DSWX_MAP = {0: DRY, 1: WATER, 2: PARTIAL, 254: PERM}


def decode_dswx(wtr):
    """DSWx WTR/BWTR array -> class codes."""
    wtr = np.asarray(wtr)
    out = np.full(wtr.shape, NODATA, np.uint8)
    for k, v in DSWX_MAP.items():
        out[wtr == k] = v
    return out


def decode_mask(arr, water_values=(1,), dry_values=(0,), nodata=None):
    """A generic water mask (WOfS, JRC monthly, your own) -> class codes."""
    arr = np.asarray(arr)
    out = np.full(arr.shape, NODATA, np.uint8)
    out[np.isin(arr, dry_values)] = DRY
    out[np.isin(arr, water_values)] = WATER
    if nodata is not None:
        out[arr == nodata] = NODATA
    return out


# ------------------------------------------------- optical: DSWx-HLS tests

# Default thresholds of the DSWx-HLS algorithm (OPERA DSWx-HLS ATBD, inherited
# from USGS DSWE). Reflectance thresholds are on a 0-10000 scale.
DSWX_HLS_THRESHOLDS = dict(
    wigt=0.124, awgt=0.0,
    pswt_1_mndwi=-0.44, pswt_1_nir=1500, pswt_1_swir1=900, pswt_1_ndvi=0.7,
    pswt_2_mndwi=-0.5, pswt_2_blue=1000, pswt_2_nir=2500, pswt_2_swir1=3000, pswt_2_swir2=1000,
)

# DSWE interpretation of the 5 diagnostic tests (code = t1 + 10 t2 + 100 t3 + 1000 t4 + 10000 t5)
_HIGH = {1111, 10111, 11011, 11101, 11110, 11111}
_MOD = {111, 1011, 1101, 1110, 10011, 10101, 10110, 11001, 11010, 11100}
_PSW_CONS = {11000}
_PSW_AGGR = {11, 101, 110, 1001, 1010, 1100, 10000, 10001, 10010, 10100}


def dswx_hls_tests(blue, green, red, nir, swir1, swir2, scale=1.0, thresholds=None):
    """The five DSWx-HLS / DSWE diagnostic tests on surface reflectance.

    Inputs are arrays of reflectance; `scale` multiplies them onto the
    0-10000 scale the thresholds use (1 for HLS/Sentinel-2 L2A integers,
    10000 for 0-1 floats). Returns (diagnostic code, interpreted class) where
    the class is 1 high-confidence, 2 moderate, 3 partial conservative,
    4 partial aggressive, 0 not water.
    """
    t = dict(DSWX_HLS_THRESHOLDS, **(thresholds or {}))
    b, g, r, n, s1, s2 = (np.asarray(x, np.float32) * scale for x in (blue, green, red, nir, swir1, swir2))
    with np.errstate(divide="ignore", invalid="ignore"):
        mndwi = (g - s1) / (g + s1)
        ndvi = (n - r) / (n + r)
    mbsrv, mbsrn = g + r, n + s1
    awesh = b + 2.5 * g - 1.5 * mbsrn - 0.25 * s2
    t1 = mndwi > t["wigt"]
    t2 = mbsrv > mbsrn
    t3 = awesh > t["awgt"]
    t4 = (mndwi > t["pswt_1_mndwi"]) & (s1 < t["pswt_1_swir1"]) & (n < t["pswt_1_nir"]) & (ndvi < t["pswt_1_ndvi"])
    t5 = ((mndwi > t["pswt_2_mndwi"]) & (b < t["pswt_2_blue"]) & (s1 < t["pswt_2_swir1"])
          & (s2 < t["pswt_2_swir2"]) & (n < t["pswt_2_nir"]))
    code = (t1.astype(np.int32) + 10 * t2 + 100 * t3 + 1000 * t4 + 10000 * t5)
    cls = np.zeros(code.shape, np.uint8)
    for codes, v in ((_HIGH, 1), (_MOD, 2), (_PSW_CONS, 3), (_PSW_AGGR, 4)):
        cls[np.isin(code, list(codes))] = v
    return code, cls


def optical_water(blue, green, red, nir, swir1, swir2, invalid=None, scale=1.0, thresholds=None):
    """Reflectance -> class codes using the DSWx-HLS tests. High and moderate
    confidence count as WATER, both partial-water classes as PARTIAL.
    `invalid` (bool array) marks cloud, shadow and fill."""
    _, cls = dswx_hls_tests(blue, green, red, nir, swir1, swir2, scale, thresholds)
    out = np.full(cls.shape, DRY, np.uint8)
    out[(cls == 1) | (cls == 2)] = WATER
    out[(cls == 3) | (cls == 4)] = PARTIAL
    bad = ~np.isfinite(np.asarray(blue, np.float32)) | (np.asarray(blue) <= 0)
    if invalid is not None:
        bad |= invalid
    out[bad] = NODATA
    return out


# Cloud/fill masks for common optical products
SCL_INVALID = (0, 1, 3, 8, 9, 10)  # S2 L2A SCL: nodata, saturated, shadow, cloud med/high, cirrus
# (SCL 6 = water is valid; snow 11 is left valid here, Africa)


def fmask_invalid(fmask, dilated=True):
    """HLS Fmask bits: 1 cloud, 2 adjacent, 3 cloud shadow (bit 0 cirrus is
    unreliable in v2.0 and is ignored)."""
    f = np.asarray(fmask).astype(np.uint16)
    bits = [1, 3] + ([2] if dilated else [])
    bad = np.zeros(f.shape, bool)
    for bit in bits:
        bad |= (f >> bit) & 1 == 1
    return bad | (f == 255)


# ---------------------------------------------------------- SAR (Sentinel-1)

def to_db(linear):
    a = np.asarray(linear, np.float32)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(a > 0, 10 * np.log10(a), np.nan).astype(np.float32)


def boxcar(a, k=5):
    """k x k mean ignoring NaN (a cheap speckle filter), via summed-area tables."""
    a = np.asarray(a, np.float64)
    if k <= 1:
        return a.astype(np.float32)
    v = np.isfinite(a)
    z = np.where(v, a, 0.0)
    p = k // 2

    def box(x):
        x = np.pad(x, ((p + 1, p), (p + 1, p)), mode="constant")
        c = x.cumsum(0).cumsum(1)
        return c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]

    s, n = box(z), box(v.astype(np.float64))
    with np.errstate(invalid="ignore", divide="ignore"):
        out = s / n
    out[~v] = np.nan
    return out.astype(np.float32)


def otsu(values, bins=256, lo=None, hi=None):
    """Otsu threshold of a 1-D sample (NaN ignored)."""
    v = np.asarray(values, np.float64)
    v = v[np.isfinite(v)]
    if lo is not None:
        v = v[v >= lo]
    if hi is not None:
        v = v[v <= hi]
    if v.size < 100:
        return None
    hist, edges = np.histogram(v, bins=bins)
    mids = (edges[:-1] + edges[1:]) / 2
    w0 = np.cumsum(hist)
    w1 = w0[-1] - w0
    m0 = np.cumsum(hist * mids)
    mu0 = m0 / np.maximum(w0, 1)
    mu1 = (m0[-1] - m0) / np.maximum(w1, 1)
    between = w0 * w1 * (mu0 - mu1) ** 2
    return float(mids[np.argmax(between[:-1])])


def sar_threshold(vv_db, default=-18.0, lo=-26.0, hi=-10.0, smooth=5):
    """Pick a VV water threshold: Otsu on the (smoothed) dB histogram between
    lo and hi, kept inside [-22, -15] dB; falls back to `default`.
    Works best when the scene holds a fair share of water (a lake, a river)."""
    sm = boxcar(vv_db, smooth)
    t = otsu(sm[::2, ::2], lo=lo, hi=hi)
    if t is None:
        return default, "default"
    return float(min(max(t, -22.0), -15.0)), "otsu"


def sar_water(vv_db, threshold, smooth=5, valid=None):
    """Open water where smoothed VV backscatter is below `threshold` dB."""
    sm = boxcar(vv_db, smooth)
    out = np.where(sm < threshold, WATER, DRY).astype(np.uint8)
    bad = ~np.isfinite(sm)
    if valid is not None:
        bad |= ~valid
    out[bad] = NODATA
    return out


def sar_change_water(event_db, baseline_db, threshold, drop_db=3.0, loose_db=-14.0, smooth=5, valid=None):
    """Event water from absolute threshold OR a backscatter drop.

    A pixel is WATER when its smoothed VV is below `threshold`, or when it
    fell by more than `drop_db` relative to the baseline (median of the
    baseline scenes) and is below `loose_db`. The drop test catches shallow
    floodwater in fields that never gets as dark as a calm lake. (This is the
    change-detection idea in UN-SPIDER's recommended practice, at full
    resolution.)
    """
    ev = boxcar(event_db, smooth)
    bl = boxcar(baseline_db, smooth)
    with np.errstate(invalid="ignore"):
        water = (ev < threshold) | (((ev - bl) < -drop_db) & (ev < loose_db))
    out = np.where(water, WATER, DRY).astype(np.uint8)
    bad = ~np.isfinite(ev)
    if valid is not None:
        bad |= ~valid
    out[bad] = NODATA
    return out


# ----------------------------------------------------------- combine dates

def combine(stack, mode="any"):
    """Combine class arrays from several dates into one.

    any      water if water on any observed date (maximum extent; the default
             for the event, and for the baseline it is the conservative choice:
             anything wet before the event never counts as flood)
    majority water if water on more than half the observed dates
    """
    s = np.stack([np.asarray(a, np.uint8) for a in stack])
    obs = s != NODATA
    n_obs = obs.sum(0)
    n_w = ((s == WATER) | (s == PERM)).sum(0)
    n_p = (s == PARTIAL).sum(0)
    perm = (s == PERM).any(0)
    out = np.full(s.shape[1:], NODATA, np.uint8)
    out[n_obs > 0] = DRY
    if mode == "any":
        out[(n_p > 0)] = PARTIAL
        out[(n_w > 0)] = WATER
    elif mode == "majority":
        out[(n_p + n_w) * 2 > n_obs] = PARTIAL
        out[n_w * 2 > n_obs] = WATER
    else:
        raise ValueError(f"unknown mode {mode}")
    out[perm] = PERM
    out[n_obs == 0] = NODATA
    return out


def flood_classes(event, baseline=None, permanent=None):
    """Event vs baseline -> flood classes (F_*).

    new water   = water now, not water (or partial) before, not permanent
    unobserved  = event not observed. Pixels whose baseline was not observed
                  are still classed from the event alone (counted separately
                  in the summary as `baseline_unobserved`).
    """
    ev = np.asarray(event, np.uint8)
    out = np.full(ev.shape, F_DRY, np.uint8)
    before = np.zeros(ev.shape, bool)
    if baseline is not None:
        bl = np.asarray(baseline, np.uint8)
        before = (bl == WATER) | (bl == PERM) | (bl == PARTIAL)
    if permanent is not None:
        before |= np.asarray(permanent, bool)
    ev_water = (ev == WATER) | (ev == PERM)
    out[(ev == WATER) & ~before] = F_NEW_WATER
    out[(ev == PARTIAL) & ~before] = F_NEW_PARTIAL
    out[(ev_water | (ev == PARTIAL)) & before] = F_STANDING
    out[ev == PERM] = F_STANDING
    if permanent is not None:
        out[np.asarray(permanent, bool)] = F_STANDING
    out[ev == NODATA] = F_UNOBSERVED
    return out


# --------------------------------------------------------------- areas

WGS84_A, WGS84_F = 6378137.0, 1 / 298.257223563


def _authalic_lat(lat_rad):
    e2 = WGS84_F * (2 - WGS84_F)
    e = math.sqrt(e2)
    s = np.sin(lat_rad)
    q = (1 - e2) * (s / (1 - e2 * s * s) - np.log((1 - e * s) / (1 + e * s)) / (2 * e))
    return q


def pixel_area_m2(transform, shape, geographic):
    """Area of each pixel in m2, as an (rows, 1) column (geographic CRS, exact
    on the WGS84 ellipsoid) or a scalar (projected CRS: |a*e|; for UTM this is
    within about 0.1% of true area)."""
    a, b, c, d, e, f = transform[:6]
    if not geographic:
        return abs(a * e - b * d)
    rows = shape[0]
    top = f + e * np.arange(rows)
    bot = top + e
    q_top = _authalic_lat(np.radians(top))
    q_bot = _authalic_lat(np.radians(bot))
    area = WGS84_A ** 2 / 2 * np.abs(q_top - q_bot) * math.radians(abs(a))
    return area.reshape(-1, 1)


# ------------------------------------------------------------ zone summary

SUMMARY_FIELDS = [
    "zone_ha", "observed_pct", "crop_ha", "crop_observed_pct",
    "flooded_crop_ha", "flooded_crop_partial_ha", "flooded_crop_pct",
    "flooded_all_ha", "standing_water_crop_ha", "baseline_unobserved_crop_ha",
]


def zone_summary(flood, crop_frac, area, zone_mask, baseline=None):
    """Hectares for one zone. `crop_frac` is the cropland fraction (0-1, NaN
    where the cropland map has no data) of each pixel on the flood grid;
    `area` is pixel_area_m2 output; `zone_mask` is a bool array."""
    z = np.asarray(zone_mask, bool)
    if not z.any():
        return dict.fromkeys(SUMMARY_FIELDS, 0.0)
    fl = flood[z]
    ar = np.broadcast_to(area, flood.shape)[z] / 1e4
    cf = np.nan_to_num(np.asarray(crop_frac, np.float32)[z], nan=0.0)
    obs = fl != F_UNOBSERVED
    crop_ha = float((cf * ar).sum())
    crop_obs = float((cf * ar)[obs].sum())
    fc = float((cf * ar)[fl == F_NEW_WATER].sum())
    fcp = float((cf * ar)[fl == F_NEW_PARTIAL].sum())
    out = dict(
        zone_ha=float(ar.sum()),
        observed_pct=100.0 * float(ar[obs].sum()) / float(ar.sum()),
        crop_ha=crop_ha,
        crop_observed_pct=100.0 * crop_obs / crop_ha if crop_ha else 0.0,
        flooded_crop_ha=fc,
        flooded_crop_partial_ha=fcp,
        flooded_crop_pct=100.0 * fc / crop_obs if crop_obs else 0.0,
        flooded_all_ha=float(ar[fl == F_NEW_WATER].sum()),
        standing_water_crop_ha=float((cf * ar)[fl == F_STANDING].sum()),
        baseline_unobserved_crop_ha=0.0,
    )
    if baseline is not None:
        bu = (np.asarray(baseline)[z] == NODATA) & ((fl == F_NEW_WATER) | (fl == F_NEW_PARTIAL))
        out["baseline_unobserved_crop_ha"] = float((cf * ar)[bu].sum())
    return out
