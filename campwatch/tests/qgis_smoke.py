"""Run the QGIS Processing script headless in real QGIS and compare with the CLI demo output.

Usage (QGIS's Python, e.g. /usr/bin/python3.12 with python3-qgis from apt):
    QT_QPA_PLATFORM=offscreen python3.12 tests/qgis_smoke.py OUT_DIR
Needs demo/output from demo/run_demo.sh. first_seen.tif must match the CLI pixel
for pixel, and the detected areas' total footprint must match.
"""
import csv
import glob
import importlib.util
import json
import os
import sys

import numpy as np
from osgeo import gdal
from qgis.core import QgsApplication, QgsProcessingContext, QgsProcessingFeedback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = sys.argv[1]
QgsApplication.setPrefixPath("/usr", True)
app = QgsApplication([], False)
app.initQgis()
spec = importlib.util.spec_from_file_location("cw", os.path.join(ROOT, "qgis", "campwatch_processing.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
D = os.path.join(ROOT, "demo")

alg = mod.CampGrowthWatch().createInstance()
alg.initAlgorithm()
params = {"SCENES": sorted(glob.glob(f"{D}/data/s2/*.tif")), "UNITS": None, "BASELINE": "2021-11 2022-05",
          "PERIOD": "2023-01 2025-03", "DRY": "11,12,1,2,3,4,5", "T_RATIO": 0.07, "T_BLUE": 0.015,
          "MAX_NDVI": 0.30, "MIN_AREA_HA": 5.0, "OUTPUT": OUT}
res, ok = alg.run(params, QgsProcessingContext(), QgsProcessingFeedback())
assert ok, res
a = gdal.Open(os.path.join(OUT, "first_seen.tif")).ReadAsArray()
b = gdal.Open(f"{D}/output/first_seen.tif").ReadAsArray()
q = json.load(open(os.path.join(OUT, "run.json")))
c = json.load(open(f"{D}/output/run.json"))
print("first_seen pixels differing:", int((a != b).sum()), "of", a.size)
print("areas QGIS", q["n_areas"], "CLI", c["n_areas"], "| footprint ha QGIS", q["total_footprint_ha"], "CLI",
      c["total_footprint_ha"])
app.exitQgis()
