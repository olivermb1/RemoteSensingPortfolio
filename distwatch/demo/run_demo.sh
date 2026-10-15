#!/usr/bin/env bash
# Replays three DIST Watch runs on the synthetic Ghana data, a month apart.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 demo/make_demo_data.py
rm -rf demo/state demo/state_forest demo/output
for d in 2025-01-15 2025-02-15 2025-03-15; do
  python3 -m distwatch run --areas demo/data/areas.geojson --data demo/data/granules \
    --state demo/state --out demo/output/run_$d --as-of $d
  python3 -m distwatch run --areas demo/data/areas.geojson --data demo/data/granules \
    --state demo/state_forest --out demo/output/forest_run_$d --as-of $d \
    --forest-mask demo/data/forest_2020_mask.tif > /dev/null
done
python3 -m distwatch status --state demo/state
