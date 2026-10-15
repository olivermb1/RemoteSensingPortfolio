"""Drought Check core: SPI/SPEI stacks, drought class map, area-in-drought series and
drought events for an area, from monthly rainfall (and optionally PET or temperature).

Pure numpy (+ scipy, or climate-indices when installed) so the QGIS script can call it
with arrays it read through GDAL.
"""
from __future__ import annotations

import numpy as np

from . import indices as I


def _pad_to_years(a, start_year, start_month):
    """Pad a (time, ...) monthly block with NaN so it starts in January and ends in
    December. Returns padded block, first year, number of leading pad months."""
    lead = start_month - 1
    total = lead + a.shape[0]
    trail = (-total) % 12
    pad = [(lead, trail)] + [(0, 0)] * (a.ndim - 1)
    return np.pad(a.astype("float64"), pad, constant_values=np.nan), start_year, lead


def month_labels(start_year, start_month, n):
    out = []
    y, m = start_year, start_month
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def run(precip, start_year, start_month=1, *, pet=None, tmax=None, tmin=None, lat=None,
        scales=(1, 3, 6, 12), spei_scales=(3, 6, 12), calibration=(1991, 2020),
        class_scale=3, threshold=-1.0, min_duration=2, events_since=None, backend="auto"):
    """precip, pet, tmax, tmin: (time, y, x) monthly blocks on the same grid.
    lat: (y, x) pixel-centre latitudes (needed if PET is computed from tmax/tmin).

    Returns a dict with:
      months         labels 'YYYY-MM'
      spi[s], spei[s] (time, y, x) index blocks
      pet            (time, y, x) or None
      latest         dict(month, scale, z (y, x), cls (y, x)) for the last month with data
      area           list of per-month rows: AOI-mean rain, SPI of the AOI-mean rain,
                     share of valid pixels in each drought class
      events         drought events of the AOI-mean SPI at class_scale
      layers         per-pixel event summary at class_scale (dict of (y, x) arrays)
      info           backend, calibration, gaps
    """
    P = np.asarray(precip, "float64")
    nt = P.shape[0]
    months = month_labels(start_year, start_month, nt)
    Pp, y0, lead = _pad_to_years(P, start_year, start_month)
    yrs_avail = (start_year, start_year + (start_month - 1 + nt - 1) // 12)
    cal = (max(calibration[0], yrs_avail[0]), min(calibration[1], yrs_avail[1]))
    backend = I.backend_name(backend)

    def trim(z):
        return z[lead:lead + nt]

    if pet is None and tmax is not None and tmin is not None:
        if lat is None:
            raise ValueError("lat is needed to compute PET from temperature")
        Tx, _, _ = _pad_to_years(np.asarray(tmax), start_year, start_month)
        Tn, _, _ = _pad_to_years(np.asarray(tmin), start_year, start_month)
        PETp = I.pet_hargreaves_monthly(Tx, Tn, lat, y0)
    elif pet is not None:
        PETp, _, _ = _pad_to_years(np.asarray(pet), start_year, start_month)
    else:
        PETp = None

    out = dict(months=months, spi={}, spei={}, pet=None if PETp is None else trim(PETp))
    for s in scales:
        out["spi"][s] = trim(I.spi(Pp, s, y0, cal, backend))
    if PETp is not None:
        for s in spei_scales:
            out["spei"][s] = trim(I.spei(Pp, PETp, s, y0, cal, backend))

    # AOI-mean rainfall and its SPI (the regional signal, not the mean of pixel SPIs)
    valid_px = np.isfinite(P).any(0)
    p_mean = np.array([np.nanmean(P[t][valid_px]) if np.isfinite(P[t][valid_px]).any() else np.nan
                       for t in range(nt)])
    pm_pad, _, _ = _pad_to_years(p_mean, start_year, start_month)
    spi_aoi = {s: trim(I.spi(pm_pad, s, y0, cal, backend)) for s in scales}

    z = out["spi"][class_scale]
    last = nt - 1
    while last > 0 and not np.isfinite(z[last]).any():
        last -= 1
    out["latest"] = dict(month=months[last], scale=class_scale, z=z[last], cls=I.classify(z[last]))

    rows = []
    for t in range(nt):
        zt = z[t][valid_px]
        n = np.isfinite(zt).sum()
        row = dict(month=months[t], rain_mm=p_mean[t])
        for s in scales:
            row[f"spi{s}_aoi"] = spi_aoi[s][t]
        row[f"spi{class_scale}_pixel_mean"] = np.nanmean(zt) if n else np.nan
        for name, lo in (("moderate_or_worse", -1.0), ("severe_or_worse", -1.5), ("extreme", -2.0)):
            row[f"pct_area_{name}"] = 100.0 * np.sum(zt[np.isfinite(zt)] <= lo) / n if n else np.nan
        rows.append(row)
    out["area"] = rows

    ev = I.runs_1d(spi_aoi[class_scale], threshold, min_duration)
    for e in ev:
        e["start_month"], e["end_month"] = months[e["start"]], months[e["end"]]
        e["peak_month"] = months[e["start"] + int(np.nanargmin(spi_aoi[class_scale][e["start"]:e["end"] + 1]))]
    out["events"] = ev

    since = 0
    if events_since:
        since = next((i for i, m in enumerate(months) if m >= events_since), 0)
    out["layers"] = I.event_layers(z, threshold, min_duration, since)

    gaps = [months[t] for t in range(nt) if not np.isfinite(P[t][valid_px]).any()]
    out["info"] = dict(backend=backend, calibration=list(cal), class_scale=class_scale,
                       threshold=threshold, min_duration=min_duration,
                       events_since=months[since], first_month=months[0], last_month=months[-1],
                       latest_month=months[last], missing_months=gaps,
                       pet="given" if pet is not None else ("hargreaves" if PETp is not None else None))
    return out


def findings(res, top=5):
    """Plain-language findings for the report."""
    f = []
    sc = res["info"]["class_scale"]
    lat = res["latest"]
    cls = lat["cls"][lat["cls"] != -99]
    if cls.size:
        dr = 100 * np.mean(cls <= -1)
        f.append(f"{lat['month']}: SPI-{sc} puts {dr:.0f}% of the area in moderate or worse drought "
                 f"(median SPI {np.nanmedian(lat['z']):.2f}).")
    ev = sorted(res["events"], key=lambda e: -e["magnitude"])[:top]
    if ev:
        f.append(f"Worst area-wide droughts by SPI-{sc} magnitude: " + "; ".join(
            f"{e['start_month']} to {e['end_month']} ({e['duration']} months, peak {e['peak']:.2f})" for e in ev) + ".")
    cur = res["layers"]["current_run"]
    if np.nanmax(cur) > 0:
        f.append(f"{100 * np.nanmean(cur > 0):.0f}% of pixels are in a drought spell that is still running "
                 f"(longest {int(np.nanmax(cur))} months).")
    if res["info"]["missing_months"]:
        f.append("Months with no rainfall data (indices that span them are blank): "
                 + ", ".join(res["info"]["missing_months"]) + ".")
    return f
