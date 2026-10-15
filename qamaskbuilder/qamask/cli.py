"""Command line: python -m qamask <command> ..."""

import argparse
import json
import os
import sys

from . import ops
from .registry import PRODUCTS, get_product


def _split(s):
    return [x for x in (s or "").split(",") if x.strip()]


def _out_for(path, out, out_dir, suffix):
    if out:
        return out
    base = os.path.splitext(os.path.basename(path))[0] + suffix
    return os.path.join(out_dir or os.path.dirname(os.path.abspath(path)), base)


def cmd_products(a):
    for k, p in PRODUCTS.items():
        print(f"{k:28s} {p.title}")


def cmd_flags(a):
    p = get_product(a.product)
    print(f"{p.title}\nlayer: {p.layer} ({p.dtype})   source: {p.source}\n\nfields:")
    for f in p.fields.values():
        s, n = f["bits"]
        bits = f"bit {s}" if n == 1 else f"bits {s}-{s + n - 1}"
        print(f"  {f['name']:18s} {bits:10s} " + "; ".join(f"{k}={v}" for k, v in f["values"].items()))
    print("\nflags (use with --drop / --keep):")
    for f in p.flags.values():
        print(f"  {f['name']:22s} {f['label']}")
    print("\npresets:")
    for k, v in p.presets.items():
        mark = " (default)" if k == p.default_preset else ""
        print(f"  {k:16s}{mark} {', '.join(v)}")


def cmd_build(a):
    if a.out and len(a.qa) > 1:
        sys.exit("--out works with one input; use --out-dir for several")
    if a.out_dir:
        os.makedirs(a.out_dir, exist_ok=True)
    for path in a.qa:
        out = _out_for(path, a.out, a.out_dir, "_mask.tif")
        r = ops.build(path, out, a.product, _split(a.drop), _split(a.keep), a.buffer, a.fix_crs, a.band)
        m, c = r["mask"], r["crs"]
        print(f"{os.path.basename(out)}: {r['product']}, usable {m['usable_share_of_valid']:.1%} of valid pixels, "
              f"dropped [{', '.join(r['drop'])}]" + (f", keep [{', '.join(r['keep'])}]" if r["keep"] else ""))
        if c.get("applied"):
            print(f"  CRS fixed: EPSG:{c['input_epsg']} -> EPSG:{c['output_epsg']}")
        elif c.get("needed"):
            print(f"  CRS note: {c['reason']} (not applied; --fix-crs yes to apply)")


def cmd_apply(a):
    r = ops.apply(a.data, a.mask, a.out, a.nodata)
    print(f"{a.out}: kept {r['usable']} pixels, set {r['masked'] + r['nodata']} to {r['nodata']}")


def cmd_decode(a):
    out = _out_for(a.qa, a.out, None, "_decoded.tif")
    r = ops.decode(a.qa, out, a.product, a.fix_crs, a.band)
    print(f"{out}: bands {', '.join(r['bands'])}")


def cmd_stats(a):
    from . import core, io
    p = ops._product(a.qa, a.product)
    s = core.flag_stats(io.read(a.qa, a.band), p)
    if a.json:
        print(json.dumps(s, indent=1))
        return
    print(f"{p.key}: {s['valid_pixels']} valid pixels, {s['fill_pixels']} fill")
    for r in s["flags"]:
        print(f"  {r['flag']:22s} {r['share_of_valid']:7.2%}  {r['label']}")


def cmd_fix_crs(a):
    if a.out_dir:
        os.makedirs(a.out_dir, exist_ok=True)
    for path in a.inputs:
        out = _out_for(path, a.out if len(a.inputs) == 1 else None, a.out_dir, "_fixcrs.vrt" if a.vrt else "_fixcrs.tif")
        r = ops.fix_crs(path, out, a.vrt, a.force)
        print(f"{os.path.basename(path)}: {'wrote ' + os.path.basename(r['output']) + '; ' if r.get('output') else ''}{r['reason']}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="qamask", description="Build clean masks from NASA quality layers")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("products", help="list supported products").set_defaults(fn=cmd_products)
    s = sub.add_parser("flags", help="show the fields, flags and presets of a product")
    s.add_argument("product")
    s.set_defaults(fn=cmd_flags)

    s = sub.add_parser("build", help="make a mask: 1 usable, 0 masked, 255 no data")
    s.add_argument("qa", nargs="+", help="QA layer file(s)")
    s.add_argument("--product", default="auto", help="product key, or auto to guess from the file name")
    s.add_argument("--drop", help="comma list of flags or presets to mask out (default: the product's default preset)")
    s.add_argument("--keep", help="comma list of flags; a pixel must have one of them to be usable")
    s.add_argument("--buffer", type=int, default=0, help="grow masked areas by this many pixels")
    s.add_argument("--fix-crs", choices=["auto", "yes", "no"], default="auto",
                   help="relabel southern-hemisphere HLS/OPERA files as EPSG:327xx (auto: HLS and OPERA only)")
    s.add_argument("--band", type=int, default=1)
    s.add_argument("--out")
    s.add_argument("--out-dir")
    s.set_defaults(fn=cmd_build)

    s = sub.add_parser("apply", help="set pixels the mask doesn't keep to nodata")
    s.add_argument("data")
    s.add_argument("--mask", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--nodata", type=float)
    s.set_defaults(fn=cmd_apply)

    s = sub.add_parser("decode", help="write every QA field as its own band")
    s.add_argument("qa")
    s.add_argument("--product", default="auto")
    s.add_argument("--fix-crs", choices=["auto", "yes", "no"], default="auto")
    s.add_argument("--band", type=int, default=1)
    s.add_argument("--out")
    s.set_defaults(fn=cmd_decode)

    s = sub.add_parser("stats", help="share of valid pixels carrying each flag")
    s.add_argument("qa")
    s.add_argument("--product", default="auto")
    s.add_argument("--band", type=int, default=1)
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_stats)

    s = sub.add_parser("fix-crs", help="relabel southern-hemisphere HLS/OPERA files as EPSG:327xx, no resampling")
    s.add_argument("inputs", nargs="+")
    s.add_argument("--out")
    s.add_argument("--out-dir")
    s.add_argument("--vrt", action="store_true", help="write a small VRT instead of copying pixels")
    s.add_argument("--force", action="store_true", help="also relabel files that aren't HLS/OPERA")
    s.set_defaults(fn=cmd_fix_crs)

    a = ap.parse_args(argv)
    try:
        a.fn(a)
    except (KeyError, ValueError) as e:
        sys.exit(f"error: {e.args[0] if e.args else e}")


if __name__ == "__main__":
    main()
