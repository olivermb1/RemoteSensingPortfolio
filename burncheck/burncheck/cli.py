"""Command line: python -m burncheck {run,fetch-s2,fetch-buildings,fetch-places}."""

import argparse
import glob
import sys

from . import core


def _expand(paths):
    out = []
    for p in paths:
        out += sorted(glob.glob(p)) or [p]
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="burncheck", description="Which settlements show new burn scars between two dates?")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="compare before/after imagery inside settlements")
    r.add_argument("--before", nargs="+", required=True, help="scenes or composites before the event (globs ok)")
    r.add_argument("--after", nargs="+", required=True, help="scenes or composites after the event")
    r.add_argument("--buildings", required=True, help="building footprints (any OGR vector)")
    r.add_argument("--units", help="your own reporting polygons instead of automatic settlements/blocks")
    r.add_argument("--places", help="named points to label units (fetch-places output)")
    r.add_argument("--firms", help="NASA FIRMS CSV; detections between the two image windows are counted per unit")
    r.add_argument("--out", required=True)
    r.add_argument("--link", type=float, default=40.0, help="m between buildings of the same settlement (40)")
    r.add_argument("--max-km2", type=float, default=0.5, help="settlements larger than this are split into blocks (0.5)")
    r.add_argument("--cell", type=float, default=250.0, help="block size in m for large settlements (250)")
    r.add_argument("--min-buildings", type=int, default=5)
    r.add_argument("--scale", type=float, default=1e-4, help="reflectance scale for plain 6-band inputs")
    r.add_argument("--offset", type=float, default=0.0)
    r.add_argument("--chips", type=int, default=12)
    for k, v in core.DEFAULTS.items():
        r.add_argument("--" + k.replace("_", "-"), type=type(v), default=v)

    f = sub.add_parser("fetch-s2", help="Sentinel-2 L2A from AWS (no login)")
    f.add_argument("--bbox", nargs=4, type=float, required=True, metavar=("W", "S", "E", "N"))
    f.add_argument("--start", required=True)
    f.add_argument("--end", required=True)
    f.add_argument("--out", required=True)
    f.add_argument("--min-clear", type=float, default=50.0, help="skip scenes with less clear area over bbox (%%)")

    for name in ("fetch-buildings", "fetch-places"):
        g = sub.add_parser(name, help=f"{name.split('-')[1]} from Overture Maps (no login)")
        g.add_argument("--bbox", nargs=4, type=float, required=True, metavar=("W", "S", "E", "N"))
        g.add_argument("--out", required=True)

    a = ap.parse_args(argv)
    if a.cmd == "run":
        from .pipeline import run
        params = {k: getattr(a, k) for k in core.DEFAULTS}
        run(_expand(a.before), _expand(a.after), a.buildings, a.out, a.units, a.places, a.firms, params,
            a.link, a.max_km2, a.cell, a.min_buildings, a.scale, a.offset, a.chips)
    elif a.cmd == "fetch-s2":
        from .fetch_s2 import fetch
        fetch(tuple(a.bbox), a.start, a.end, a.out, min_clear=a.min_clear)
    elif a.cmd == "fetch-buildings":
        from .fetch_overture import fetch_buildings
        fetch_buildings(tuple(a.bbox), a.out)
    else:
        from .fetch_overture import fetch_places
        fetch_places(tuple(a.bbox), a.out)


if __name__ == "__main__":
    sys.exit(main())
