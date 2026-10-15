#!/usr/bin/env bash
# Gezira irrigation scheme near Wad Madani, Al Jazira state, Sudan. The RSF took
# Wad Madani in December 2023; the 2024 summer season is compared with 2021-2023.
# Control: New Halfa scheme (Kassala state), with no fighting in 2024, same years.
# Scenes (~1 GB each site) are downloaded to data/ and are not kept in the project folder.
set -euo pipefail
cd "$(dirname "$0")"
export CURL_CA_BUNDLE=${CURL_CA_BUNDLE:-/etc/ssl/certs/ca-certificates.crt}
export PYTHONPATH=..:${PYTHONPATH:-}
PY="python -m fallowcheck"

site() {  # name, bbox (4 numbers)
  local name=$1; shift
  $PY fetch-worldcover --bbox "$@" --out data/worldcover_2021_$name.tif
  for y in 2021 2022 2023 2024; do
    $PY fetch-s2 --bbox "$@" --start $y-07-15 --end $y-11-30 --out data/s2_$name
  done
  $PY run --scenes "data/s2_$name/*.tif" --baseline-years 2021 2022 2023 --target-year 2024 \
    --season 07-15 11-30 --cropland data/worldcover_2021_$name.tif $PLACES --out output_$name
}
$PY fetch-places --bbox 33.38 14.20 33.50 14.32 --out data/places_gezira.geojson
PLACES="--places data/places_gezira.geojson" site gezira 33.38 14.20 33.50 14.32
PLACES="" site newhalfa 35.55 15.28 35.65 15.38
