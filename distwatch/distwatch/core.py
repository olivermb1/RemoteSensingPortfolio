"""The arithmetic of DIST Watch, on plain numpy arrays. No file or network access.

One tile at a time:
  1. qualifying()  which pixels count as loss under your rules today
  2. diff()        which of those were not reported on an earlier run
  3. label() and patch_stats()  group new pixels into patches
  4. area_rows()   per-area totals
"""

from collections import deque

import numpy as np

from . import products as P


def qualifying(status, anom_max, dist_date, *, level="confirmed", min_loss=50, since=None,
               forest=None, codes=None):
    """Boolean mask of pixels that count as loss.

    level      "first", "provisional" or "confirmed" (see products.LEVELS)
    min_loss   minimum VEG-ANOM-MAX, percent vegetation cover lost (0 to keep all)
    since      ISO date or day number; only disturbances first detected after it
    forest     optional boolean mask, True where land was forest at the baseline
    """
    codes = codes if codes is not None else P.LEVELS[level]
    m = np.isin(status, list(codes))
    if min_loss:
        m &= (anom_max >= min_loss) & (anom_max != P.NODATA["VEG-ANOM-MAX"])
    if since is not None:
        day = since if isinstance(since, (int, np.integer)) else P.date_to_day(since)
        m &= dist_date > day
    if forest is not None:
        m &= forest.astype(bool)
    return m


def diff(qual, reported):
    """Split today's loss into new and already-reported pixels.

    reported is the uint16 run number at which each pixel was first reported
    (0 = never). Returns (new, old, withdrawn): withdrawn pixels were reported
    before but no longer qualify, which happens when a provisional alert is
    dropped or the rules were tightened.
    """
    seen = reported > 0
    return qual & ~seen, qual & seen, seen & ~qual


def label(mask, connectivity=8):
    """Label connected patches of True pixels. Returns (labels int32, count).

    Uses scipy when it is installed, otherwise a breadth-first search, which is
    fine for the sparse masks loss alerts produce.
    """
    try:
        from scipy import ndimage
        st = np.ones((3, 3), bool) if connectivity == 8 else None
        lab, n = ndimage.label(mask, structure=st)
        return lab.astype("int32"), int(n)
    except ImportError:
        pass
    h, w = mask.shape
    lab = np.zeros(mask.shape, "int32")
    if connectivity == 8:
        steps = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    else:
        steps = [(-1, 0), (0, -1), (0, 1), (1, 0)]
    n = 0
    for r0, c0 in zip(*np.nonzero(mask)):
        if lab[r0, c0]:
            continue
        n += 1
        lab[r0, c0] = n
        q = deque([(r0, c0)])
        while q:
            r, c = q.popleft()
            for dr, dc in steps:
                rr, cc = r + dr, c + dc
                if 0 <= rr < h and 0 <= cc < w and mask[rr, cc] and not lab[rr, cc]:
                    lab[rr, cc] = n
                    q.append((rr, cc))
    return lab, n


def drop_small(labels, min_pixels):
    """Remove patches smaller than min_pixels and renumber the rest 1..n."""
    if labels.max() == 0:
        return labels, 0
    sizes = np.bincount(labels.ravel())
    keep = sizes >= max(min_pixels, 1)
    keep[0] = False
    newid = np.zeros(len(sizes), "int32")
    newid[keep] = np.arange(1, keep.sum() + 1)
    return newid[labels], int(keep.sum())


