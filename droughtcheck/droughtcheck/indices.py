"""Monthly drought indices on (time, y, x) blocks.

SPI and SPEI use the `climate-indices` package (NOAA/NCEI lineage) when it is installed,
and a small built-in implementation otherwise, so the QGIS script runs on a stock QGIS
(numpy + scipy). tests/test_indices.py checks that the two agree.

  SPI   gamma fit per calendar month on rainfall summed over `scale` months, with the
        probability of zero handled as in McKee et al. (1993) / Edwards & McKee (1997).
  SPEI  generalised-logistic ("log-logistic") fit of rainfall minus PET by L-moments,
        as in the R SPEI package (Vicente-Serrano et al. 2010; Begueria et al. 2014).
  PET   monthly Hargreaves (Hargreaves & Samani 1985; FAO-56 eq. 52) from monthly mean
        daily Tmax and Tmin.
"""
from __future__ import annotations

import calendar
import logging

import numpy as np

CLASSES = [  # (upper bound, code, label) McKee et al. 1993 / WMO-No. 1090
    (-2.0, -3, "Extreme drought"),
    (-1.5, -2, "Severe drought"),
    (-1.0, -1, "Moderate drought"),
    (1.0, 0, "Near normal"),
    (1.5, 1, "Moderately wet"),
    (2.0, 2, "Very wet"),
    (np.inf, 3, "Extremely wet"),
]
CLASS_LABELS = {code: lab for _, code, lab in CLASSES}


def _ci():
    """climate_indices modules, or None. Quietens its structured logging."""
    try:
        import structlog
        structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING))
        from climate_indices import compute, indices
        return indices, compute
    except Exception:
        return None


def backend_name(prefer: str = "auto") -> str:
    if prefer == "builtin":
        return "builtin"
    if _ci() is None:
        if prefer == "climate-indices":
            raise ImportError("climate-indices is not installed: pip install climate-indices")
        return "builtin"
    return "climate-indices"


def classify(z: np.ndarray) -> np.ndarray:
    out = np.full(z.shape, -99, dtype="int8")
    ok = np.isfinite(z)
    lo = -np.inf
    for hi, code, _ in CLASSES:
        sel = ok & (z > lo) & (z <= hi) if np.isfinite(lo) else ok & (z <= hi)
        out[sel] = code
        lo = hi
    return out


def rolling_sum(x: np.ndarray, scale: int) -> np.ndarray:
    """Sum over the current and previous scale-1 months; NaN if any month is missing."""
    if scale == 1:
        return x.astype("float64")
    c = np.cumsum(np.nan_to_num(x, nan=0.0), axis=0, dtype="float64")
    n = np.cumsum(np.isnan(x), axis=0)
    out = np.full(x.shape, np.nan)
    out[scale - 1:] = c[scale - 1:] - np.concatenate([np.zeros((1,) + x.shape[1:]), c[:-scale]])
    bad = n[scale - 1:] - np.concatenate([np.zeros((1,) + x.shape[1:]), n[:-scale]]) > 0
    out[scale - 1:][bad] = np.nan
    return out


def _cal_mask(nt, start_year, cal):
    years = start_year + np.arange(nt) // 12
    return (years >= cal[0]) & (years <= cal[1])


Z_LIMIT = 3.09  # the +/-3.09 clip climate-indices applies to SPI/SPEI


def _to_z(p):
    from scipy.special import ndtri
    with np.errstate(invalid="ignore"):
        return np.clip(ndtri(p), -Z_LIMIT, Z_LIMIT)


def spi_builtin(precip, scale, start_year, cal):
    from scipy.special import gammainc
    x = rolling_sum(precip, scale)
    nt = x.shape[0]
    calm = _cal_mask(nt, start_year, cal)
    out = np.full(x.shape, np.nan)
    for m in range(12):
        idx = np.arange(m, nt, 12)
        xm = x[idx]
        ref = xm[calm[idx]]
        nvalid = np.isfinite(ref).sum(0)
        q = np.where(nvalid > 0, (ref == 0).sum(0) / np.maximum(nvalid, 1), np.nan)
        pos = np.where(ref > 0, ref, np.nan)
        mean = np.nanmean(pos, 0)
        A = np.log(mean) - np.nanmean(np.log(pos), 0)  # Thom (1958) MLE approximation
        alpha = (1 + np.sqrt(1 + 4 * A / 3)) / (4 * A)
        beta = mean / alpha
        with np.errstate(invalid="ignore", divide="ignore"):
            g = gammainc(alpha, np.where(xm > 0, xm, 0) / beta)
        p = q + (1 - q) * np.where(xm > 0, g, 0)
        z = _to_z(p)
        z[~np.isfinite(xm)] = np.nan
        out[idx] = z
    return out


