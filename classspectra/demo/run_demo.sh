#!/bin/sh
# Reproduce the Nakuru demo from the tool folder: sh demo/run_demo.sh
set -e
D=demo/data
python demo/make_demo_data.py
python -m classspectra $D/nakuru_s2_20240215.tif $D/worldcover_2021_v200.tif \
  --mask $D/nakuru_s2_scl.tif --mask-invalid 0,1,3,8,9,10,11 \
  --compare $D/worldcover_2020_v100.tif --map-names WC2021 WC2020 \
  --title "Nakuru, Kenya - Sentinel-2 L2A 15 Feb 2024 - ESA WorldCover 2021" --out demo/output_10m
python -m classspectra $D/nakuru_s2_30m.tif $D/worldcover_2021_v200.tif \
  --mask $D/nakuru_s2_scl.tif --mask-invalid 0,1,3,8,9,10,11 \
  --title "Nakuru, 30 m aggregate (HLS-like grid), WorldCover 2021, purity >= 0.75" --out demo/output_30m
python -m classspectra $D/nakuru_s2_20240215.tif $D/worldcover_2021_v200.tif \
  --erosion 0 --outlier-z 0 --no-separability \
  --title "Nakuru, no cleaning (no cloud mask, no erosion, no outlier trim)" --out demo/output_10m_raw
