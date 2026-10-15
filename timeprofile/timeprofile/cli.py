"""Command line: python -m timeprofile <command> ..."""

import argparse
import os
import sys

from . import catalog, geom, report
from .indices import INDICES


def _io():
    try:
        from . import rio_io
        return rio_io
    except ImportError:
        from . import gdal_io
        return gdal_io


def _scenes(a, io):
    names = a.band_names.split(",") if a.band_names else None
    sc = catalog.scan(a.scenes, io.info, names, a.scale, a.offset)
    return catalog.filter_scenes(sc, a.start, a.end, a.sensors.split(",") if a.sensors else None,
                                 a.tiles.split(",") if a.tiles else None)


def _scene_args(p):
    p.add_argument("--scenes", required=True, help="folder of scenes (searched recursively) or one file")
    p.add_argument("--start", help="first date, YYYY-MM-DD")
    p.add_argument("--end", help="last date, YYYY-MM-DD")
    p.add_argument("--sensors", help="keep only these, comma-separated prefixes, e.g. HLS.S30,S2")
    p.add_argument("--tiles", help="keep only these MGRS tiles / Landsat paths, comma-separated")
    p.add_argument("--band-names", help="for plain GeoTIFFs: names of the bands in order, e.g. blue,green,red,nir")
    p.add_argument("--scale", type=float, help="for plain GeoTIFFs: reflectance = DN * scale + offset")
    p.add_argument("--offset", type=float)


def cmd_scan(a):
    io = _io()
    sc = _scenes(a, io)
    print(catalog.describe(sc))
    if a.list:
        for s in sc:
            print(f"{s.date}  {s.sensor:8s} {s.tile:6s} {s.id}  mask={s.mask[2] if s.mask else '-'}  "
                  f"scale={s.scale:g} offset={s.offset:g}")


def cmd_extract(a):
    from .extract import extract
    io = _io()
    feats = []
    if a.features:
        feats += geom.load_geojson(a.features, a.name_field)
    for i, p in enumerate(a.point or [], len(feats) + 1):
        feats.append(geom.parse_point(p, i))
    if not feats:
        sys.exit("give --features file.geojson and/or --point lon,lat[,name]")
    sc = _scenes(a, io)
    if not sc:
        sys.exit("no scenes found")
    print(catalog.describe(sc))
    indices = [s for s in a.index.split(";")] if ";" in a.index else a.index.split(",")
    drops = a.also_mask.split(",") if a.also_mask else ()

    def prog(i, n):
        if i % 25 == 0 or i == n:
            print(f"  {i}/{n} scenes", file=sys.stderr)
    rows, notes = extract(sc, feats, indices, io, use_mask=not a.no_mask, extra_drop=drops, buffer=a.buffer,
                          min_clear=a.min_clear, progress=prog)
    settings = {k: v for k, v in vars(a).items() if k != "func"}
    settings["backend"] = io.NAME
    paths = report.outputs(a.out, rows, notes, settings, a.season_start, a.smooth, a.spike, not a.no_chart,
                           a.title)
    for n in notes[:10]:
        print("note:", n)
    clear = [r for r in rows if r["status"] == "clear"]
    print(f"{len(rows)} observations, {len(clear)} clear, {sum(r['flag'] == 'spike' for r in rows)} flagged as spikes")
    for k, p in paths.items():
        print(f"  {k}: {p}")


def cmd_chart(a):
    rows = report.read_csv(a.csv)
    post = report.postprocess(rows, a.spike, a.smooth, season_start=a.season_start)
    out = a.out or os.path.splitext(a.csv)[0] + ".png"
    report.chart_time(out, rows, post, a.title)
    print(out)
    if a.seasons:
        for idx in dict.fromkeys(r["index"] for r in rows):
            p = os.path.splitext(out)[0] + f"_seasons_{idx}.png"
            report.chart_seasons(p, rows, post, idx, a.season_start)
            print(p)


def cmd_indices(a):
    for k, (expr, what) in INDICES.items():
        print(f"{k:6s} {expr:60s} {what}")
    print("\nAny band name (red, nir, swir1 ...) also works, or your own: 'MSI=swir1/nir'.")


