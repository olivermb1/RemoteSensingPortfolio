"""Run the QGIS plugin's algorithms headless. Usage: python3 tests/qgis_smoke.py OUT_DIR

Needs QGIS's Python (python3-qgis). Builds the plugin folder first with qgis_plugin/make_plugin.py.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "demo", "data")
OUT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/qamask_qgis"
os.makedirs(OUT, exist_ok=True)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qgis.core import Qgis, QgsApplication, QgsProcessingContext, QgsProcessingFeedback, QgsProject, QgsRasterLayer  # noqa: E402

app = QgsApplication([], False)
app.initQgis()
sys.path.insert(0, "/usr/share/qgis/python/plugins")
sys.path.insert(0, os.path.join(ROOT, "qgis_plugin"))
import processing  # noqa: E402
from processing.core.Processing import Processing  # noqa: E402

Processing.initialize()
from qa_mask_builder.provider import QAMaskProvider  # noqa: E402

prov = QAMaskProvider()
QgsApplication.processingRegistry().addProvider(prov)
algs = [a.id() for a in prov.algorithms()]
print("QGIS", Qgis.version(), "algorithms:", len(algs))

hls = os.path.join(DATA, "HLS.L30.T19JHN.2024279T141847.v2.0.Fmask.tif")
ls = os.path.join(DATA, "LC08_L2SP_169060_20241104_20241113_02_T1_QA_PIXEL_crop.tif")
b5 = os.path.join(DATA, "LC08_L2SP_169060_20241104_20241113_02_T1_SR_B5_crop.tif")
conf = os.path.join(DATA, "OPERA_L3_DSWx-HLS_T19JHN_20241005T141847Z_L8_30_v1.0_B03_CONF.tif")

fb = QgsProcessingFeedback()
r = processing.run("qamaskbuilder:build_hls_fmask", {"INPUT": hls, "OUTPUT": os.path.join(OUT, "hls_mask.tif")}, feedback=fb)
lyr = QgsRasterLayer(r["OUTPUT"], "m")
print("hls mask:", lyr.isValid(), lyr.crs().authid())
assert lyr.crs().authid() == "EPSG:32719"

r = processing.run("qamaskbuilder:build_landsat_c2_qa_pixel",
                   {"INPUT": ls, "PRESET": 0, "DROP": [2, 3], "BUFFER": 1, "OUTPUT": os.path.join(OUT, "ls_mask.tif")}, feedback=fb)
r2 = processing.run("qamaskbuilder:apply_mask", {"DATA": b5, "MASK": r["OUTPUT"], "OUTPUT": os.path.join(OUT, "b5_masked.tif")})
print("apply:", QgsRasterLayer(r2["OUTPUT"], "b").isValid())

r = processing.run("qamaskbuilder:build_opera_dswx_hls_conf", {"INPUT": conf, "OUTPUT": os.path.join(OUT, "water.tif")}, feedback=fb)
r = processing.run("qamaskbuilder:fix_hls_crs", {"INPUT": hls, "VRT": True, "OUTPUT": os.path.join(OUT, "hls_fixed.vrt")})
print("fix vrt:", QgsRasterLayer(r["OUTPUT"], "f").crs().authid())
r = processing.run("qamaskbuilder:decode", {"INPUT": hls, "PRODUCT": 0, "OUTPUT": os.path.join(OUT, "decoded.tif")})
print("decode bands:", QgsRasterLayer(r["OUTPUT"], "d").bandCount())

# The style sidecar loads onto the layer when the output is added to a project
ctx = QgsProcessingContext()
ctx.setProject(QgsProject.instance())
alg = QgsApplication.processingRegistry().createAlgorithmById("qamaskbuilder:build_hls_fmask")
res, ok = alg.run({"INPUT": hls, "OUTPUT": os.path.join(OUT, "hls_mask2.tif")}, ctx, fb)
details = ctx.layerToLoadOnCompletionDetails(res["OUTPUT"]) if ctx.willLoadLayerOnCompletion(res["OUTPUT"]) else None
lyr = QgsRasterLayer(res["OUTPUT"], "m2")
if details and details.postProcessor():
    details.postProcessor().postProcessLayer(lyr, ctx, fb)
print("renderer after post-processor:", lyr.renderer().type(), [c.label for c in lyr.renderer().classes()])
app.exitQgis()
print("OK")
