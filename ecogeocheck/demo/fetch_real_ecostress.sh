#!/usr/bin/env bash
# Real data: run this on your own computer (NASA servers were unreachable where the tool was built).
# Needs a free Earthdata login in ~/.netrc (machine urs.earthdata.nasa.gov login USER password PASS)
# or EARTHDATA_TOKEN, and: pip install -r requirements.txt
#
# Kenyan Rift lakes (Nakuru, Elmenteita, Naivasha), January to August 2025, tile 37MAV.
set -euo pipefail
cd "$(dirname "$0")/.."
BBOX=36.0,-0.95,36.45,-0.12
# 1. See which scenes exist and what flag each has (small; reads only metadata).
python3 -m ecogeocheck fetch --bbox $BBOX --start 2025-01-01 --end 2025-08-31 --tiles 37MAV --dest real_data --list
# 2. Download the LST, cloud and water layers and record the flags in real_data/geo_flags.csv.
python3 -m ecogeocheck fetch --bbox $BBOX --start 2025-01-01 --end 2025-08-31 --tiles 37MAV --dest real_data
# 3. Check them. geo_flags.csv in the folder is picked up automatically.
python3 -m ecogeocheck check real_data --out real_output
echo "Open real_output/summary.md and real_output/quicklook.png"
