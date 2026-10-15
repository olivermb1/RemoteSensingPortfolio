"""Command line: python -m floodcrop --source sar --event ... --baseline ... --cropland ... --zones ..."""
import argparse
import sys

from . import pipeline, report


def main(argv=None):
    ap = argparse.ArgumentParser(prog="floodcrop", description="Hectares of cropland flooded per area, from OPERA DSWx "
                                 "(or Sentinel-1, optical reflectance, any water mask) + a cropland map + polygons.")
    ap.add_argument("--source", required=True, choices=["dswx", "sar", "optical", "mask"],
                    help="dswx: OPERA DSWx WTR/BWTR GeoTIFFs; sar: Sentinel-1 VV gamma0 (linear or dB); "
                         "optical: 6-band surface reflectance stacks (blue green red nir swir1 swir2); "
                         "mask: any water mask (1 water, 0 dry)")
    ap.add_argument("--event", nargs="+", required=True, help="file(s) on or after the event date; the first sets the grid")
    ap.add_argument("--baseline", nargs="*", default=[], help="pre-event file(s), same source type")
    ap.add_argument("--cropland", help="cropland raster (any CRS/resolution)")
    ap.add_argument("--crop-preset", default="worldcover", choices=["worldcover", "deafrica", "worldcereal", "binary"])
    ap.add_argument("--zones", help="polygons (GeoJSON; GPKG/SHP need fiona): admin units or FEWS NET livelihood zones")
    ap.add_argument("--name-field", help="zone name attribute (default: first of name, shapeName, ADM2_EN, LZNAMEEN, FNID...)")
    ap.add_argument("--permanent", help="water frequency/occurrence raster (WOfS 0-1 or JRC GSW 0-100) to exclude")
    ap.add_argument("--permanent-threshold", type=float, default=0.8)
    ap.add_argument("--event-combine", default="any", choices=["any", "majority"])
    ap.add_argument("--baseline-combine", default="any", choices=["any", "majority"])
    ap.add_argument("--event-clouds", nargs="*", help="optical: cloud layer per event file (SCL or Fmask)")
    ap.add_argument("--baseline-clouds", nargs="*", help="optical: cloud layer per baseline file")
    ap.add_argument("--cloud-kind", default="scl", choices=["scl", "fmask"])
    ap.add_argument("--scale", type=float, default=1.0, help="optical: multiply reflectance onto 0-10000 (10000 for 0-1 floats)")
    ap.add_argument("--sar-method", default="change", choices=["change", "threshold"])
    ap.add_argument("--sar-threshold", type=float, help="VV dB water threshold (default: Otsu per scene, clamped to -22..-15)")
    ap.add_argument("--drop-db", type=float, default=3.0, help="sar change: backscatter drop that counts as new water")
    ap.add_argument("--loose-db", type=float, default=-14.0, help="sar change: dropped pixels must also be below this")
    ap.add_argument("--smooth", type=int, default=5, help="sar: boxcar window (pixels) before thresholding")
    ap.add_argument("--out", default="floodcrop_out")
    ap.add_argument("--title", default="Flooded cropland")
    a = ap.parse_args(argv)

    if a.source == "sar" and a.sar_method == "change" and not a.baseline:
        ap.error("--sar-method change needs --baseline")
    res = pipeline.run(a.source, a.event, a.baseline, a.cropland, a.crop_preset, a.zones, a.name_field, a.permanent,
                       a.permanent_threshold, a.event_clouds, a.baseline_clouds, a.event_combine, a.baseline_combine,
                       a.out, cloud_kind=a.cloud_kind, scale=a.scale, sar_method=a.sar_method,
                       sar_threshold=a.sar_threshold, drop_db=a.drop_db, loose_db=a.loose_db, smooth=a.smooth)
    report.write_tables(res, a.out)
    report.plot(res, a.out, a.title)
    w = res["whole"]
    print(f"cropland {w['crop_ha']:,.0f} ha | flooded (open water) {w['flooded_crop_ha']:,.0f} ha "
          f"({w['flooded_crop_pct']:.2f}%) | partial {w['flooded_crop_partial_ha']:,.0f} ha | "
          f"cropland observed {w['crop_observed_pct']:.0f}%")
    for r in sorted(res["rows"], key=lambda r: -r["flooded_crop_ha"])[:10]:
        print(f"  {r['zone']:<24} {r['flooded_crop_ha']:>9,.0f} ha  {r['flooded_crop_pct']:5.1f}%  of {r['crop_ha']:,.0f} ha cropland")
    print("outputs in", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