def patch_stats(labels, n, anom_max, dist_date, conf=None):
    """One dict per patch: pixels, ha, first/last detection dates, loss stats."""
    if n == 0:
        return []
    idx = labels.ravel()
    sel = idx > 0
    ids = idx[sel]
    px = np.bincount(ids, minlength=n + 1)
    an = anom_max.ravel()[sel].astype("float64")
    dd = dist_date.ravel()[sel].astype("int64")
    an_sum = np.bincount(ids, weights=an, minlength=n + 1)
    an_max = np.zeros(n + 1)
    np.maximum.at(an_max, ids, an)
    d_min = np.full(n + 1, np.iinfo("int64").max)
    d_max = np.full(n + 1, -1)
    np.minimum.at(d_min, ids, dd)
    np.maximum.at(d_max, ids, dd)
    rows, cols = np.nonzero(labels)
    r_sum = np.bincount(labels[rows, cols], weights=rows, minlength=n + 1)
    c_sum = np.bincount(labels[rows, cols], weights=cols, minlength=n + 1)
    if conf is not None:
        cf = np.zeros(n + 1)
        np.maximum.at(cf, ids, conf.ravel()[sel].astype("float64"))
    out = []
    for i in range(1, n + 1):
        d = {
            "patch": i,
            "pixels": int(px[i]),
            "area_ha": round(float(px[i]) * P.PIXEL_HA, 2),
            "first_detected": P.day_to_date(d_min[i]).isoformat(),
            "last_first_detected": P.day_to_date(d_max[i]).isoformat(),
            "mean_loss_pct": round(float(an_sum[i] / px[i]), 1),
            "max_loss_pct": int(an_max[i]),
            "row": float(r_sum[i] / px[i]),
            "col": float(c_sum[i] / px[i]),
        }
        if conf is not None:
            d["max_anomalous_obs"] = int(cf[i])
        out.append(d)
    return out


def owner_mask(lon, lat, tile_center, other_centers):
    """True where this tile's centre is the nearest of all loaded tiles' centres.

    MGRS tiles overlap by several km, so the same loss shows up in two tiles.
    Giving each location to its nearest tile centre counts it once.
    """
    cos = np.cos(np.radians(lat))
    def d2(c):
        return ((lon - c[0]) * cos) ** 2 + (lat - c[1]) ** 2
    mine = d2(tile_center)
    keep = np.ones(np.shape(lon), bool)
    for c in other_centers:
        keep &= mine <= d2(c)
    return keep


def area_counts(area_mask, new, cumulative, anom_max, dist_date, owned=None):
    """Totals for one area on one tile window. All inputs share the window shape."""
    m = area_mask if owned is None else area_mask & owned
    nw = new & m
    cu = cumulative & m
    out = {"new_px": int(nw.sum()), "cum_px": int(cu.sum())}
    if out["new_px"]:
        dd = dist_date[nw]
        out["new_first"] = int(dd.min())
        out["new_last"] = int(dd.max())
        out["new_loss_sum"] = float(anom_max[nw].astype("float64").sum())
    return out


def merge_counts(parts):
    """Add up area_counts() results from several tiles."""
    tot = {"new_px": 0, "cum_px": 0, "new_loss_sum": 0.0}
    firsts, lasts = [], []
    for p in parts:
        tot["new_px"] += p["new_px"]
        tot["cum_px"] += p["cum_px"]
        tot["new_loss_sum"] += p.get("new_loss_sum", 0.0)
        if "new_first" in p:
            firsts.append(p["new_first"])
            lasts.append(p["new_last"])
    tot["new_first"] = min(firsts) if firsts else None
    tot["new_last"] = max(lasts) if lasts else None
    return tot


def area_row(name, area_ha, counts, patches):
    """The per-area summary line written to area_summary.csv."""
    new_ha = counts["new_px"] * P.PIXEL_HA
    cum_ha = counts["cum_px"] * P.PIXEL_HA
    return {
        "area": name,
        "area_ha": round(area_ha, 1),
        "new_loss_ha": round(new_ha, 2),
        "new_patches": patches,
        "new_loss_pct_of_area": round(100 * new_ha / area_ha, 3) if area_ha else None,
        "total_loss_ha": round(cum_ha, 2),
        "total_loss_pct_of_area": round(100 * cum_ha / area_ha, 3) if area_ha else None,
        "new_mean_loss_pct": round(counts["new_loss_sum"] / counts["new_px"], 1) if counts["new_px"] else None,
        "new_first_detected": P.day_to_date(counts["new_first"]).isoformat() if counts["new_first"] is not None else "",
        "new_last_detected": P.day_to_date(counts["new_last"]).isoformat() if counts["new_last"] is not None else "",
        "flag": "NEW LOSS" if counts["new_px"] else "",
    }
