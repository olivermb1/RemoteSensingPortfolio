#!/bin/sh
# Rebuild the demo folder of broken files, check it, and run the doctor here.
set -e
cd "$(dirname "$0")/.."
python3 demo/make_demo_files.py
mkdir -p demo/output
python3 -m hlsdoctor files demo/files > demo/output/files_report.txt || true
python3 -m hlsdoctor check > demo/output/check_report.txt 2>/dev/null || true
python3 -m pytest -q tests
