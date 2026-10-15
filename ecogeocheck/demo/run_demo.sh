#!/usr/bin/env bash
# Synthetic demo: 12 ECOSTRESS-style scenes over the Kenyan Rift lakes.
# Writes three runs to demo/output/: the default check, the same with --fix, and flags only.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -d demo/data/scenes ] || python3 demo/make_demo_data.py
rm -rf demo/output
python3 -m ecogeocheck check demo/data/scenes --summary demo/data/geolocation_summary_example.txt --out demo/output/default
python3 -m ecogeocheck check demo/data/scenes --summary demo/data/geolocation_summary_example.txt --out demo/output/fix --fix
python3 -m ecogeocheck check demo/data/scenes --summary demo/data/geolocation_summary_example.txt --out demo/output/flags_only --no-measure
# Check the fix: the shifted copies should now measure close to zero.
python3 -m ecogeocheck check demo/output/fix/shifted --out demo/output/fix_recheck --no-stack
