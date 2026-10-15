"""Command line: python -m fallowcheck {run,fetch-s2,fetch-worldcover,fetch-places}."""

import argparse
import glob
import sys

from . import core


def main(argv=None):
    ap = argparse.ArgumentParser(prog="fallowcheck",
                                 description="Which normally farmed fields were not farmed this season?")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="compare a target season with normal seasons")
    r.add_argument("--scenes", nargs="+", required=True, help="Sentinel-2 scenes from fetch-s2 (globs ok)")
    r.add_argument("--baseline-years", nargs="+", type=int, required=True, help="normal seasons, e.g. 2021 2022")
    r.add_argument("--target-year", type=int, required=True)
    r.add_argument("--season", nargs=2, required=True, metavar=("MM-DD", "MM-DD"),
                   help="growing-season window, same every year (may cross New Year)")
    r.add_argument("--cropland", help="land cover raster (e.g. fetch-worldcover output)")
    r.add_argument("--crop-classes", default="40", help="cropland class values (WorldCover: 40)")
    r.add_argument("--units", help="your own polygons (admin units, irrigation blocks); default a square grid")
    r.add_argument("--cell", type=float, default=1000.0, help="grid size in m (1000)")
    r.add_argument("--places", help="named points to label units")
    r.add_argument("--out", required=True)
    for k, v in core.DEFAULTS.items():
        r.add_argument("--" + k.replace("_", "-"), type=type(v), default=v)

    f = sub.add_parser("fetch-s2", help="Sentinel-2 L2A from AWS (no login)")
    f.add_argument("--bbox", nargs=4, type=float, required=True, metavar=("W", "S", "E", "N"))
    f.add_argument("--start", required=True)
    f.add_argument("--end", required=True)
    f.add_argument("--out", required=True)
    f.add_argument("--min-clear", type=float, default=60.0)

    for name in ("fetch-worldcover", "fetch-places"):
        g = sub.add_parser(name)
        g.add_argument("--bbox", nargs=4, type=float, required=True, metavar=("W", "S", "E", "N"))
        g.add_argument("--out", required=True)

    a = ap.parse_args(argv)
    if a.cmd == "run":
        from .pipeline import run
        scenes = []
        for s in a.scenes:
            scenes += sorted(glob.glob(s)) or [s]
        run(scenes, a.baseline_years, a.target_year, a.season, a.out, a.cropland,
            tuple(int(x) for x in a.crop_classes.split(",")), a.units, a.cell, a.places,
            {k: getattr(a, k) for k in core.DEFAULTS})
    elif a.cmd == "fetch-s2":
        from .fetch_s2 import fetch
        fetch(tuple(a.bbox), a.start, a.end, a.out, min_clear=a.min_clear)
    elif a.cmd == "fetch-worldcover":
        from .fetch_worldcover import fetch_worldcover
        fetch_worldcover(tuple(a.bbox), a.out)
    else:
        from .fetch_overture import fetch_places
        fetch_places(tuple(a.bbox), a.out)


if __name__ == "__main__":
    sys.exit(main())
