"""Bit decoding and mask building. numpy only, no GIS libraries."""

import numpy as np

KEEP, MASKED, NODATA = 1, 0, 255


_BITS = {"uint8": 8, "int16": 16, "uint16": 16, "int32": 32, "uint32": 32}


def _as_unsigned(qa, product):
    """View signed QA values (MODIS SummaryQA is int16, fill -1) as unsigned at the product's bit depth."""
    qa = np.asarray(qa)
    if qa.dtype.kind == "i":
        return qa.astype(np.int64) & ((1 << _BITS[product.dtype]) - 1)
    return qa


def decode_field(qa, product, field):
    """Value of one field (start bit, n bits) for every pixel."""
    start, n = product.fields[field]["bits"]
    return (_as_unsigned(qa, product) >> start) & ((1 << n) - 1)


def flag_array(qa, product, flag):
    """Boolean array, True where the flag is set."""
    f = product.flags[flag]
    return np.isin(decode_field(qa, product, f["field"]), f["in"])


def fill_array(qa, product, extra_nodata=None):
    """True where the QA layer itself says there is no data."""
    raw = np.asarray(qa)
    fill = np.zeros(raw.shape, bool)
    vals = list(product.fill)
    if extra_nodata is not None:
        vals.append(extra_nodata)
    if vals:
        fill |= np.isin(raw, vals)
    if product.fill_rule:
        r = product.fill_rule
        fill |= np.isin(decode_field(qa, product, r["field"]), r["in"])
    return fill


def dilate(mask, radius):
    """Grow True areas by radius pixels with a square window (shift-and-or, no scipy)."""
    if radius <= 0:
        return mask
    out = mask.copy()
    h, w = mask.shape
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if dy == 0 and dx == 0:
                continue
            ys, yd = (slice(0, h - dy), slice(dy, h)) if dy >= 0 else (slice(-dy, h), slice(0, h + dy))
            xs, xd = (slice(0, w - dx), slice(dx, w)) if dx >= 0 else (slice(-dx, w), slice(0, w + dx))
            out[yd, xd] |= mask[ys, xs]
    return out


def build_mask(qa, product, drop=None, keep=None, buffer=0, extra_nodata=None):
    """Return a uint8 mask: 1 = usable, 0 = masked, 255 = no data.

    drop: flag or preset names; a pixel with any of them set is masked.
    keep: optional flag or preset names; if given, a pixel must have at least one
          of them set to be usable (for class layers like DSWx water or DIST status).
    buffer: grow the dropped area by this many pixels.
    """
    drop = product.resolve(drop if drop is not None else [product.default_preset])
    keep = product.resolve(keep) if keep else []
    bad = np.zeros(np.shape(qa), bool)
    for f in drop:
        bad |= flag_array(qa, product, f)
    fill = fill_array(qa, product, extra_nodata)
    bad &= ~fill
    if buffer:
        bad = dilate(bad, int(buffer)) & ~fill
    if keep:
        good = np.zeros(np.shape(qa), bool)
        for f in keep:
            good |= flag_array(qa, product, f)
        bad |= ~good
    out = np.where(bad, MASKED, KEEP).astype(np.uint8)
    out[fill] = NODATA
    return out


def flag_stats(qa, product, extra_nodata=None):
    """Per-flag pixel counts and shares of valid (non-fill) pixels."""
    fill = fill_array(qa, product, extra_nodata)
    valid = int((~fill).sum())
    rows = []
    for name, f in product.flags.items():
        n = int((flag_array(qa, product, name) & ~fill).sum())
        rows.append({"flag": name, "label": f["label"], "pixels": n,
                     "share_of_valid": round(n / valid, 4) if valid else 0.0})
    return {"valid_pixels": valid, "fill_pixels": int(fill.sum()), "flags": rows}


def mask_stats(mask):
    usable = int((mask == KEEP).sum())
    masked = int((mask == MASKED).sum())
    nodata = int((mask == NODATA).sum())
    valid = usable + masked
    return {"usable": usable, "masked": masked, "nodata": nodata,
            "usable_share_of_valid": round(usable / valid, 4) if valid else 0.0}


def apply_mask(data, mask, nodata):
    """Set data to nodata wherever mask is not 1. Works on (bands, rows, cols) or (rows, cols)."""
    data = np.array(data, copy=True)
    data[..., mask != KEEP] = nodata
    return data
