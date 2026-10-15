#!/usr/bin/env bash
# Alacha refugee camp, Ouaddaï, eastern Chad, set up for
# people fleeing the war in Sudan that began in April 2023. The baseline year is
# the 2021-22 dry season, well before the displacement; the tracked period runs
# from January 2023 to March 2025 (dry-season months only).
set -euo pipefail
cd "$(dirname "$0")"
export CURL_CA_BUNDLE=${CURL_CA_BUNDLE:-/etc/ssl/certs/ca-certificates.crt}
export PYTHONPATH=..:${PYTHONPATH:-}
BBOX="21.565 13.035 21.655 13.115"
PY="python -m campwatch"

$PY fetch-places --bbox $BBOX --out data/places.geojson
for r in "2021-11-01 2022-05-31" "2023-01-01 2023-05-31" "2023-11-01 2024-05-31" "2024-11-01 2025-03-31"; do
  set -- $r
  $PY fetch-s2 --bbox $BBOX --start $1 --end $2 --out data/s2
done
$PY run --scenes 'data/s2/*.tif' --baseline 2021-11 2022-05 --period 2023-01 2025-03 \
  --places data/places.geojson --out output
