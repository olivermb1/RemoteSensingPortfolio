#!/bin/sh
# Composite Check on real NASA HLS v2.0: Nakuru, Kenya, January to June 2024.
# Needs a free NASA Earthdata login (https://urs.earthdata.nasa.gov) and
#   pip install -r requirements.txt earthaccess
# Run from the compositecheck folder. First run asks for your Earthdata login
# and saves it to ~/.netrc. Downloads roughly 100-200 MB (only the area is read).
set -e
cd "$(dirname "$0")/.."
BBOX="36.00 -0.40 36.12 -0.28"
python3 -m compositecheck.fetch --bbox $BBOX --start 2024-01-01 --end 2024-06-30 --out demo/hls_real
COMMON="demo/hls_real --bbox $BBOX --start 2024-01-01 --end 2024-06-30 --target 2024-03-31 --dilate 1"
python3 -m compositecheck $COMMON --method medoid --out demo/output_hls_medoid \
  --title "Nakuru, Kenya, Jan-Jun 2024: medoid of real HLS L30 + S30"
python3 -m compositecheck $COMMON --method target --out demo/output_hls_target \
  --title "Nakuru, Kenya, Jan-Jun 2024: closest clear date to 31 Mar, real HLS"
echo
echo "Done. Send back demo/output_hls_medoid/report.json and demo/output_hls_target/report.json"
echo "(and the report.png files) to compare with the HLS-like demo."