def _glo_params(ref):
    """Generalised logistic (Hosking's GLO, the "log-logistic" of the R SPEI package)
    fitted by unbiased L-moments. ref: (n, ...) values for one calendar month.
    Returns loc, scale, shape."""
    s = np.sort(ref, axis=0)  # NaN sort last
    n = np.isfinite(s).sum(0).astype("float64")
    i = np.arange(1, s.shape[0] + 1, dtype="float64").reshape((-1,) + (1,) * (s.ndim - 1))
    x = np.where(i <= n, s, 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        b0 = x.sum(0) / n
        b1 = ((i - 1) / (n - 1) * x).sum(0) / n
        b2 = ((i - 1) * (i - 2) / ((n - 1) * (n - 2)) * x).sum(0) / n
        l1, l2, l3 = b0, 2 * b1 - b0, 6 * b2 - 6 * b1 + b0
        k = -(l3 / l2)
        small = np.abs(k) < 1e-6
        kk = np.where(small, 1.0, k * np.pi / np.sin(k * np.pi))
        scale = l2 / kk
        loc = np.where(small, l1, l1 - scale * (1 - kk) / np.where(small, 1, k))
    bad = (n < 10) | ~(scale > 0) | ~(np.abs(k) < 1)
    return np.where(bad, np.nan, loc), np.where(bad, np.nan, scale), np.where(bad, np.nan, k)


def spei_builtin(precip, pet, scale, start_year, cal):
    d = rolling_sum(precip - pet, scale)
    nt = d.shape[0]
    calm = _cal_mask(nt, start_year, cal)
    out = np.full(d.shape, np.nan)
    for m in range(12):
        idx = np.arange(m, nt, 12)
        dm = d[idx]
        loc, sc, k = _glo_params(dm[calm[idx]])
        with np.errstate(invalid="ignore", divide="ignore", over="ignore"):
            z = (dm - loc) / sc
            y = np.where(np.abs(k) < 1e-6, z, -np.log(np.maximum(0.0, 1.0 - k * z)) / k)
            F = 1.0 / (1.0 + np.exp(-y))
        zz = _to_z(F)
        zz[~np.isfinite(dm) | ~np.isfinite(F)] = np.nan
        out[idx] = zz
    return out


def _as3d(a):
    a = np.asarray(a, dtype="float64")
    if a.ndim == 1:
        return a[:, None, None], (lambda r: r[:, 0, 0])
    if a.ndim == 2:
        return a[:, :, None], (lambda r: r[:, :, 0])
    return a, (lambda r: r)


def spi(precip, scale, start_year, cal=(1991, 2020), backend="auto"):
    """SPI for a (time, ...) monthly block whose first month is January of start_year."""
    p, back = _as3d(precip)
    if backend_name(backend) == "builtin":
        return back(spi_builtin(p, scale, start_year, cal))
    indices, compute = _ci()
    z = indices.spi(p, scale, indices.Distribution.gamma, start_year, cal[0], cal[1],
                    compute.Periodicity.monthly, spatial_time_major=True)
    return back(np.asarray(z, dtype="float64"))


def spei(precip, pet, scale, start_year, cal=(1991, 2020), backend="auto"):
    p, back = _as3d(precip)
    e, _ = _as3d(pet)
    if backend_name(backend) == "builtin":
        return back(spei_builtin(p, e, scale, start_year, cal))
    indices, compute = _ci()
    z = indices.spei(p, e, scale, indices.Distribution.loglogistic, compute.Periodicity.monthly,
                     start_year, cal[0], cal[1], spatial_time_major=True)
    return back(np.asarray(z, dtype="float64"))


def extraterrestrial_radiation(lat_deg, doy):
    """FAO-56 eq. 21, MJ m-2 day-1."""
    phi = np.radians(lat_deg)
    dr = 1 + 0.033 * np.cos(2 * np.pi * doy / 365)
    dec = 0.409 * np.sin(2 * np.pi * doy / 365 - 1.39)
    ws = np.arccos(np.clip(-np.tan(phi) * np.tan(dec), -1, 1))
    return (24 * 60 / np.pi) * 0.0820 * dr * (ws * np.sin(phi) * np.sin(dec)
                                              + np.cos(phi) * np.cos(dec) * np.sin(ws))


def pet_hargreaves_monthly(tmax, tmin, lat, start_year):
    """Monthly PET (mm) from monthly-mean daily Tmax/Tmin (degC), (time, y, x); lat (y, x)
    or scalar. Ra is taken at the 15th of each month."""
    tmax = np.asarray(tmax, "float64"); tmin = np.asarray(tmin, "float64")
    nt = tmax.shape[0]
    out = np.empty_like(tmax)
    for t in range(nt):
        y, m = start_year + t // 12, t % 12 + 1
        doy = (np.datetime64(f"{y:04d}-{m:02d}-15") - np.datetime64(f"{y:04d}-01-01")).astype(int) + 1
        ra = extraterrestrial_radiation(lat, doy)
        tmean = (tmax[t] + tmin[t]) / 2
        daily = 0.0023 * 0.408 * ra * (tmean + 17.8) * np.sqrt(np.clip(tmax[t] - tmin[t], 0, None))
        out[t] = daily * calendar.monthrange(y, m)[1]
    return out


# ---------------------------------------------------------------- drought events

def runs_1d(z, threshold=-1.0, min_duration=1):
    """Run theory (Yevjevich 1967): spells below threshold. Returns a list of dicts with
    start, end (inclusive indices), duration, magnitude (sum of threshold - z), intensity
    (magnitude / duration) and peak (min z). Missing values end a run."""
    try:
        from climate_indices.runs import identify_runs
        rs = identify_runs(np.asarray(z, "float64"), threshold=threshold, direction="below",
                           min_duration=min_duration)
        return [dict(start=int(rs.start_index[i]), end=int(rs.end_index[i]),
                     duration=int(rs.duration[i]), magnitude=float(rs.magnitude[i]),
                     intensity=float(rs.intensity[i]), peak=float(rs.peak_value[i]))
                for i in range(len(rs.duration))]
    except ImportError:
        pass
    out, s = [], None
    zz = np.asarray(z, "float64")
    for i, v in enumerate(list(zz) + [np.nan]):
        below = np.isfinite(v) and v < threshold
        if below and s is None:
            s = i
        elif not below and s is not None:
            seg = zz[s:i]
            if len(seg) >= min_duration:
                mag = float(np.sum(threshold - seg))
                out.append(dict(start=s, end=i - 1, duration=len(seg), magnitude=mag,
                                intensity=mag / len(seg), peak=float(seg.min())))
            s = None
    return out


def event_layers(z, threshold=-1.0, min_duration=2, since=0):
    """Per-pixel drought event summary from an index block (time, y, x), counting events
    that start at or after time index `since`.
    Returns dict of (y, x) arrays: n_events, longest, worst_peak, worst_magnitude,
    months_in_drought, current_run (months the latest run has lasted, 0 if none)."""
    nt, ny, nx = z.shape
    keys = ["n_events", "longest", "worst_peak", "worst_magnitude", "months_in_drought", "current_run"]
    L = {k: np.full((ny, nx), np.nan) for k in keys}
    last_valid = nt - 1
    while last_valid > 0 and not np.isfinite(z[last_valid]).any():
        last_valid -= 1
    for r in range(ny):
        for c in range(nx):
            s = z[:, r, c]
            if not np.isfinite(s).any():
                continue
            ev = [e for e in runs_1d(s, threshold, min_duration) if e["start"] >= since]
            L["n_events"][r, c] = len(ev)
            L["longest"][r, c] = max([e["duration"] for e in ev], default=0)
            L["worst_peak"][r, c] = min([e["peak"] for e in ev], default=np.nan)
            L["worst_magnitude"][r, c] = max([e["magnitude"] for e in ev], default=0)
            tail = s[since:]
            L["months_in_drought"][r, c] = np.sum(tail[np.isfinite(tail)] < threshold)
            k = 0
            for v in s[last_valid::-1]:
                if np.isfinite(v) and v < threshold:
                    k += 1
                else:
                    break
            L["current_run"][r, c] = k
    return L
