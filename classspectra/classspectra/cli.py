"""Command line: classspectra IMAGE LANDCOVER [options]."""

import argparse
import csv
import os

import numpy as np

from . import core, report
from .legends import BROAD, BROAD_CODES, class_name
from .sensors import PRESETS, RED_NIR


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="classspectra",
        description="Per-class spectral signatures (median and spread) from an image and a land cover map.")
    p.add_argument("image", help="multiband reflectance GeoTIFF (bands in preset order)")
    p.add_argument("landcover", help="land cover map GeoTIFF (any CRS / resolution)")
    p.add_argument("--legend", default="worldcover", choices=["worldcover", "io", "dynamicworld", "none"])
    p.add_argument("--compare", help="second land cover map to compare against")
    p.add_argument("--compare-legend", default="worldcover", choices=["worldcover", "io", "dynamicworld"])
    p.add_argument("--map-names", nargs=2, default=None, metavar=("A", "B"), help="labels for the two maps")
    p.add_argument("--preset", default="s2_l2a", choices=list(PRESETS) + ["none"])
    p.add_argument("--scale", type=float, help="override reflectance scale")
    p.add_argument("--offset", type=float, help="override reflectance offset")
    p.add_argument("--nodata", type=float, help="override image nodata")
    p.add_argument("--bbox", nargs=4, type=float, metavar=("W", "S", "E", "N"), help="area in lon/lat")
    p.add_argument("--mask", help="quality raster (e.g. Sentinel-2 SCL, HLS Fmask)")
    p.add_argument("--mask-invalid", default="", help="comma list of mask values to reject, e.g. 0,1,3,8,9,10")
    p.add_argument("--mask-bits", type=int, default=0, help="reject pixels with any of these bits set (HLS Fmask: 15)")
    p.add_argument("--erosion", type=int, default=1, help="drop pixels within N pixels of another class (0 = off)")
    p.add_argument("--min-purity", type=float, default=0.75, help="when the map is finer than the image")
    p.add_argument("--outlier-z", type=float, default=3.5, help="robust z threshold, 0 = off")
    p.add_argument("--min-pixels", type=int, default=30)
    p.add_argument("--max-samples", type=int, default=100_000)
    p.add_argument("--no-separability", action="store_true")
    p.add_argument("--title", default="")
    p.add_argument("--out", default="classspectra_out")
    return p.parse_args(argv)


def main(argv=None):
    a = parse_args(argv)
    from . import io  # rasterio only needed for standalone use

    preset = PRESETS.get(a.preset, {"bands": None, "wavelengths": None, "scale": 1.0, "offset": 0.0, "nodata": None})
    scale = a.scale if a.scale is not None else preset["scale"]
    offset = a.offset if a.offset is not None else preset["offset"]
    nodata = a.nodata if a.nodata is not None else preset["nodata"]

    img, prof = io.read_image(a.image, a.bbox, scale, offset, nodata)
    names = preset["bands"] or [d or f"band{i+1}" for i, d in enumerate(prof["descriptions"])]
    if len(names) != img.shape[0]:
        raise SystemExit(f"image has {img.shape[0]} bands but preset {a.preset} lists {len(names)}")
    wl = preset["wavelengths"]
    red_nir = None
    if a.preset in RED_NIR:
        r, n = RED_NIR[a.preset]
        red_nir = (names.index(r), names.index(n))

    valid = np.all(np.isfinite(img), axis=0)
    neg = float(np.mean(img[:, valid] < 0)) if valid.any() else 0.0
    if neg > 0.02:
        print(f"WARNING: {neg*100:.0f}% of reflectance values are negative; check --preset / --offset "
              "(Sentinel-2 offset -0.1 applied twice or to already-harmonized data?)")
    if a.mask:
        invalid = [int(v) for v in a.mask_invalid.split(",") if v.strip()]
        valid &= io.read_mask(a.mask, prof, invalid, a.mask_bits)

    labels, purity = io.read_labels(a.landcover, prof)
    legend = a.legend
    opts = dict(erosion=a.erosion, purity=purity, min_purity=a.min_purity, outlier_z=a.outlier_z,
                min_pixels=a.min_pixels, max_samples=a.max_samples, red_nir=red_nir, valid=valid & (labels > 0))

    os.makedirs(a.out, exist_ok=True)
    print(f"image {img.shape[2]}x{img.shape[1]} px, {img.shape[0]} bands, "
          f"{valid.mean()*100:.1f}% valid after mask; map purity layer: {'yes' if purity is not None else 'no'}")

    res = core.class_signatures(img, labels, **opts)
    report.write_signatures_csv(os.path.join(a.out, "signatures.csv"), res, names, wl, legend)
    rows = report.summary_rows(res, legend)
    report.write_summary_csv(os.path.join(a.out, "class_summary.csv"), rows)
    report.plot_signatures(os.path.join(a.out, "signatures.png"), res, names, wl, legend, title=a.title)
    sep = None
    if not a.no_separability:
        cls, m = core.separability_matrix(res)
        report.write_separability_csv(os.path.join(a.out, "separability.csv"), cls, m, legend)
        report.plot_separability(os.path.join(a.out, "separability.png"), cls, m, legend)
        sep = {"classes": cls, "jm": m.tolist()}
    for r in rows:
        print(f"  {r['class_name']:<26} used {r['used']:>7,} of {r['pixels']:>8,}  "
              f"outliers {r['outlier_share']*100:4.1f}%  spread {r['spread']:.2f}  NDVI {r['ndvi_median']}  {r['warnings']}")

    summary = {"image": a.image, "landcover": a.landcover, "bbox": a.bbox, "preset": a.preset,
               "options": {k: v for k, v in vars(a).items() if k not in ("image", "landcover")},
               "classes": res, "separability": sep}

    if a.compare:
        summary["comparison"] = compare_maps(a, img, prof, labels, valid, names, wl, opts)
    report.write_json(os.path.join(a.out, "run.json"), summary)
    print(f"outputs in {a.out}/")


