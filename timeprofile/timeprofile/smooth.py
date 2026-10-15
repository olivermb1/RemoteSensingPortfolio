"""Spike flags, a Whittaker smoother, and per-season summaries. numpy only."""

import datetime as dt

import numpy as np


def flag_spikes(dates, values, threshold=0.1, max_gap=40):
    """Indices of single-date spikes: a value that differs from BOTH neighbours by more
    than `threshold` in the same direction while the neighbours agree with each other
    (within `threshold`) and are each at most `max_gap` days away. That pattern is
    almost always a cloud or shadow the mask missed; a real change (harvest, fire,
    flooding) persists into the next date and is not flagged."""
    d = np.array([x.toordinal() for x in dates], float)
    v = np.asarray(values, float)
    out = []
    for i in range(1, len(v) - 1):
        a, b, c = v[i - 1], v[i], v[i + 1]
        if d[i] - d[i - 1] > max_gap or d[i + 1] - d[i] > max_gap:
            continue
        if abs(a - c) <= threshold and ((b < min(a, c) - threshold) or (b > max(a, c) + threshold)):
            out.append(i)
    return out


def _penta_solve(diag, off1, off2, rhs):
    """Solve a symmetric pentadiagonal system (LDL^T, no pivoting; the Whittaker
    matrix W + lam D'D is positive definite whenever 3+ weights are non-zero)."""
    n = len(diag)
    d = np.zeros(n)
    l1 = np.zeros(n)
    l2 = np.zeros(n)
    for i in range(n):
        d[i] = diag[i] - (l1[i - 1] ** 2 * d[i - 1] if i >= 1 else 0) - (l2[i - 2] ** 2 * d[i - 2] if i >= 2 else 0)
        if i + 1 < n:
            l1[i] = (off1[i] - (l1[i - 1] * l2[i - 1] * d[i - 1] if i >= 1 else 0)) / d[i]
        if i + 2 < n:
            l2[i] = off2[i] / d[i]
    y = np.zeros(n)
    for i in range(n):
        y[i] = rhs[i] - (l1[i - 1] * y[i - 1] if i >= 1 else 0) - (l2[i - 2] * y[i - 2] if i >= 2 else 0)
    x = y / d
    for i in range(n - 1, -1, -1):
        x[i] -= (l1[i] * x[i + 1] if i + 1 < n else 0) + (l2[i] * x[i + 2] if i + 2 < n else 0)
    return x


def whittaker(dates, values, lam=1000.0, max_gap=60):
    """Smooth curve on a daily grid (second-order Whittaker, weights 0 on days with
    no observation). lam=1000 smooths over roughly a month. The curve is split
    where clear observations are more than max_gap days apart, so it never
    invents a season across a long cloudy gap. Returns a list of (dates, values)
    segments."""
    if len(values) < 4:
        return []
    order = np.argsort([d.toordinal() for d in dates])
    dd = np.array([dates[i].toordinal() for i in order])
    vv = np.asarray(values, float)[order]
    cuts = np.where(np.diff(dd) > max_gap)[0] + 1
    segs = []
    for idx in np.split(np.arange(len(dd)), cuts):
        if len(idx) < 4:
            continue
        o = dd[idx] - dd[idx[0]]
        n = int(o[-1]) + 1
        w = np.zeros(n)
        y = np.zeros(n)
        np.add.at(w, o, 1.0)
        np.add.at(y, o, vv[idx])
        y = np.divide(y, w, out=np.zeros(n), where=w > 0)
        # D'D for second differences: bands [1,-2,1]
        dtd0 = np.full(n, 6.0)
        dtd0[[0, -1]] = 1
        dtd0[[1, -2]] = 5
        dtd1 = np.full(n - 1, -4.0)
        dtd1[[0, -1]] = -2
        dtd2 = np.ones(n - 2)
        z = _penta_solve(w + lam * dtd0, lam * dtd1, lam * dtd2, w * y)
        start = dd[idx[0]]
        segs.append(([dt.date.fromordinal(int(start + k)) for k in range(n)], z))
    return segs


def season_of(date, start_month=1):
    """Season label: the calendar year when start_month is 1, else e.g. '2023-24'
    for a season starting in October 2023."""
    if start_month == 1:
        return str(date.year)
    y = date.year if date.month >= start_month else date.year - 1
    return f"{y}-{str(y + 1)[2:]}"


def seasons(dates, values, curve=None, start_month=1):
    """Per-season summary: count, mean, and the peak and low (from the smooth curve
    if given, else from the observations)."""
    by = {}
    for d, v in zip(dates, values):
        by.setdefault(season_of(d, start_month), []).append((d, v))
    cur = {}
    for seg_d, seg_v in (curve or []):
        for d, v in zip(seg_d, seg_v):
            cur.setdefault(season_of(d, start_month), []).append((d, v))
    out = []
    for s in sorted(by):
        obs = by[s]
        src = cur.get(s) or obs
        hi = max(src, key=lambda t: t[1])
        lo = min(src, key=lambda t: t[1])
        out.append({"season": s, "n_clear": len(obs), "first": min(o[0] for o in obs).isoformat(),
                    "last": max(o[0] for o in obs).isoformat(), "mean": float(np.mean([o[1] for o in obs])),
                    "peak": float(hi[1]), "peak_date": hi[0].isoformat(), "low": float(lo[1]),
                    "low_date": lo[0].isoformat(), "from": "smooth curve" if cur.get(s) else "observations"})
    return out
