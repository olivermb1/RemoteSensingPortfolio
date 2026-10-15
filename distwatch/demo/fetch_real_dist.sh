#!/usr/bin/env bash
# Run this on your own computer: it downloads real OPERA DIST-ALERT-HLS
# granules over the Ghana / Cote d'Ivoire cocoa belt and runs DIST Watch.
#
# Needs: pip install rasterio shapely pyproj requests matplotlib
#        a free NASA Earthdata login, in ~/.netrc:
#          machine urs.earthdata.nasa.gov login YOUR_USER password YOUR_PASSWORD
#        or as a token: export EARTHDATA_TOKEN=...
#
# Untested: NASA's servers were not reachable where this was written.
set -euo pipefail
cd "$(dirname "$0")/.."
AREAS=${1:-demo/real_areas_cocoa_belt.geojson}
STATE=${2:-demo/real_state}

# 1. See what is there (no download).
python3 -m distwatch fetch --areas "$AREAS" --dest "$STATE/granules" --list
# 2. Download the newest granule per tile and run. Re-run this script later:
#    only loss that appeared since this run will be reported.
python3 -m distwatch run --areas "$AREAS" --state "$STATE" --fetch \
  --out "demo/real_output/run_$(date +%Y-%m-%d)"