def compare_maps(a, img, prof, labels_a, valid, names, wl, opts):
    """Same image, two maps, recoded to shared broad classes."""
    from . import io
    labels_b, purity_b = io.read_labels(a.compare, prof)
    la, lb = (a.map_names or ("Map A", "Map B"))
    ba = core.to_broad(labels_a, BROAD[a.legend], BROAD_CODES)
    bb = core.to_broad(labels_b, BROAD[a.compare_legend], BROAD_CODES)
    v = valid & (ba > 0) & (bb > 0)
    classes = sorted(set(np.unique(ba[v])) | set(np.unique(bb[v])))
    classes = [int(c) for c in classes if c > 0]
    o = dict(opts, valid=v, purity=None)
    ra = core.class_signatures(img, ba, classes, **o)
    rb = core.class_signatures(img, bb, classes, **o)
    agree_labels = np.where(ba == bb, ba, 0)
    rc = core.class_signatures(img, agree_labels, classes, **dict(o, valid=v & (agree_labels > 0)))
    agreement = core.map_agreement(ba, bb, classes, v)

    out = a.out
    report.plot_signatures(os.path.join(out, "compare_signatures.png"), ra, names, wl, "broad",
                           title=f"Same pixels, two maps: {la} (solid, shaded IQR) vs {lb} (dashed)",
                           compare=rb, compare_label=(la, lb))
    report.write_signatures_csv(os.path.join(out, "compare_signatures.csv"), ra, names, wl, "broad", la)
    for res, lab in ((rb, lb), (rc, "agreement only")):
        report.write_signatures_csv(os.path.join(out, "compare_signatures.csv"), res, names, wl, "broad", lab, append=True)

    table = []
    for c in classes:
        sa, sb, sc = ra[c]["stats"], rb[c]["stats"], rc[c]["stats"]
        row = {"broad_class": class_name("broad", c),
               f"pixels_{la}": agreement[c]["pixels_a"], f"pixels_{lb}": agreement[c]["pixels_b"],
               "share_agreed": round(agreement[c]["share_of_a_agreed"], 3)}
        if sa is not None and sb is not None:
            row["angle_A_vs_B_deg"] = round(core.spectral_angle(sa["median"], sb["median"]), 2)
            row["max_band_diff_A_vs_B"] = round(float(np.max(np.abs(sa["median"] - sb["median"]))), 4)
        if sa is not None and sc is not None:
            row["angle_A_vs_agreed_deg"] = round(core.spectral_angle(sa["median"], sc["median"]), 2)
        for tag, r in ((la, ra), (lb, rb), ("agreed", rc)):
            if "ndvi" in r[c]:
                row[f"ndvi_{tag}"] = round(r[c]["ndvi"]["median"], 3)
        table.append(row)
    keys = []
    for r in table:
        keys += [k for k in r if k not in keys]
    with open(os.path.join(out, "compare_summary.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(table)
    print(f"comparison {la} vs {lb}:")
    for r in table:
        print("  " + "  ".join(f"{k}={v}" for k, v in r.items()))
    return {"agreement": agreement, "table": table}


if __name__ == "__main__":
    main()
