"""Turn extracted rows into ChartWidget series. No Qt or QGIS imports, so it can be tested anywhere."""

import datetime as dt

from .timeprofile import smooth
from .timeprofile.report import PALETTE, marker_for, series


def _tip(r, feature):
    extra = f"<br>{r['n_clear']} of {r['n_valid']} pixels clear" if r["n_valid"] > 1 else ""
    flag = "<br><i>flagged: single-date spike</i>" if r.get("flag") == "spike" else ""
    return f"<b>{feature}</b><br>{r['date']} &middot; {r['sensor']}<br>{r['index']} = {r['value']:.3f}{extra}{flag}"


def time_series(rows, post, index, colors):
    """One chart series per feature. colors: {feature: hex}, kept stable as features come and go."""
    out = []
    for f in dict.fromkeys(r["feature"] for r in rows if r["index"] == index):
        d, v, rs = series(rows, f, index)
        pts = [(dd.toordinal(), vv, _tip(r, f), r.get("flag") == "spike", marker_for(r["sensor"]))
               for dd, vv, r in zip(d, v, rs)]
        lines = [[(x.toordinal(), float(y)) for x, y in zip(sd, sv)]
                 for sd, sv in post.get((f, index), {}).get("curve", [])]
        out.append({"name": f, "color": colors.get(f, PALETTE[len(out) % len(PALETTE)]), "points": pts, "lines": lines})
    return out


def season_series(rows, post, index, feature, season_start=1, max_seasons=8):
    """One chart series per season of one feature, x = days since the season starts."""
    d, v, rs = series(rows, feature, index)

    def x_of(day):
        s0 = dt.date(day.year if day.month >= season_start else day.year - 1, season_start, 1)
        return (day - s0).days
    seasons = sorted({smooth.season_of(x, season_start) for x in d})[-max_seasons:]
    out = []
    for i, s in enumerate(seasons):
        pts = [(x_of(dd), vv, _tip(r, feature), r.get("flag") == "spike", marker_for(r["sensor"]))
               for dd, vv, r in zip(d, v, rs) if smooth.season_of(dd, season_start) == s]
        lines = []
        for sd, sv in post.get((feature, index), {}).get("curve", []):
            seg = [(x_of(x), float(y)) for x, y in zip(sd, sv) if smooth.season_of(x, season_start) == s]
            if seg:
                lines.append(seg)
        out.append({"name": s, "color": PALETTE[i], "points": pts, "lines": lines})
    return out
