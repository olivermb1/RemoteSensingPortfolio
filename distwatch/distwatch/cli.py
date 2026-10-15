"""Command line: python -m distwatch {run,fetch,status,codes} ..."""

import argparse
import datetime as dt
import json
import os

from . import products as P


def main(argv=None):
    ap = argparse.ArgumentParser(prog="distwatch", description="New vegetation loss since your last run, "
                                 "from NASA OPERA DIST-ALERT-HLS.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="report new loss per area and update the state folder")
    r.add_argument("--areas", required=True, help="GeoJSON of areas in lon/lat (farms, concessions, districts)")
    r.add_argument("--state", required=True, help="folder that remembers what earlier runs reported")
    r.add_argument("--out", required=True, help="folder for this run's outputs")
    r.add_argument("--data", help="folder of DIST-ALERT GeoTIFFs (default: <state>/granules)")
    r.add_argument("--fetch", action="store_true", help="download the newest granules first (Earthdata login)")
    r.add_argument("--level", choices=list(P.LEVELS), default="confirmed")
    r.add_argument("--min-loss", type=int, default=50, help="minimum %% vegetation cover lost (VEG-ANOM-MAX)")
    r.add_argument("--since", default=P.EPOCH.isoformat(),
                   help="only disturbances first detected after this date (default: EUDR cutoff 2020-12-31)")
    r.add_argument("--min-patch-px", type=int, default=3, help="smallest patch to report, in 30 m pixels")
    r.add_argument("--forest-mask", help="optional raster, non-zero = forest at baseline (e.g. JRC GFC2020)")
    r.add_argument("--as-of", help="ignore granules sensed after this date (to replay history)")
    r.add_argument("--tiles", nargs="*", help="limit to these MGRS tiles, e.g. 30NWM")
    r.add_argument("--name-field", help="property holding each area's name")
    r.add_argument("--lookback-days", type=int, default=60, help="with --fetch, how far back to search")
    r.add_argument("--dry-run", action="store_true", help="write outputs but don't update the state")
    r.add_argument("--io", choices=["rasterio", "gdal"])

    f = sub.add_parser("fetch", help="download the newest DIST-ALERT granule per tile over the areas")
    f.add_argument("--areas", required=True)
    f.add_argument("--dest", required=True)
    f.add_argument("--start", default=(dt.date.today() - dt.timedelta(days=60)).isoformat())
    f.add_argument("--end")
    f.add_argument("--all", action="store_true", help="every granule in the window, not just the newest per tile")
    f.add_argument("--list", action="store_true", help="only list what would be downloaded")

    s = sub.add_parser("status", help="show the run history in a state folder")
    s.add_argument("--state", required=True)

    sub.add_parser("codes", help="print the VEG-DIST-STATUS codes and alert levels")

    a = ap.parse_args(argv)
    if a.cmd == "codes":
        for k, v in P.STATUS.items():
            lv = [n for n, c in P.LEVELS.items() if k in c]
            print(f"{k:>3}  {v:<30} {'counts at: ' + ', '.join(lv) if lv else ''}")
        return
    if a.cmd == "status":
        path = os.path.join(a.state, "state.json")
        if not os.path.exists(path):
            print("No runs yet.")
            return
        with open(path) as fh:
            meta = json.load(fh)
        for run in meta["runs"]:
            print(f"run {run['run']}  {run['time']}  new {run['new_loss_ha']} ha in {run['new_patches']} patches  "
                  "tiles: " + ", ".join(t + "=" + g.split("_")[4][:8] for t, g in run["granules"].items()))
        return
    if a.cmd == "fetch":
        from . import fetch
        gr = fetch.pick(fetch.search(fetch.bbox_of(a.areas), a.start, a.end), latest_only=not a.all)
        for g in gr:
            print(g["tile"], g["sensing"].date(), g["id"])
        if not a.list:
            fetch.download(gr, a.dest)
        return

    data = a.data or os.path.join(a.state, "granules")
    if a.fetch:
        from . import fetch
        start = (dt.date.today() - dt.timedelta(days=a.lookback_days)).isoformat()
        fetch.download(fetch.pick(fetch.search(fetch.bbox_of(a.areas), start)), data)
    from . import watch
    watch.run(data, a.areas, a.state, a.out, level=a.level, min_loss=a.min_loss, since=a.since,
              min_patch_px=a.min_patch_px, forest_mask=a.forest_mask, as_of=a.as_of, tiles=a.tiles,
              name_field=a.name_field, dry_run=a.dry_run, io=watch.get_io(a.io) if a.io else None)


if __name__ == "__main__":
    main()
