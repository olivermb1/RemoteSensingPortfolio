"""File-level operations shared by the command line and the QGIS plugin."""

import json
import os

import numpy as np

from . import core, io, style
from .registry import detect_product, get_product


def _product(qa_path, product):
    if product and product != "auto":
        return get_product(product)
    p = detect_product(qa_path)
    if p is None:
        raise ValueError(f"can't tell the product from '{os.path.basename(qa_path)}'; pass --product")
    return p


def _georef(src, fix_crs, product):
    """Return (Info to write with, crs check dict). fix_crs: 'auto' (HLS/OPERA only), 'yes', 'no'."""
    chk = src.crs_check()
    if fix_crs == "no":
        return src, dict(chk, applied=False)
    if fix_crs == "auto" and not product.is_hls_family:
        # Landsat Collection 2 uses northern zones south of the equator on purpose; say so quietly
        return src, {"needed": False, "applied": False, "reason": "not an HLS/OPERA product, CRS left as is",
                     "note": chk["reason"]}
    fixed, chk = src.fixed()
    return fixed, dict(chk, applied=chk["needed"])


def build(qa_path, out_path, product=None, drop=None, keep=None, buffer=0, fix_crs="auto", band=1,
          write_style=True, write_report=True):
    p = _product(qa_path, product)
    src = io.info(qa_path)
    qa = io.read(qa_path, band)
    drop_flags = p.resolve(drop if drop else [p.default_preset])
    keep_flags = p.resolve(keep) if keep else []
    mask = core.build_mask(qa, p, drop_flags, keep_flags, buffer)
    ref, chk = _georef(src, fix_crs, p)
    tags = {"QAMASK_PRODUCT": p.key, "QAMASK_DROP": ",".join(drop_flags), "QAMASK_KEEP": ",".join(keep_flags),
            "QAMASK_BUFFER": buffer, "QAMASK_VALUES": "1=usable 0=masked 255=no data", "QAMASK_SOURCE": os.path.basename(qa_path)}
    if chk.get("applied"):
        tags["QAMASK_CRS_FIX"] = chk["reason"]
    io.write(out_path, mask, ref, nodata=core.NODATA, colormap=io.MASK_COLORS, tags=tags)
    report = {"input": qa_path, "output": out_path, "product": p.key, "drop": drop_flags, "keep": keep_flags,
              "buffer": buffer, "crs": {"input_epsg": src.epsg, "output_epsg": ref.epsg, **chk},
              "mask": core.mask_stats(mask), "flags": core.flag_stats(qa, p)}
    if write_style:
        report["style"] = style.write_mask_qml(out_path)
    if write_report:
        with open(os.path.splitext(out_path)[0] + ".json", "w") as fh:
            json.dump(report, fh, indent=1)
    return report


def apply(data_path, mask_path, out_path, nodata=None):
    """Copy data_path with every pixel the mask doesn't mark usable set to nodata. Grids must match."""
    d, m = io.info(data_path), io.info(mask_path)
    if (d.width, d.height) != (m.width, m.height):
        raise ValueError("data and mask have different sizes; build the mask from this scene's own QA layer")
    if any(abs(a - b) > 1e-6 for a, b in zip(d.gt, m.gt)):
        fixed, chk = d.fixed()
        if not (chk["needed"] and all(abs(a - b) <= 1e-6 for a, b in zip(fixed.gt, m.gt))):
            raise ValueError("data and mask are on different grids")
        d = fixed  # the mask had the southern-hemisphere fix; give the output the same fix
    data = io.read_all(data_path)
    mask = io.read(mask_path)
    if nodata is None:
        nodata = d.nodata if d.nodata is not None else (0 if data.dtype.kind == "u" else -9999)
    io.write(out_path, core.apply_mask(data, mask, nodata), d, nodata=nodata, tags=d.tags)
    return {"input": data_path, "mask": mask_path, "output": out_path, "nodata": nodata, **core.mask_stats(mask)}


def decode(qa_path, out_path, product=None, fix_crs="auto", band=1):
    """Write every field of the QA layer as its own band, named after the field."""
    p = _product(qa_path, product)
    src = io.info(qa_path)
    qa = io.read(qa_path, band)
    fill = core.fill_array(qa, p)
    names = list(p.fields)
    arr = np.stack([core.decode_field(qa, p, f) for f in names]).astype(np.uint8)
    arr[:, fill] = 255
    ref, chk = _georef(src, fix_crs, p)
    io.write(out_path, arr, ref, nodata=255, band_names=names, tags={"QAMASK_PRODUCT": p.key})
    return {"output": out_path, "product": p.key, "bands": names, "crs": chk}


def fix_crs(in_path, out_path, vrt=False, force=False):
    """Write a relabelled copy (or a VRT) of a southern-hemisphere HLS/OPERA file. No resampling."""
    src = io.info(in_path)
    fixed, chk = src.fixed()
    if not chk["needed"]:
        return {"input": in_path, "output": None, **chk}
    p = detect_product(in_path)
    if not force and not (p and p.is_hls_family) and "HLS" not in os.path.basename(in_path):
        return {"input": in_path, "output": None, "needed": True,
                "reason": chk["reason"] + ". Not an HLS/OPERA file name, so skipped; pass --force to relabel anyway "
                          "(Landsat Collection 2 uses northern zones on purpose)"}
    if vrt:
        io.write_fix_vrt(out_path, fixed, in_path)
    else:
        io.write(out_path, io.read_all(in_path), fixed, nodata=src.nodata, tags=src.tags)
    return {"input": in_path, "output": out_path, **chk}
