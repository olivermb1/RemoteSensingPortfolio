"""Greenness link: is vegetation browning because of drought, or for some other reason?

Pairs a monthly NDVI standardised anomaly stack with SPI on the same grid and a land
cover map, and reports, per land cover class and per pixel:

  * how strongly greenness follows rainfall (correlation of NDVI anomaly with SPI, by
    SPI scale and lag), so you know which classes are rain-fed and how fast they respond;
  * a diagnosis for a target month:
        1 drought-linked browning   NDVI anomaly <= -1 and SPI <= -1
        2 browning without drought  NDVI anomaly <= -1 and SPI >  -0.5   (look here first:
                                    clearing, fire, harvest timing, flooding, degradation)
        3 holding up in drought     SPI <= -1 and NDVI anomaly >= -0.5  (irrigation,
                                    groundwater, deep roots, or a lagged response)
        4 browning, mild dryness    NDVI anomaly <= -1 and -1 < SPI <= -0.5
        0 none of the above, -1 no data;
  * "unexplained" browning: the mean of NDVI anomaly minus what that pixel's own
    rainfall response predicts, over the most recent months. A pixel whose greenness
    has dropped further than its rain explains, month after month, is a land change
    candidate, not a drought story.

Pure numpy; the caller puts all inputs on one grid with matching months.
"""
from __future__ import annotations

import warnings

import numpy as np

warnings.filterwarnings("ignore", "Mean of empty slice", RuntimeWarning)
warnings.filterwarnings("ignore", "All-NaN slice", RuntimeWarning)

DIAG = {-1: "No data", 0: "No signal", 1: "Drought-linked browning", 2: "Browning without drought",
        3: "Holding up in drought", 4: "Browning, mild dryness"}
DIAG_COLORS = {-1: "#ffffff", 0: "#e4e3df", 1: "#c0392b", 2: "#7b3fa0", 3: "#2a78d6", 4: "#eb9f6c"}
SKIP_CLASSES_DEFAULT = {0, 50, 70, 80}  # nodata, built-up, snow/ice, water (WorldCover codes)


def _lag(a, k):
    """Shift a (time, ...) block so that out[t] = a[t - k]."""
    if k == 0:
        return a
    out = np.full_like(a, np.nan)
    out[k:] = a[:-k]
    return out


