#!/usr/bin/env bash
# Kano Plains, Kisumu County, Kenya: long-rains floods, late April / early May 2024.
# Fetch data first:  python demo/fetch_demo_data.py
set -euo pipefail
cd "$(dirname "$0")/.."
D=demo/data
S1BASE="$D/s1/S1_VV_20240224.tif $D/s1/S1_VV_20240307.tif"
COMMON="--permanent $D/wofs_alltime_frequency.tif --zones $D/zones_subcounties.geojson"

# 1. Main run: Sentinel-1 (stand-in for OPERA DSWx-S1) on 6 May 2024 vs two dry-season dates,
#    Digital Earth Africa cropland mask, Kenya sub-counties
python -m floodcrop --source sar --event $D/s1/S1_VV_20240506.tif --baseline $S1BASE \
  --cropland $D/deafrica_cropmask_2019.tif --crop-preset deafrica $COMMON \
  --out demo/output_sar_deafrica --title "Flooded cropland, Kano Plains, 6 May 2024 (Sentinel-1 vs Feb-Mar; DE Africa crop mask)"

# 2. Same, ESA WorldCover 2021 cropland instead
python -m floodcrop --source sar --event $D/s1/S1_VV_20240506.tif --baseline $S1BASE \
  --cropland $D/worldcover_2021_v200.tif --crop-preset worldcover $COMMON \
  --out demo/output_sar_worldcover --title "Flooded cropland, Kano Plains, 6 May 2024 (Sentinel-1; WorldCover 2021 cropland)"

# 3. Peak extent over two passes (24 Apr + 6 May), counties instead of sub-counties
python -m floodcrop --source sar --event $D/s1/S1_VV_20240424.tif $D/s1/S1_VV_20240506.tif --baseline $S1BASE \
  --cropland $D/deafrica_cropmask_2019.tif --crop-preset deafrica \
  --permanent $D/wofs_alltime_frequency.tif --zones $D/zones_counties.geojson \
  --out demo/output_sar_peak_counties --title "Flooded cropland, any of 24 Apr / 6 May 2024, by county (Sentinel-1)"

# 4. Optical: Sentinel-2 L2A with the DSWx-HLS tests (stand-in for OPERA DSWx-HLS),
#    30 Apr + 10 May vs 10 + 15 Feb 2024. Tile 36MYE misses the AOI west of ~34.8E.
python -m floodcrop --source optical \
  --event $D/s2/S2_SR_20240430.tif $D/s2/S2_SR_20240510.tif --event-clouds $D/s2/S2_SCL_20240430.tif $D/s2/S2_SCL_20240510.tif \
  --baseline $D/s2/S2_SR_20240210.tif $D/s2/S2_SR_20240215.tif --baseline-clouds $D/s2/S2_SCL_20240210.tif $D/s2/S2_SCL_20240215.tif \
  --cropland $D/deafrica_cropmask_2019.tif --crop-preset deafrica $COMMON \
  --out demo/output_optical_deafrica --title "Flooded cropland, Kano Plains, 30 Apr + 10 May 2024 (Sentinel-2, DSWx-HLS tests)"

# 5. Sensitivity of the Sentinel-1 result to its thresholds
python demo/sensitivity.py
