"""Run the QGIS Processing script headless in real QGIS (3.34 tested).

Usage (Python that has QGIS, e.g. /usr/bin/python3.12 on Ubuntu with python3-qgis):
    QT_QPA_PLATFORM=offscreen python3 tests/qgis_smoke.py OUT_DIR
"""
import glob
import importlib.util
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append("/usr/share/qgis/python/plugins")
from qgis.core import QgsApplication, QgsProcessingProvider, QgsRasterLayer  # noqa: E402

app = QgsApplication([], False)
app.initQgis()
from processing.core.Processing import Processing  # noqa: E402
import processing  # noqa: E402
Processing.initialize()

spec = importlib.util.spec_from_file_location("ng", os.path.join(ROOT, "qgis", "nisargunw_processing.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class Provider(QgsProcessingProvider):
    def loadAlgorithms(self):
        self.addAlgorithm(m.NisarGunwToGeoTiff())

    def id(self):
        return "nisartest"

    def name(self):
        return "nisartest"


provider = Provider()  # keep a reference or Python frees it
QgsApplication.processingRegistry().addProvider(provider)
out = sys.argv[1]
h5 = glob.glob(os.path.join(ROOT, "demo", "data", "NISAR_L2_*GUNW*.h5"))[0]
dem = os.path.join(ROOT, "demo", "data", "dem_fentale.tif")
res = processing.run("nisartest:nisargunwtogeotiff", {
    "INPUT": h5, "PRESET": 1, "LAYERS": "wrapped_phase", "DEM": dem,
    "EXTENT": "39.88,39.98,8.93,9.02 [EPSG:4326]", "LOAD": False, "OUTPUT": out})
print(json.dumps({k: os.path.basename(str(v)) for k, v in res.items()}, indent=1))
for k, v in res.items():
    if str(v).endswith(".tif"):
        lyr = QgsRasterLayer(v, k)
        assert lyr.isValid(), v
        print(f"{k:24s} {lyr.width()}x{lyr.height()} {lyr.crs().authid()}")
with open(res["METADATA"]) as f:
    meta = json.load(f)
print("corrections:", meta["corrections"]["applied"], "reader:", meta["reader"])
app.exitQgis()
