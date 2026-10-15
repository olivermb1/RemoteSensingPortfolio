"""Run the QGIS Processing script headless in real QGIS and compare with the CLI demo output.

Usage (QGIS's Python, e.g. /usr/bin/python3.12 with python3-qgis from apt):
    QT_QPA_PLATFORM=offscreen python3.12 tests/qgis_smoke.py OUT_DIR
Needs demo/output_2023 from demo/run_demo.sh. Case 1 uses the CLI's own units,
so burned and clear pixel counts must match exactly. Case 2 builds units on the
pixel grid and only reports the class counts.
"""
import csv
import glob
import importlib.util
import os
import sys

from qgis.core import QgsApplication, QgsProcessingContext, QgsProcessingFeedback, QgsVectorLayer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = sys.argv[1]
QgsApplication.setPrefixPath("/usr", True)
app = QgsApplication([], False)
app.initQgis()

spec = importlib.util.spec_from_file_location("bc", os.path.join(ROOT, "qgis", "burncheck_processing.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
D = os.path.join(ROOT, "demo")


def run(units, out):
    alg = mod.BurnedSettlementCheck().createInstance()
    alg.initAlgorithm()
    params = {"BEFORE": sorted(glob.glob(f"{D}/data/s2_2023_before/*.tif")),
              "AFTER": sorted(glob.glob(f"{D}/data/s2_2023_after/*.tif")),
              "BUILDINGS": f"{D}/data/buildings.geojson", "UNITS": units, "OUTPUT": out}
    ctx, fb = QgsProcessingContext(), QgsProcessingFeedback()
    res, ok = alg.run(params, ctx, fb)
    assert ok, res
    with open(os.path.join(out, "summary.csv")) as f:
        return list(csv.DictReader(f))


cli = {int(r["unit_id"]): r for r in csv.DictReader(open(f"{D}/output_2023/summary.csv"))}
# CLI units in unit_id order, so feature i+1 = unit_id i+1
lay = QgsVectorLayer(f"{D}/output_2023/units.geojson", "u", "ogr")
feats = sorted(lay.getFeatures(), key=lambda f: f["unit_id"])
tmp = os.path.join(OUT, "cli_units_sorted.geojson")
from qgis.core import QgsVectorFileWriter  # noqa: E402
mem = QgsVectorLayer("MultiPolygon?crs=EPSG:4326&field=unit_id:integer", "s", "memory")
mem.dataProvider().addFeatures(feats)
QgsVectorFileWriter.writeAsVectorFormat(mem, tmp, "utf-8", mem.crs(), "GeoJSON")

rows = run(tmp, os.path.join(OUT, "given_units"))
diff = [(r["unit_id"], r["burned_px"], cli[int(r["unit_id"])]["burned_px"]) for r in rows
        if r["burned_px"] != cli[int(r["unit_id"])]["burned_px"] or r["class"] != cli[int(r["unit_id"])]["class"]]
print(f"case 1 (CLI units): {len(rows)} units, {len(diff)} differ in burned_px or class", diff[:5])

rows = run(None, os.path.join(OUT, "auto_units"))
counts = {}
for r in rows:
    counts[r["class"]] = counts.get(r["class"], 0) + 1
print("case 2 (pixel-grid units):", len(rows), "units", counts)
app.exitQgis()
