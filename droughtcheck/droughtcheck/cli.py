"""Command line for Drought Check.

  python -m droughtcheck drought   --precip chirps.tif [--temps power.tif | --pet pet.tif] --out out/
  python -m droughtcheck greenness --ndvi ndvi_anomaly.tif --drought-dir out/ --landcover worldcover.tif --out out/
"""
from __future__ import annotations

import argparse

from . import pipeline, rio


def cmd_drought(a):
    pipeline.drought_files(rio, a.precip, a.out, temps=a.temps, pet=a.pet, scales=a.scales,
                           spei_scales=a.spei_scales, calibration=tuple(a.calibration),
                           class_scale=a.class_scale, threshold=a.threshold, min_duration=a.min_duration,
                           events_since=a.events_since, backend=a.backend)


def cmd_greenness(a):
    pipeline.greenness_files(rio, a.ndvi, a.drought_dir, a.landcover, a.out, clear=a.clear,
                             min_clear=a.min_clear, legend=a.legend, scales=a.scales, target=a.target,
                             scale=a.scale, lag=a.lag, recent=a.recent, min_class_pixels=a.min_class_pixels)


def main(argv=None):
    p = argparse.ArgumentParser(prog="droughtcheck", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("drought", help="SPI/SPEI, drought classes and drought events from monthly rainfall")
    d.add_argument("--precip", required=True, help="multiband GeoTIFF, one band per month, descriptions YYYY-MM")
    d.add_argument("--temps", help="Tmax/Tmin GeoTIFF from `droughtcheck.fetch temps` (SPEI with Hargreaves PET)")
    d.add_argument("--pet", help="monthly PET GeoTIFF in mm (SPEI)")
    d.add_argument("--scales", type=int, nargs="+", default=[1, 3, 6, 12])
    d.add_argument("--spei-scales", type=int, nargs="+", default=[3, 6, 12])
    d.add_argument("--calibration", type=int, nargs=2, default=[1991, 2020])
    d.add_argument("--class-scale", type=int, default=3, help="SPI scale for classes and events")
    d.add_argument("--threshold", type=float, default=-1.0)
    d.add_argument("--min-duration", type=int, default=2)
    d.add_argument("--events-since", help="YYYY-MM; per-pixel event layers count from here")
    d.add_argument("--backend", choices=["auto", "climate-indices", "builtin"], default="auto")
    d.add_argument("--out", required=True)
    d.set_defaults(fn=cmd_drought)

    g = sub.add_parser("greenness", help="NDVI anomaly vs SPI per land cover class: drought or something else?")
    g.add_argument("--ndvi", required=True, help="monthly NDVI standardised anomaly GeoTIFF")
    g.add_argument("--clear", help="matching clear-count GeoTIFF; months with fewer clear views are dropped")
    g.add_argument("--min-clear", type=int, default=1)
    g.add_argument("--drought-dir", required=True, help="output folder of the drought command")
    g.add_argument("--landcover", required=True)
    g.add_argument("--legend", default="worldcover", help="worldcover | io | dynamicworld | none")
    g.add_argument("--scales", type=int, nargs="+", default=[1, 3, 6])
    g.add_argument("--scale", default="auto"); g.add_argument("--lag", default="auto")
    g.add_argument("--target", help="YYYY-MM (default: last month)")
    g.add_argument("--recent", type=int, default=12, help="months in the recent window")
    g.add_argument("--min-class-pixels", type=int, default=50)
    g.add_argument("--out", required=True)
    g.set_defaults(fn=cmd_greenness)

    a = p.parse_args(argv)
    a.fn(a)
