#!/bin/sh
# Real Sentinel-2 L2A demo: Mwea irrigation scheme, Kenya, 2023-2024.
# Downloads ~50 MB from the free AWS bucket if demo/data/s2_mwea is missing.
set -e
cd "$(dirname "$0")/.."
[ -d demo/data/s2_mwea ] || python demo/make_demo_data.py
python -m timeprofile scan --scenes demo/data/s2_mwea
python -m timeprofile extract --scenes demo/data/s2_mwea --features demo/mwea_features.geojson \
  --index NDVI,MNDWI --out demo/output --title "Mwea irrigation scheme, Kenya: Sentinel-2 L2A, 2023-2024"
