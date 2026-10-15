#!/bin/sh
# Same Mwea area from NASA HLS (Landsat + Sentinel-2, 30 m), for your own computer.
# Needs: pip install -r requirements.txt, and a free Earthdata login in ~/.netrc:
#   machine urs.earthdata.nasa.gov login YOUR_USER password YOUR_PASSWORD
set -e
cd "$(dirname "$0")/.."
python -m timeprofile fetch-hls --bbox 37.3223 -0.675 37.3636 -0.6352 --start 2023-01-01 --end 2024-12-31 \
  --out demo/data/hls_mwea
python -m timeprofile scan --scenes demo/data/hls_mwea
python -m timeprofile extract --scenes demo/data/hls_mwea --features demo/mwea_features.geojson \
  --index NDVI,MNDWI --out demo/output_hls --title "Mwea irrigation scheme, Kenya: HLS L30 + S30, 2023-2024"
# Compare with the Sentinel-2 run: demo/output/series.csv vs demo/output_hls/series.csv
