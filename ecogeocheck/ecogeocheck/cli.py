"""Command line: python -m ecogeocheck {check,fetch,flags,levels}"""

import argparse
import os
import sys

from . import __version__, core, flags, known_issues


def _cols(s):
    if not s:
        return None
    return dict(kv.split("=", 1) for kv in s.split(","))


def main(argv=None):
    p = argparse.ArgumentParser(prog="ecogeocheck", description="Find ECOSTRESS scenes with bad geolocation.")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="check ECOSTRESS files and decide which to keep")
    c.add_argument("inputs", nargs="+", help="ECOSTRESS files or folders (tiled .tif layers, L1B GEO .h5, sidecars)")
    c.add_argument("--out", required=True, help="output folder")
    c.add_argument("--summary", help="table of per-scene flags (NASA's summary file, or geo_flags.csv from fetch)")
    c.add_argument("--summary-columns", help="override detected columns, e.g. orbit=Orbit,scene=Scene,qa=GeoQA")
    c.add_argument("--reference", help="raster to measure offsets against (water mask, HLS NDVI, ...) instead of "
                                       "each scene's own water layer")
    c.add_argument("--accept", default="best,good", help="NASA flags to keep (default best,good)")
    c.add_argument("--tolerance", type=float, default=140, help="largest offset to accept, metres (default 140 = 2 px)")
    c.add_argument("--max-shift", type=float, default=7700, help="search radius, metres (default 7700)")
    c.add_argument("--fix", action="store_true", help="write shifted copies of scenes with a reliable measured offset")
    c.add_argument("--rescue", action="store_true", help="keep flagged scenes whose measured offset is within tolerance")
    c.add_argument("--no-measure", action="store_true", help="flags only, don't measure offsets")
    c.add_argument("--no-stack", action="store_true", help="don't use 'best' scenes as a reference")
    c.add_argument("--io", choices=["rasterio", "gdal"], help="raster backend")

    f = sub.add_parser("fetch", help="find and download ECO_L2T_LSTE layers plus flags (needs Earthdata login)")
    f.add_argument("--bbox", required=True, help="W,S,E,N in degrees")
    f.add_argument("--start", required=True)
    f.add_argument("--end", required=True)
    f.add_argument("--dest", required=True)
    f.add_argument("--tiles", help="comma-separated MGRS tiles to keep, e.g. 37MBU")
    f.add_argument("--layers", default="LST,cloud,water")
    f.add_argument("--list", action="store_true", help="only list scenes and flags")
    f.add_argument("--no-geo-read", action="store_true", help="don't open L1B GEO files for the flag")

    fl = sub.add_parser("flags", help="print the geolocation fields found in files")
    fl.add_argument("files", nargs="+")
    sub.add_parser("levels", help="explain NASA's flag levels and the dated known issues")
    a = p.parse_args(argv)

    if a.cmd == "check":
        summary = a.summary
        if not summary:
            for i in a.inputs:
                cand = os.path.join(i, "geo_flags.csv")
                if os.path.isdir(i) and os.path.exists(cand):
                    summary = cand
                    print(f"using {cand}")
        results, info = core.run(a.inputs, out=a.out, summary=summary, summary_columns=_cols(a.summary_columns),
                                 reference=a.reference, io=core.get_io(a.io),
                                 accept=tuple(x.strip() for x in a.accept.split(",") if x.strip()),
                                 tolerance_m=a.tolerance, max_shift_m=a.max_shift, fix=a.fix, rescue=a.rescue,
                                 measure=not a.no_measure, use_stack=not a.no_stack)
        c = info["counts"]
        print(f"keep {c['keep']}, caution {c['caution']}, fixed {c['fixed']}, check {c['check']}, drop {c['drop']}")
        return 0
    if a.cmd == "fetch":
        from . import fetch
        fetch.fetch(tuple(float(x) for x in a.bbox.split(",")), a.start, a.end, a.dest,
                    tiles=set(a.tiles.split(",")) if a.tiles else None, layers=tuple(a.layers.split(",")),
                    list_only=a.list, read_geo=not a.no_geo_read)
        return 0
    if a.cmd == "flags":
        io = core.get_io()
        for path in a.files:
            low = path.lower()
            if low.endswith(".h5"):
                r = flags.from_hdf5(path)
            elif low.endswith((".json", ".xml")):
                r = flags.from_sidecar(path)
            else:
                r = flags.from_tags(io.read_tags(path))
            print(f"{os.path.basename(path)}: {r or 'no geolocation fields found'}")
        return 0
    if a.cmd == "levels":
        print("NASA GeolocationAccuracyQA levels (NASA recommends best and good where geolocation matters):")
        for k in flags.QA_LEVELS:
            print(f"  {k:8s} {flags.QA_ERROR[k]}")
        print("OrbitCorrectionPerformed=False means no image matching: up to 7 km off.")
        print("Dated known issues checked for every scene:")
        for s, e, lvl, msg in known_issues.WINDOWS:
            print(f"  {s:%Y-%m-%d} to {e:%Y-%m-%d} [{lvl}] {msg}")
        print("  FieldOfViewObstruction=True [caution], reliable only from 2024-10-24")
        return 0


if __name__ == "__main__":
    sys.exit(main())
