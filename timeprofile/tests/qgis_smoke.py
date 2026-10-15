"""Smoke test to run inside QGIS 3.28+ or QGIS 4 (Plugins > Python Console > Show Editor >
open this file > Run). Needs the plugin installed from qgis_plugin/time_profile.zip.
Set FOLDER to where this timeprofile folder is on your computer."""

import os

import processing
from qgis.core import QgsVectorLayer
from qgis.utils import iface, plugins

FOLDER = os.path.expanduser("~/timeprofile")  # <- edit

layer = QgsVectorLayer(os.path.join(FOLDER, "demo", "mwea_features.geojson"), "mwea", "ogr")
assert layer.isValid(), "features file not found: set FOLDER"
res = processing.run("timeprofile:timeseries", {
    "FEATURES": layer, "NAME_FIELD": "name", "SCENES": os.path.join(FOLDER, "demo", "data", "s2_mwea"),
    "INDEX": "NDVI,MNDWI", "MASK": True, "BUFFER": 0, "MIN_CLEAR": 50, "SEASON_START": 0,
    "OUTPUT": os.path.join(FOLDER, "demo", "output_qgis")})
print(res)
rows = open(res["SERIES"]).read().splitlines()
print(len(rows) - 1, "rows (the command-line demo gives 800)")

# The dock: open it, point it at the demo folder, then click inside the Mwea paddies.
p = plugins["time_profile"]
p.action.setChecked(True)
p.dock.folder.setText(os.path.join(FOLDER, "demo", "data", "s2_mwea"))
p.dock.scan()
iface.mapCanvas().setExtent(layer.extent())
p.dock.pick.setChecked(True)
print("Now click the map; the chart should appear in the Time Profile panel.")
