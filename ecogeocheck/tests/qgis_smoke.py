"""Headless QGIS run of the Processing script on the demo data.

Run with the Python that has QGIS (e.g. /usr/bin/python3.12 tests/qgis_smoke.py).
Set NO_H5PY=1 to force the GDAL HDF5 path for L1B GEO files.
"""
import os
import sys
import tempfile

if os.environ.get("NO_H5PY"):
    sys.modules["h5py"] = None  # makes `import h5py` raise ImportError
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "qgis"))

from qgis.core import QgsApplication, QgsProcessingContext, QgsProcessingFeedback, QgsProject  # noqa: E402

app = QgsApplication([], False)
app.initQgis()
from ecogeocheck_processing import EcoGeoCheckAlgorithm  # noqa: E402

alg = EcoGeoCheckAlgorithm()
alg.initAlgorithm()
out = tempfile.mkdtemp()
ctx = QgsProcessingContext()
ctx.setProject(QgsProject.instance())
fb = QgsProcessingFeedback()
params = {"INPUT": os.path.join(ROOT, "demo", "data", "scenes"),
          "SUMMARY": os.path.join(ROOT, "demo", "data", "geolocation_summary_example.txt"),
          "ACCEPT": [0, 1], "TOLERANCE": 140, "MAX_SHIFT": 7700, "MEASURE": True, "FIX": True,
          "RESCUE": False, "LOAD_KEPT": True, "OUTPUT_FOLDER": out}
ok, msg = alg.checkParameterValues(params, ctx)
assert ok, msg
res = alg.processAlgorithm(params, ctx, fb)
print(res)
assert res["KEEP"] == 11 and res["DROP"] == 1, res
assert len(os.listdir(os.path.join(out, "shifted"))) == 9  # 3 scenes x 3 layers
assert len(ctx.layersToLoadOnCompletion()) == 12  # scenes layer + 11 kept LST layers
import csv  # noqa: E402
rows = list(csv.DictReader(open(os.path.join(out, "scenes.csv"))))
print({r["time"][:10]: (r["geo_qa"], r["geo_qa_source"][:20], r["offset_m"], r["decision"]) for r in rows})
assert sum(r["geo_qa_source"].startswith("L1B_GEO") for r in rows) == 8
print("QGIS smoke test ok with", "GDAL HDF5" if os.environ.get("NO_H5PY") else "h5py")
app.exitQgis()
