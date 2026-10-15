#!/bin/sh
# Composite Check demo: Nakuru, Kenya, January to June 2024 (first-half GeoMAD period).
# Run from the compositecheck folder. Downloads ~120 MB on first run.
set -e
cd "$(dirname "$0")/.."
[ -f demo/data/manifest.csv ] || python3 demo/make_demo_data.py
COMMON="demo/data/manifest.csv --start 2024-01-01 --end 2024-06-30 --target 2024-03-31 --dilate 1"

# 1. Medoid composite of all 95 Landsat + Sentinel-2 scenes
python3 -m compositecheck $COMMON --method medoid --out demo/output_medoid \
  --title "Nakuru, Kenya, Jan-Jun 2024: medoid of Landsat + Sentinel-2"
# 2. Closest-clear-date composite (a minimal best-available-pixel rule), same scenes
python3 -m compositecheck $COMMON --method target --out demo/output_target \
  --title "Nakuru, Kenya, Jan-Jun 2024: closest clear date to 31 Mar"
# 3. Digital Earth Africa GeoMAD (Sentinel-2, H1 2024), assessed against the Sentinel-2 scenes
python3 -m compositecheck $COMMON --sensors S --composite demo/data/geomad_2024H1.tif \
  --composite-bands 1,2,3,4,5,6 --out demo/output_geomad \
  --title "Nakuru, Kenya: DE Africa GeoMAD H1 2024 vs its Sentinel-2 scenes"
python3 demo/geomad_count.py
