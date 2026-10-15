#!/usr/bin/env bash
# El Geneina, West Darfur, Sudan. Large parts of the town, including several
# camps for displaced people, were attacked and burned from 24 April 2023.
# Run 1 compares early April with late May / mid June 2023.
# Run 2 is a control: the same months in 2022, when there was no such attack,
# to show how many false alarms the rules give from the season alone.
set -euo pipefail
cd "$(dirname "$0")"
export CURL_CA_BUNDLE=${CURL_CA_BUNDLE:-/etc/ssl/certs/ca-certificates.crt}
BBOX="22.40 13.41 22.49 13.49"
PY="python -m burncheck"
export PYTHONPATH=..:${PYTHONPATH:-}

$PY fetch-buildings --bbox $BBOX --out data/buildings.geojson
$PY fetch-places    --bbox $BBOX --out data/places.geojson
$PY fetch-s2 --bbox $BBOX --start 2023-03-28 --end 2023-04-20 --out data/s2_2023_before
$PY fetch-s2 --bbox $BBOX --start 2023-05-25 --end 2023-06-20 --out data/s2_2023_after
$PY fetch-s2 --bbox $BBOX --start 2022-03-28 --end 2022-04-20 --out data/s2_2022_before
$PY fetch-s2 --bbox $BBOX --start 2022-05-25 --end 2022-06-20 --out data/s2_2022_after

$PY run --before 'data/s2_2023_before/*.tif' --after 'data/s2_2023_after/*.tif' \
  --buildings data/buildings.geojson --places data/places.geojson --out output_2023
$PY run --before 'data/s2_2022_before/*.tif' --after 'data/s2_2022_after/*.tif' \
  --buildings data/buildings.geojson --places data/places.geojson --out output_2022_control