def _corr(x, y, axis=0):
    ok = np.isfinite(x) & np.isfinite(y)
    n = ok.sum(axis)
    x = np.where(ok, x, np.nan); y = np.where(ok, y, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        mx, my = np.nanmean(x, axis), np.nanmean(y, axis)
        dx, dy = x - np.expand_dims(mx, axis), y - np.expand_dims(my, axis)
        sxy = np.nansum(dx * dy, axis)
        sxx, syy = np.nansum(dx * dx, axis), np.nansum(dy * dy, axis)
        r = sxy / np.sqrt(sxx * syy)
        slope = sxy / sxx
        icpt = my - slope * mx
    return r, slope, icpt, n


def diagnose(ndvi, spi, browning=-1.0, drought=-1.0, normal_spi=-0.5, holding=-0.5):
    d = np.zeros(ndvi.shape, "int8")
    ok = np.isfinite(ndvi) & np.isfinite(spi)
    d[~ok] = -1
    brown = ok & (ndvi <= browning)
    dry = ok & (spi <= drought)
    d[brown & dry] = 1
    d[brown & (spi > normal_spi)] = 2
    d[ok & dry & (ndvi >= holding)] = 3
    d[brown & (spi > drought) & (spi <= normal_spi)] = 4
    return d


def run(ndvi, months, spi_by_scale, landcover, legend=None, *, target=None, scale="auto", lag="auto",
        lags=(0, 1, 2), recent=12, clip=4.0, min_class_pixels=50, landchange_months=3,
        skip_classes=SKIP_CLASSES_DEFAULT, browning=-1.0, drought=-1.0, normal_spi=-0.5, holding=-0.5):
    """ndvi: (T, y, x) NDVI standardised anomaly; months: T labels 'YYYY-MM';
    spi_by_scale: {scale: (T, y, x)} SPI on the same grid and months;
    landcover: (y, x) class codes; legend: {code: (name, colour)}."""
    legend = legend or {}
    N = np.clip(np.asarray(ndvi, "float64"), -clip, clip)
    T = N.shape[0]
    lc = np.asarray(landcover)
    classes = [int(c) for c in np.unique(lc) if int(c) not in skip_classes
               and np.sum(lc == c) >= min_class_pixels]
    name = lambda c: legend.get(c, (f"class {c}", "#888888"))[0]

    # 1. class-level response: class-mean NDVI anomaly vs class-mean SPI, by scale and lag
    lag_rows, series = [], {}
    for c in classes:
        m = lc == c
        n_series = np.array([np.nanmean(N[t][m]) if np.isfinite(N[t][m]).any() else np.nan for t in range(T)])
        series[c] = dict(ndvi=n_series)
        for s, Z in spi_by_scale.items():
            z_series = np.array([np.nanmean(Z[t][m]) if np.isfinite(Z[t][m]).any() else np.nan for t in range(T)])
            series[c][f"spi{s}"] = z_series
            for k in lags:
                r, b, _, n = _corr(n_series, _lag(z_series, k))
                lag_rows.append(dict(class_code=c, class_name=name(c), spi_scale=s, lag_months=k,
                                     r=float(r), slope=float(b), n_months=int(n)))

    # 2. pick one scale and lag for the pixel layers: best median r over the classes
    combos = {}
    for row in lag_rows:
        if (scale == "auto" or row["spi_scale"] == int(scale)) and (lag == "auto" or row["lag_months"] == int(lag)):
            combos.setdefault((row["spi_scale"], row["lag_months"]), []).append(row["r"])
    (s_use, k_use) = max(combos, key=lambda kv: np.nanmedian(combos[kv]))
    Z = _lag(np.asarray(spi_by_scale[s_use], "float64"), k_use)

    # 3. per-pixel fit on the baseline (everything before the recent window)
    tgt = T - 1 if target is None else months.index(target)
    rec0 = max(0, tgt - recent + 1)
    base = slice(0, rec0)
    r, b, a, n = _corr(N[base], Z[base])
    pred = a[None] + b[None] * Z[rec0:tgt + 1]
    resid = N[rec0:tgt + 1] - pred
    with np.errstate(invalid="ignore"):
        unexplained = np.nanmean(resid, 0)
    unexplained[n < 24] = np.nan

    D_recent = diagnose(N[rec0:tgt + 1], Z[rec0:tgt + 1], browning, drought, normal_spi, holding)
    nonclim = np.sum(D_recent == 2, 0).astype("float64")
    diag_t = diagnose(N[tgt], Z[tgt], browning, drought, normal_spi, holding)
    landchange = ((nonclim >= landchange_months) & (unexplained <= -1.0)).astype("uint8")
    skip = np.isin(lc, list(skip_classes))
    for arr in (r, b, unexplained, nonclim):
        arr[skip] = np.nan
    diag_t[skip] = -1
    landchange[skip] = 0

    # 4. per-class summary for the target month
    class_rows = []
    for c in classes:
        m = (lc == c)
        best = max((x for x in lag_rows if x["class_code"] == c), key=lambda x: x["r"] if np.isfinite(x["r"]) else -9)
        dv = diag_t[m]
        valid = dv >= 0
        row = dict(class_code=c, class_name=name(c), pixels=int(m.sum()),
                   ndvi_anom_target=float(np.nanmean(N[tgt][m])), spi_target=float(np.nanmean(Z[tgt][m])),
                   median_pixel_r=float(np.nanmedian(r[m])), pct_rain_sensitive=float(100 * np.nanmean(r[m] > 0.3)),
                   best_scale=best["spi_scale"], best_lag=best["lag_months"], best_r=best["r"],
                   mean_unexplained_recent=float(np.nanmean(unexplained[m])),
                   pct_landchange_flag=float(100 * landchange[m].mean()))
        for code in (1, 2, 3, 4):
            row[f"pct_{DIAG[code].lower().replace(' ', '_').replace(',', '')}"] = \
                float(100 * np.sum(dv == code) / max(valid.sum(), 1))
        class_rows.append(row)

    return dict(months=months, target=months[tgt], recent=(months[rec0], months[tgt]),
                scale=s_use, lag=k_use, lag_rows=lag_rows, class_rows=class_rows, series=series,
                classes=classes, legend=legend,
                layers=dict(r=r, slope=b, n_baseline=n.astype("float64"), unexplained_recent=unexplained,
                            nonclimatic_months_recent=nonclim, diagnosis_target=diag_t.astype("float64"),
                            landchange_flag=landchange.astype("float64")),
                ndvi_target=N[tgt], spi_target=Z[tgt])


def findings(res):
    f = [f"Greenness follows SPI-{res['scale']} best, with a {res['lag']}-month lag (median over classes)."]
    rows = sorted(res["class_rows"], key=lambda r: -r["best_r"])
    if rows:
        f.append("Most rain-driven classes: " + "; ".join(
            f"{r['class_name']} r={r['best_r']:.2f} (SPI-{r['best_scale']}, lag {r['best_lag']})" for r in rows[:3]) + ".")
    tot = sum(r["pixels"] for r in res["class_rows"])
    if tot:
        w = lambda key: sum(r[key] * r["pixels"] for r in res["class_rows"]) / tot
        f.append(f"{res['target']}: {w('pct_drought-linked_browning'):.0f}% of vegetated pixels show drought-linked browning, "
                 f"{w('pct_browning_without_drought'):.0f}% browning without drought, "
                 f"{w('pct_holding_up_in_drought'):.0f}% holding up in drought.")
        lc = w("pct_landchange_flag")
        f.append(f"{lc:.1f}% of vegetated pixels are land change candidates: browning without drought in several "
                 f"months from {res['recent'][0]} to {res['target']}, and on average at least 1 standard deviation "
                 f"browner than their own rainfall response predicts.")
    return f
