"""Run the QGIS Processing script headless in real QGIS and compare with the CLI demo output.

Usage (QGIS's Python, e.g. /usr/bin/python3.12 with python3-qgis from apt):
    QT_QPA_PLATFORM=offscreen python3.12 tests/qgis_smoke.py SCENE_DIR OUT_DIR
SCENE_DIR holds the Gezira scenes (demo/data/s2_gezira after demo/run_demo.sh).
field_classes.tif must match the CLI's pixel for pixel, and the totals must agree.
"""
import glob
import importlib.util
import json
import os
import sys

from osgeo import gdal
from qgis.core import QgsApplication, QgsProcessingContext, QgsProcessingFeedback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENES, OUT = sys.argv[1], sys.argv[2]
QgsApplication.setPrefixPath("/usr", True)
app = QgsApplication([], False)
app.initQgis()
spec = importlib.util.spec_from_file_location("fc", os.path.join(ROOT, "qgis", "fallowcheck_processing.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
D = os.path.join(ROOT, "demo")
alg = mod.AbandonedFields().createInstance()
alg.initAlgorithm()
params = {"SCENES": sorted(glob.glob(f"{SCENES}/*.tif")), "BASELINE": "2021 2022 2023", "TARGET": 2024,
          "SEASON": "07-15 11-30", "CROPLAND": f"{D}/data/worldcover_2021_gezira.tif", "CLASSES": "40",
          "UNITS": None, "CELL": 1000.0, "MIN_BASE": 0.40, "MAX_TARGET": 0.30, "MIN_DROP": 0.15, "OUTPUT": OUT}
res, ok = alg.run(params, QgsProcessingContext(), QgsProcessingFeedback())
assert ok, res
a = gdal.Open(os.path.join(OUT, "field_classes.tif")).ReadAsArray()
b = gdal.Open(f"{D}/output_gezira/field_classes.tif").ReadAsArray()
q = json.load(open(os.path.join(OUT, "run.json")))
c = json.load(open(f"{D}/output_gezira/run.json"))
print("field_classes pixels differing:", int((a != b).sum()), "of", a.size)
print("not farmed ha QGIS", q["not_farmed_ha"], "CLI", c["target"]["not_farmed_ha"],
      "| pattern-lost units QGIS", q["pattern_lost_units"], "of", q["units_reported"],
      "CLI", c["pattern_lost_units"], "of", c["units_reported"])
app.exitQgis()
