"""Command line: python -m nisargunw inspect|convert ..."""

import argparse
import glob
import json
import sys

from . import __version__, product as P


def _floats(s, n):
    v = [float(x) for x in s.replace(" ", "").split(",")]
    if len(v) != n:
        raise argparse.ArgumentTypeError(f"expected {n} comma-separated numbers")
    return v


def main(argv=None):
    ap = argparse.ArgumentParser(prog="nisargunw", description=(
        "Convert NISAR L2 GUNW interferograms (HDF5) to GeoTIFF, with optional "
        "ionosphere/troposphere/solid-Earth-tide corrections and LOS displacement in metres."))
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("inspect", help="list what is in a GUNW file")
    a.add_argument("file")
    a.add_argument("--json", action="store_true", help="print JSON")

    c = sub.add_parser("convert", help="write GeoTIFFs")
    c.add_argument("files", nargs="+", help="GUNW .h5 file(s); globs are fine")
    c.add_argument("-o", "--out", required=True, help="output folder")
    c.add_argument("--layers", default="default", help=(
        "comma list, 'default' or 'all'. File layers: " + ", ".join(P.LAYERS) +
        ". Computed: " + ", ".join(P.DERIVED) + ". Default: " + ",".join(P.DEFAULT_LAYERS)))
    c.add_argument("--bbox", type=lambda s: _floats(s, 4), metavar="W,S,E,N",
                   help="clip to a lon/lat box")
    c.add_argument("--frequency", choices=["A", "B"], help="default A")
    c.add_argument("--pol", help="polarization, default the first one (HH or VV)")
    c.add_argument("--correct", default="ionosphere,troposphere,solid_earth_tide",
                   help="corrections subtracted before computing displacement; 'none' for none")
    c.add_argument("--dem", help="DEM GeoTIFF, used to sample the radar grid cube at ground height")
    c.add_argument("--height", type=float, default=0.0,
                   help="constant height (m above ellipsoid) when no DEM is given")
    c.add_argument("--reference", choices=["largest", "median", "none"], default="largest",
                   help="how to zero the displacement map (default: median of the largest component)")
    c.add_argument("--ref-lonlat", type=lambda s: _floats(s, 2), metavar="LON,LAT",
                   help="zero the displacement at this point instead (a stable spot)")
    c.add_argument("--min-coherence", type=float, default=0.0,
                   help="blank displacement where coherence is lower (default 0 = off)")
    c.add_argument("--components", choices=["largest", "all"], default="largest",
                   help="keep only the largest connected component (default) or all")
    c.add_argument("--flip-sign", action="store_true",
                   help="use +lambda/4pi instead of -lambda/4pi (see README)")
    c.add_argument("--prefix", help="output file prefix (default: short name from the granule ID)")
    c.add_argument("--no-quicklook", action="store_true")
    c.add_argument("--reader", choices=["auto", "h5py", "gdal"], default="auto")
    c.add_argument("--gdal-io", action="store_true", help="write with GDAL instead of rasterio")
    args = ap.parse_args(argv)

    from . import convert as C
    if args.cmd == "inspect":
        info = C.inspect(args.file)
        if args.json:
            print(json.dumps(info, indent=2, default=str))
            return
        idn = info["identification"]
        print(f"{idn.get('granuleId', args.file)}")
        print(f"  {idn.get('missionId', '?')} {idn.get('productType', '?')} v{idn.get('productVersion', '?')}"
              f" (spec {idn.get('productSpecificationVersion', '?')}), track {idn.get('trackNumber', '?')}"
              f" frame {idn.get('frameNumber', '?')}, {idn.get('orbitPassDirection', '?')}")
        print(f"  reference {idn.get('referenceZeroDopplerStartTime', '?')}")
        print(f"  secondary {idn.get('secondaryZeroDopplerStartTime', '?')}")
        if "wavelength_m" in info:
            print(f"  wavelength {info['wavelength_m'] * 100:.2f} cm; frequency {info['frequency']}; "
                  f"polarizations {', '.join(info['polarizations'])}")
        print("  layers:")
        for k, v in info["layers"].items():
            print(f"    {k:24s} {v['shape'][0]}x{v['shape'][1]} at {v['posting_m'][0]:g} m, EPSG:{v['epsg']}")
        if info["radar_grid_cube"]:
            print("  radar grid cube: " + ", ".join(f"{k} {tuple(s)}" for k, s in info["radar_grid_cube"].items()))
        return

    if args.gdal_io:
        from . import gdal_io as io
    else:
        from . import rio_io as io
    corr = [] if args.correct.strip().lower() in ("none", "") else \
        [s.strip() for s in args.correct.split(",")]
    files = sorted({f for pat in args.files for f in (glob.glob(pat) or [pat])})
    status = 0
    for f in files:
        print(f"{f}")
        try:
            meta = C.convert(
                f, args.out, io, layers=args.layers, freq=args.frequency, pol=args.pol,
                bbox=args.bbox, corrections=corr, dem=args.dem, height=args.height,
                ref_mode=args.reference, ref_lonlat=args.ref_lonlat,
                min_coherence=args.min_coherence, components=args.components,
                sign=1.0 if args.flip_sign else -1.0, prefix=args.prefix if len(files) == 1 else None,
                quicklook=not args.no_quicklook, reader_backend=args.reader)
        except Exception as e:  # keep going through a batch
            print(f"  FAILED: {e}", file=sys.stderr)
            status = 1
            continue
        if "los_displacement" in meta["outputs"]:
            s = meta["outputs"]["los_displacement"]["stats"]
            if s.get("valid_pixels"):
                print(f"  LOS displacement: {s['p02'] * 100:.1f} to {s['p98'] * 100:.1f} cm (2-98%), "
                      f"{meta['kept_fraction'] * 100:.0f}% of pixels kept; corrections: "
                      f"{', '.join(meta['corrections']['applied']) or 'none'}")
    sys.exit(status)


if __name__ == "__main__":
    main()