def cmd_fetch_s2(a):
    from . import fetch_s2
    fetch_s2.fetch(a.bbox, a.start, a.end, a.out, a.bands.split(","), a.res, a.tiles.split(",") if a.tiles else None,
                   a.max_cloud, a.min_clear, a.workers)


def cmd_fetch_hls(a):
    from . import fetch_hls
    fetch_hls.fetch(a.bbox, a.start, a.end, a.out, a.products.split(","), a.tile, a.max_cloud, a.workers)


def main(argv=None):
    p = argparse.ArgumentParser(prog="timeprofile", description=__doc__)
    sub = p.add_subparsers(required=True)

    s = sub.add_parser("scan", help="list the scenes found in a folder")
    _scene_args(s)
    s.add_argument("--list", action="store_true", help="one line per scene")
    s.set_defaults(func=cmd_scan)

    s = sub.add_parser("extract", help="index through time for points/polygons -> CSV + charts")
    _scene_args(s)
    s.add_argument("--features", help="GeoJSON of points and/or polygons, lon/lat")
    s.add_argument("--name-field", help="property that names each feature (default 'name')")
    s.add_argument("--point", action="append", help="lon,lat[,name]; repeat for more")
    s.add_argument("--index", default="NDVI", help="NDVI, EVI, NDMI ... or band names, comma-separated; "
                   "or your own as NAME=formula (separate several with ';')")
    s.add_argument("--out", required=True, help="output folder")
    s.add_argument("--buffer", type=int, default=0, help="points: also use this many pixels around the point")
    s.add_argument("--min-clear", type=float, default=50.0, help="polygons: %% of pixels that must be clear")
    s.add_argument("--no-mask", action="store_true", help="ignore the quality masks")
    s.add_argument("--also-mask", help="extra mask flags: water, aerosol_moderate, cirrus (HLS Fmask / Landsat)")
    s.add_argument("--smooth", type=float, default=1000.0, help="Whittaker lambda (0 = no smooth line)")
    s.add_argument("--spike", type=float, default=0.1, help="spike threshold in index units (0 = off)")
    s.add_argument("--season-start", type=int, default=1, help="month a season starts, e.g. 10 for Oct-Sep")
    s.add_argument("--title")
    s.add_argument("--no-chart", action="store_true")
    s.set_defaults(func=cmd_extract)

    s = sub.add_parser("chart", help="redraw the charts from a series.csv")
    s.add_argument("csv")
    s.add_argument("--out")
    s.add_argument("--smooth", type=float, default=1000.0)
    s.add_argument("--spike", type=float, default=0.1)
    s.add_argument("--season-start", type=int, default=1)
    s.add_argument("--seasons", action="store_true", help="also draw the season-by-season charts")
    s.add_argument("--title")
    s.set_defaults(func=cmd_chart)

    s = sub.add_parser("indices", help="list the built-in indices")
    s.set_defaults(func=cmd_indices)

    s = sub.add_parser("fetch-s2", help="download Sentinel-2 L2A for an area from AWS (free, no login)")
    s.add_argument("--bbox", nargs=4, type=float, required=True, metavar=("W", "S", "E", "N"))
    s.add_argument("--start", required=True)
    s.add_argument("--end", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--bands", default="blue,green,red,nir,swir1,swir2",
                   help="common names; add rededge1,nirn for NDRE etc.")
    s.add_argument("--res", type=int, default=10, choices=(10, 20))
    s.add_argument("--tiles", help="MGRS tiles, e.g. 37MCV (default: worked out from the bbox)")
    s.add_argument("--max-cloud", type=float, default=100.0, help="skip scenes with more tile cloud %% than this")
    s.add_argument("--min-clear", type=float, default=5.0, help="skip scenes with less clear area over the bbox (%%)")
    s.add_argument("--workers", type=int, default=8)
    s.set_defaults(func=cmd_fetch_s2)

    s = sub.add_parser("fetch-hls", help="download NASA HLS for an area (Earthdata login)")
    s.add_argument("--bbox", nargs=4, type=float, required=True, metavar=("W", "S", "E", "N"))
    s.add_argument("--start", required=True)
    s.add_argument("--end", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--products", default="L30,S30")
    s.add_argument("--tile")
    s.add_argument("--max-cloud", type=float)
    s.add_argument("--workers", type=int, default=8)
    s.set_defaults(func=cmd_fetch_hls)

    a = p.parse_args(argv)
    a.func(a)
