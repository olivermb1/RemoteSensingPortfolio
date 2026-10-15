"""Command line: python -m compositecheck STACK --start ... --end ... --target ... --out DIR"""

import argparse
import json
import os
import sys
import time

import numpy as np

from . import __version__, core, report
from .sensors import LAYER_ORDER


def parse(argv=None):
    p = argparse.ArgumentParser(prog="compositecheck", description=(
        "Per-pixel quality layers and a one-page report for a Landsat / Sentinel-2 / HLS composite."))
    p.add_argument("stack", help="manifest CSV (path,date,sensor[,fmask,scene_id]) or a folder of HLS v2.0 granules")
    p.add_argument("--start", required=True, help="period start, YYYY-MM-DD")
    p.add_argument("--end", required=True, help="period end, YYYY-MM-DD")
    p.add_argument("--target", help="target date for the composite (default: middle of the period)")
    p.add_argument("--method", default="medoid", choices=["medoid", "median", "target"],
                   help="composite to build and assess (default medoid; 'target' = closest clear date, a minimal BAP)")
    p.add_argument("--composite", help="assess this existing composite instead of building one (bands in blue..swir2 order)")
    p.add_argument("--composite-bands", help="1-based band numbers of blue,green,red,nir,swir1,swir2 in --composite")
    p.add_argument("--composite-scale", type=float, default=1e-4)
    p.add_argument("--bbox", type=float, nargs=4, metavar=("W", "S", "E", "N"), help="area in degrees (EPSG:4326)")
    p.add_argument("--sensors", help="keep only these sensors, by label prefix, e.g. S (Sentinel-2) or L (Landsat)")
    p.add_argument("--fmask-bits", default="0,1,2,3", help="Fmask bits that make a pixel unusable (default 0,1,2,3)")
    p.add_argument("--dilate", type=int, default=0, help="grow cloud/shadow masks by N pixels (default 0)")
    p.add_argument("--dominance", type=float, default=0.5, help="flag when one scene supplies more than this share (default 0.5)")
    p.add_argument("--pair-days", type=int, default=1, help="max days apart for Landsat/Sentinel-2 pairs (default 1)")
    p.add_argument("--pair-min-share", type=float, default=0.5,
                   help="shared clear area a pair needs to count as clean (default 0.5)")
    p.add_argument("--outlier-z", type=float, default=3.5, help="robust z threshold for the outlier screen (default 3.5)")
    p.add_argument("--no-composite-out", action="store_true", help="don't write composite.tif")
    p.add_argument("--title", default=None)
    p.add_argument("--out", required=True, help="output folder")
    return p.parse_args(argv)


def main(argv=None):
    a = parse(argv)
    try:
        from . import io  # rasterio
    except ImportError:
        from . import gdal_io as io  # GDAL bindings, e.g. a QGIS Python

    t0 = time.time()
    bits = tuple(int(b) for b in a.fmask_bits.split(",") if b.strip())
    stack = io.load(a.stack, bbox=a.bbox, fmask_bits=bits, dilate=a.dilate, start=a.start, end=a.end,
                 sensors=a.sensors.split(",") if a.sensors else None)
    grid = stack.meta["grid"]
    target = a.target or str(np.datetime64(a.start) + (np.datetime64(a.end) - np.datetime64(a.start)) // 2)
    print(f"{stack.T} scenes, {grid.width} x {grid.height} pixels", file=sys.stderr)

    comp_in = None
    if a.composite:
        bands = [int(b) for b in a.composite_bands.split(",")] if a.composite_bands else None
        comp_in = io.read_composite(a.composite, grid, bands, a.composite_scale)

    layers, comp, rep, scenes = core.run_checks(
        stack, a.start, a.end, target, method=a.method, composite=comp_in,
        dominance_threshold=a.dominance, pair_days=a.pair_days, pair_min_share=a.pair_min_share, outlier_z=a.outlier_z)
    if a.composite:
        rep["composite_file"] = os.path.abspath(a.composite)

    os.makedirs(a.out, exist_ok=True)
    names = io.write_layers(layers, grid, os.path.join(a.out, "qa_layers.tif"), LAYER_ORDER)
    if comp_in is None and not a.no_composite_out:
        io.write_composite(comp, grid, os.path.join(a.out, "composite.tif"))
    rep["version"] = __version__
    rep["settings"] = {k: v for k, v in vars(a).items()}
    rep["seconds"] = round(time.time() - t0, 1)
    rep = report.write_tables(a.out, rep, scenes, names)
    report.plot(a.out, layers, rep, scenes, a.title or f"Composite Check: {os.path.basename(a.stack.rstrip('/'))}")
    for f in rep["findings"]:
        print(f"{f['level'].upper():5} {f['check']}: {f['text']}")
    print(f"wrote {a.out}", file=sys.stderr)
    return rep


if __name__ == "__main__":
    main()
