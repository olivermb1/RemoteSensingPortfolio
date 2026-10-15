"""Drive the plugin's dock with real Qt6 widgets but stand-in QGIS classes (no QGIS here):
scan the demo folder, click two points, switch index and view, save CSV and PNG.
Background tasks run synchronously. rasterio stands in for GDAL.

    QT_QPA_PLATFORM=offscreen python tests/test_dock_stubbed.py
"""

import os
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [os.path.join(HERE, "qt_shim"), os.path.join(ROOT, "qgis_plugin")]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

DEMO = os.path.join(ROOT, "demo", "data", "s2_mwea")
if not os.path.isdir(DEMO):  # the demo scenes are not in git; demo/run_demo.sh downloads them
    if __name__ == "__main__":
        sys.exit("Run demo/run_demo.sh first: this test needs the demo scenes in " + DEMO)
    import pytest

    pytest.skip("needs the demo scenes; run demo/run_demo.sh first", allow_module_level=True)

from PyQt6.QtCore import QObject, Qt, pyqtSignal  # noqa: E402
from PyQt6.QtWidgets import QApplication, QDockWidget, QFileDialog  # noqa: E402

app = QApplication([])

# --- stand-in qgis.core / qgis.gui ------------------------------------------------------
core = types.ModuleType("qgis.core")
gui = types.ModuleType("qgis.gui")


class QgsTask:
    def __init__(self, title):
        self.title = title

    def setProgress(self, p):
        pass

    def isCanceled(self):
        return False


class _TM:
    def addTask(self, t):
        t.finished(t.run())


class QgsApplication:
    @staticmethod
    def taskManager():
        return _TM()


class QgsSettings:
    store = {}

    def value(self, k, d=None):
        return self.store.get(k, d)

    def setValue(self, k, v):
        self.store[k] = v


class QgsCoordinateReferenceSystem:
    def __init__(self, s=""):
        self.s = s


class QgsPointXY:
    def __init__(self, x, y):
        self._x, self._y = x, y

    def x(self):
        return self._x

    def y(self):
        return self._y


class QgsCoordinateTransform:
    def __init__(self, *a):
        pass

    def transform(self, p):
        return p  # canvas is in EPSG:4326 in this test


class QgsProject:
    @staticmethod
    def instance():
        return None


for c in (QgsTask, QgsApplication, QgsSettings, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject,
          QgsPointXY):
    setattr(core, c.__name__, c)
core.QgsGeometry = core.QgsVectorLayer = type("Unused", (), {})


class QgsMapToolEmitPoint(QObject):
    canvasClicked = pyqtSignal(object, object)

    def __init__(self, canvas):
        super().__init__()


class QgsVertexMarker:
    def __init__(self, canvas):
        pass

    def __getattr__(self, k):
        return lambda *a: None


class _Scene:
    removed = 0

    def removeItem(self, m):
        _Scene.removed += 1


class Canvas:
    tool = None

    def mapSettings(self):
        return types.SimpleNamespace(destinationCrs=lambda: QgsCoordinateReferenceSystem("EPSG:4326"))

    def setMapTool(self, t):
        self.tool = t

    def mapTool(self):
        return self.tool

    def unsetMapTool(self, t):
        self.tool = None

    def scene(self):
        return _Scene()


gui.QgsDockWidget = QDockWidget
gui.QgsMapToolEmitPoint = QgsMapToolEmitPoint
gui.QgsVertexMarker = QgsVertexMarker
gui.QgsRubberBand = object
sys.modules["qgis.core"], sys.modules["qgis.gui"] = core, gui
import qgis  # noqa: E402

qgis.core, qgis.gui = core, gui

import time_profile.timeprofile as tp  # noqa: E402
sys.path.append(ROOT)
from timeprofile import rio_io  # noqa: E402

sys.modules["time_profile.timeprofile.gdal_io"] = rio_io
tp.gdal_io = rio_io
from time_profile.dock import TimeProfileDock  # noqa: E402

iface = types.SimpleNamespace(mapCanvas=lambda: Canvas(), activeLayer=lambda: None)
QgsSettings.store["timeprofile/folder"] = DEMO
dock = TimeProfileDock(iface)
assert dock.scenes and "100 scenes" in dock.info.text(), dock.info.text()

dock.pick.setChecked(True)
assert dock.canvas.mapTool() is dock.tool
dock.tool.canvasClicked.emit(QgsPointXY(37.3367, -0.6693), Qt.MouseButton.LeftButton)   # north block
dock.tool.canvasClicked.emit(QgsPointXY(37.3228, -0.6745), Qt.MouseButton.LeftButton)   # village edge
feats = {r["feature"] for r in dock.rows}
assert len(feats) == 2, feats
assert len(dock.chart.series) == 2 and dock.chart.series[0]["color"] != dock.chart.series[1]["color"]
print(dock.status.text())

dock.index.setCurrentText("NDMI")  # re-extracts for both points
assert {r["index"] for r in dock.rows} == {"NDMI"}, {r["index"] for r in dock.rows}
dock.index.setCurrentText("bad=nir+")  # a broken formula must not crash
assert "Index" in dock.status.text(), dock.status.text()
dock.index.setCurrentText("NDVI")
dock.view.setCurrentIndex(1)
assert dock.chart.mode == "season" and dock.which.isEnabled()
dock.season.setCurrentIndex(9)  # seasons from October
assert any("-" in s["name"] for s in dock.chart.series), [s["name"] for s in dock.chart.series]

tmp = tempfile.mkdtemp()
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (os.path.join(tmp, "x.csv"), ""))
dock.save_csv()
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (os.path.join(tmp, "x.png"), ""))
dock.save_png()
assert os.path.getsize(os.path.join(tmp, "x.csv")) > 1000 and os.path.getsize(os.path.join(tmp, "x.png")) > 1000

dock.keep.setChecked(False)
dock.view.setCurrentIndex(0)
dock.tool.canvasClicked.emit(QgsPointXY(37.3300, -0.6550), Qt.MouseButton.LeftButton)
assert len({r["feature"] for r in dock.rows}) == 1 and _Scene.removed == 2, (_Scene.removed,)
dock.tool.canvasClicked.emit(QgsPointXY(10.0, 10.0), Qt.MouseButton.LeftButton)  # nowhere near the scenes
assert "No scene covers" in dock.status.text(), dock.status.text()
dock.cleanup()
print("dock ok")
