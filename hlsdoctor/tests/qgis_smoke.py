"""Headless check that the QGIS Processing script loads and runs.

    python3.12 tests/qgis_smoke.py      # the Python that has the qgis module

Runs offline on demo/files, then (if the network allows) streams a public HLS
file, and writes a Markdown report to demo/output/qgis_report.md."""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(ROOT, "qgis"))

from qgis.core import QgsApplication, QgsProcessingContext, QgsProcessingFeedback  # noqa: E402

app = QgsApplication([], False)
app.initQgis()
import hlsdoctor_processing as hp  # noqa: E402

PUBLIC = ("https://opera-pst-rs-pop1.s3.us-west-2.amazonaws.com/inputs/HLS_S30/"
          "HLS.S30.T10TCT.2021345T191811.v2.0-r1/HLS.S30.T10TCT.2021345T191811.v2.0.B8A.tif")


class Feedback(QgsProcessingFeedback):
    def __init__(self):
        super().__init__()
        self.lines = []

    def pushInfo(self, s):
        self.lines.append(s)

    def pushWarning(self, s):
        self.lines.append(s)

    def reportError(self, s, fatalError=False):
        self.lines.append(s)


alg = hp.HlsDoctorAlgorithm()
alg.initAlgorithm()
os.makedirs(os.path.join(ROOT, "demo", "output"), exist_ok=True)
out = os.path.join(ROOT, "demo", "output", "qgis_report.md")
params = {"EXTENT": None, "DAYS": 30, "OFFLINE": False, "FOLDER": os.path.join(ROOT, "demo", "files"),
          "STREAM_URL": PUBLIC, "APPLY_GDAL": True, "OUTPUT": out}
fb = Feedback()
res = alg.processAlgorithm(params, QgsProcessingContext(), fb)
print("\n".join(fb.lines))
print(res)
assert os.path.getsize(out) > 500
text = " ".join(" ".join(fb.lines).split())
assert "[OK  ] Stream with GDAL" in " ".join(fb.lines) or "Stream with GDAL" in text
assert "Earthdata login page" in text
from osgeo import gdal  # noqa: E402
assert gdal.GetConfigOption("GDAL_DISABLE_READDIR_ON_OPEN") == "EMPTY_DIR"
print("QGIS smoke test passed with GDAL", gdal.__version__)
app.exitQgis()
