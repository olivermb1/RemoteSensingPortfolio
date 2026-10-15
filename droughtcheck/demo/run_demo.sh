#!/bin/sh
# Nakuru demo: fetch open data for DE Africa tile x217y076 (35.82-36.81 E, 0-0.75 S),
# then run both steps. About 80 MB of downloads; no logins.
set -e
cd "$(dirname "$0")/.."
D=demo/data
mkdir -p $D
python -m droughtcheck.fetch chirps --bbox 35.8 -0.8 36.85 0.05 --start 1981-01 --end 2026-09 --out $D/chirps_monthly.tif
python -m droughtcheck.fetch temps  --bbox 35.8 -0.8 36.85 0.05 --start 1981-01 --end 2026-09 --out $D/power_tmax_tmin.tif
python -m droughtcheck.fetch ndvi   --tile x217y076 --start 2017-01 --end 2026-09 --overview 8 --out $D/ndvi_anomaly_240m.tif
python -m droughtcheck.fetch worldcover --like $D/ndvi_anomaly_240m.tif --out $D/worldcover_2021_240m.tif
python -m droughtcheck drought --precip $D/chirps_monthly.tif --temps $D/power_tmax_tmin.tif \
    --events-since 2000-01 --out demo/output/drought
python -m droughtcheck greenness --ndvi $D/ndvi_anomaly_240m.tif --clear $D/ndvi_anomaly_240m_clear.tif \
    --drought-dir demo/output/drought --landcover $D/worldcover_2021_240m.tif --out demo/output/greenness
