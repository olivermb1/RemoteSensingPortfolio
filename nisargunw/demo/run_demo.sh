#!/usr/bin/env bash
# Builds the synthetic Fentale GUNW (if missing) and converts it five ways.
set -euo pipefail
cd "$(dirname "$0")/.."
ls demo/data/NISAR_L2_*GUNW*.h5 >/dev/null 2>&1 || python3 demo/make_demo_data.py
F=demo/data/NISAR_L2_*GUNW*.h5
DEM=demo/data/dem_fentale.tif
rm -rf demo/output
python3 -m nisargunw inspect $F
# 1. recommended: all three corrections, DEM heights
python3 -m nisargunw convert $F -o demo/output/run1_dem_all_corrections --dem $DEM \
  --layers default,vertical_displacement,los_east,los_north,los_up,troposphere,keep_mask,wrapped_phase
# 2. no corrections at all
python3 -m nisargunw convert $F -o demo/output/run2_no_corrections --correct none --no-quicklook
# 3. corrections, but no DEM (radar cube sampled at 0 m; the rift floor is ~950 m)
python3 -m nisargunw convert $F -o demo/output/run3_no_dem --no-quicklook
# 4. keep both connected components, zero at a point on the rift floor
python3 -m nisargunw convert $F -o demo/output/run4_all_components --dem $DEM --components all \
  --ref-lonlat 39.80,8.95 --no-quicklook
# 5. clip to a box around the summit
python3 -m nisargunw convert $F -o demo/output/run5_clip_summit --dem $DEM --bbox 39.88,8.93,39.98,9.02 \
  --layers default,wrapped_phase,wrapped_coherence
python3 demo/compare_truth.py | tee demo/output/compare_truth.md
