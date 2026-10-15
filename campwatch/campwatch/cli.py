"""Command line: python -m campwatch {run,fetch-s2,fetch-places}."""

import argparse
import glob
import sys

from . import core


def main(argv=None):
    ap = argparse.ArgumentParser(prog="campwatch", description="When and how fast do new shelter areas appear?")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="detect new shelter areas and their growth")
    r.add_argument("--scenes", nargs="+", required=True, help="Sentinel-2 scenes from fetch-s2 (globs ok)")
    r.add_argument("--baseline", nargs=2, required=True, metavar=("FROM", "TO"),
                   help="months (YYYY-MM) of a year before the displacement, same season as the analysis")
    r.add_argument("--period", nargs=2, required=True, metavar=("FROM", "TO"), help="months (YYYY-MM) to track")
    r.add_argument("--dry-months", default="11,12,1,2,3,4,5",
                   help="months used, comma-separated (default Sahel dry season 11..5)")
    r.add_argument("--units", help="your own polygons (camp outlines, admin units) instead of detected areas")
    r.add_argument("--places", help="named points to label areas (fetch-places output)")
    r.add_argument("--out", required=True)
    for k, v in core.DEFAULTS.items():
        r.add_argument("--" + k.replace("_", "-"), type=type(v), default=v)

    f = sub.add_parser("fetch-s2", help="Sentinel-2 L2A from AWS (no login)")
    f.add_argument("--bbox", nargs=4, type=float, required=True, metavar=("W", "S", "E", "N"))
    f.add_argument("--start", required=True)
    f.add_argument("--end", required=True)
    f.add_argument("--out", required=True)
    f.add_argument("--min-clear", type=float, default=80.0)

    g = sub.add_parser("fetch-places", help="place names from Overture Maps (no login)")
    g.add_argument("--bbox", nargs=4, type=float, required=True, metavar=("W", "S", "E", "N"))
    g.add_argument("--out", required=True)

    a = ap.parse_args(argv)
    if a.cmd == "run":
        from .pipeline import run
        scenes = []
        for p in a.scenes:
            scenes += sorted(glob.glob(p)) or [p]
        run(scenes, tuple(a.baseline), tuple(a.period), a.out, a.units, a.places,
            tuple(int(x) for x in a.dry_months.split(",")), {k: getattr(a, k) for k in core.DEFAULTS})
    elif a.cmd == "fetch-s2":
        from .fetch_s2 import fetch
        fetch(tuple(a.bbox), a.start, a.end, a.out, min_clear=a.min_clear)
    else:
        from .fetch_overture import fetch_places
        fetch_places(tuple(a.bbox), a.out)


if __name__ == "__main__":
    sys.exit(main())
