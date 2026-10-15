"""The Time Profile dock: pick a scenes folder, click the map or use selected
features, and see the chart. Extraction runs in a background QgsTask."""

import json
import os

from qgis.core import (QgsApplication, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsGeometry,
                       QgsProject, QgsSettings, QgsTask, QgsVectorLayer)
from qgis.gui import QgsDockWidget, QgsMapToolEmitPoint, QgsRubberBand, QgsVertexMarker
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                                 QSpinBox, QVBoxLayout, QWidget)

from . import chartdata
from .chart import ChartWidget
from .timeprofile import catalog, gdal_io, geom, report
from .timeprofile.extract import Extractor, extract
from .timeprofile.indices import INDICES, resolve
from .timeprofile.report import PALETTE

WGS84 = QgsCoordinateReferenceSystem("EPSG:4326")
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


class _Task(QgsTask):
    """Runs fn() off the main thread, then done(result, error) on it."""

    def __init__(self, title, fn, done):
        super().__init__(title)
        self.fn, self.done, self.result, self.error = fn, done, None, None

    def run(self):
        try:
            self.result = self.fn(self)
            return True
        except Exception as e:  # reported in finished()
            self.error = f"{type(e).__name__}: {e}"
            return False

    def finished(self, ok):
        self.done(self.result, self.error if not ok else None)


class TimeProfileDock(QgsDockWidget):
    def __init__(self, iface):
        super().__init__("Time Profile")
        self.setObjectName("TimeProfileDock")
        self.iface, self.canvas = iface, iface.mapCanvas()
        self.scenes, self.features, self.rows, self.post = [], [], [], {}
        self.colors, self.marks, self._tasks, self._n = {}, [], [], 0
        self.extractor = None

        w = QWidget()
        lay = QVBoxLayout(w)
        row = QHBoxLayout()
        self.folder = QLineEdit(QgsSettings().value("timeprofile/folder", ""))
        self.folder.setPlaceholderText("Folder of scenes (HLS, Sentinel-2, Landsat or dated GeoTIFFs)")
        b = QPushButton("Browse…")
        b.clicked.connect(self._browse)
        s = QPushButton("Scan")
        s.clicked.connect(self.scan)
        row.addWidget(self.folder, 1)
        row.addWidget(b)
        row.addWidget(s)
        lay.addLayout(row)
        self.info = QLabel("No scenes loaded.")
        self.info.setWordWrap(True)
        lay.addWidget(self.info)

        row = QHBoxLayout()
        row.addWidget(QLabel("Index"))
        self.index = QComboBox()
        self.index.setEditable(True)
        self.index.addItems(list(INDICES) + ["red", "nir", "swir1"])
        self.index.setToolTip("A built-in index, a band name, or your own formula, e.g. MSI=swir1/nir")
        self.index.currentTextChanged.connect(lambda _: self.rerun())
        row.addWidget(self.index, 1)
        self.mask = QCheckBox("Cloud mask")
        self.mask.setChecked(True)
        self.mask.toggled.connect(lambda _: self.rerun(reset=True))
        row.addWidget(self.mask)
        row.addWidget(QLabel("Point buffer"))
        self.buffer = QSpinBox()
        self.buffer.setRange(0, 10)
        self.buffer.setSuffix(" px")
        self.buffer.setToolTip("Also average this many pixels around a clicked point (1 = 3x3)")
        self.buffer.valueChanged.connect(lambda _: self.rerun(reset=True))
        row.addWidget(self.buffer)
        lay.addLayout(row)

        row = QHBoxLayout()
        self.view = QComboBox()
        self.view.addItems(["Through time", "Season by season"])
        self.view.currentIndexChanged.connect(lambda _: self.redraw())
        row.addWidget(self.view)
        row.addWidget(QLabel("starting"))
        self.season = QComboBox()
        self.season.addItems(MONTHS)
        self.season.currentIndexChanged.connect(lambda _: self.redraw(recompute=True))
        row.addWidget(self.season)
        self.which = QComboBox()
        self.which.setToolTip("Place shown in the season-by-season view")
        self.which.currentIndexChanged.connect(lambda _: self.redraw())
        row.addWidget(self.which, 1)
        lay.addLayout(row)

        row = QHBoxLayout()
        self.pick = QPushButton("Click on map")
        self.pick.setCheckable(True)
        self.pick.toggled.connect(self._tool)
        sel = QPushButton("Selected features")
        sel.setToolTip("Chart the selected points or polygons of the active layer")
        sel.clicked.connect(self.use_selected)
        self.keep = QCheckBox("Keep earlier")
        self.keep.setToolTip("Add each new place to the chart instead of replacing it")
        self.keep.setChecked(True)
        clear = QPushButton("Clear")
        clear.clicked.connect(lambda: self.clear())
        for x in (self.pick, sel, self.keep, clear):
            row.addWidget(x)
        lay.addLayout(row)

        self.chart = ChartWidget()
        lay.addWidget(self.chart, 1)
        row = QHBoxLayout()
        self.status = QLabel("")
        self.status.setWordWrap(True)
        row.addWidget(self.status, 1)
        for text, fn in (("Save CSV…", self.save_csv), ("Save PNG…", self.save_png)):
            bt = QPushButton(text)
            bt.clicked.connect(fn)
            row.addWidget(bt)
        lay.addLayout(row)
        self.setWidget(w)

        self.tool = QgsMapToolEmitPoint(self.canvas)
        self.tool.canvasClicked.connect(self._clicked)
        if self.folder.text():
            self.scan()

    # --- scenes -------------------------------------------------------------------
    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Folder of scenes", self.folder.text())
        if d:
            self.folder.setText(d)
            self.scan()

    def scan(self):
        path = self.folder.text().strip()
        if not os.path.exists(path):
            self.info.setText("That folder does not exist.")
            return
        QgsSettings().setValue("timeprofile/folder", path)
        self.info.setText("Scanning…")

        def done(scenes, err):
            if err:
                self.info.setText(f"Could not read the folder: {err}")
                return
            self.scenes = scenes or []
            self.extractor = None
            self.info.setText(catalog.describe(self.scenes))
            self.rerun()
        self._start("Time Profile: scanning", lambda t: catalog.scan(path, gdal_io.info), done)

    # --- places -------------------------------------------------------------------
    def _tool(self, on):
        if on:
            self.canvas.setMapTool(self.tool)
        elif self.canvas.mapTool() is self.tool:
            self.canvas.unsetMapTool(self.tool)

    def _to_wgs84(self, crs):
        return QgsCoordinateTransform(crs, WGS84, QgsProject.instance())

    def _clicked(self, pt, button):
        if button != Qt.MouseButton.LeftButton:
            return
        ll = self._to_wgs84(self.canvas.mapSettings().destinationCrs()).transform(pt)
        self._n += 1
        f = {"name": f"Point {self._n} ({ll.y():.4f}, {ll.x():.4f})", "kind": "point", "coords": (ll.x(), ll.y())}
        color = self._color(f["name"])
        m = QgsVertexMarker(self.canvas)
        m.setCenter(pt)
        m.setColor(QColor(color))
        m.setIconSize(12)
        m.setPenWidth(3)
        self.marks.append(m)
        self.add([f])

    def use_selected(self):
        layer = self.iface.activeLayer()
        if not isinstance(layer, QgsVectorLayer) or layer.selectedFeatureCount() == 0:
            self.status.setText("Select some points or polygons in the active vector layer first.")
            return
        ct = self._to_wgs84(layer.crs())
        names = {fl.name().lower(): fl.name() for fl in layer.fields()}
        name_field = names.get("name")
        feats, skipped = [], 0
        for ft in layer.selectedFeatures():
            g = QgsGeometry(ft.geometry())
            g.transform(ct)
            nm = str(ft[name_field]) if name_field and ft[name_field] not in (None, "") else f"{layer.name()} #{ft.id()}"
            try:
                feats.append(geom.feature(nm, json.loads(g.asJson(7))))
            except (ValueError, KeyError):
                skipped += 1
                continue
            rb = self._band()
            rb.setToGeometry(ft.geometry(), layer)
            col = QColor(self._color(nm))
            rb.setStrokeColor(col)
            col.setAlpha(40)
            rb.setFillColor(col)
            rb.setWidth(2)
            self.marks.append(rb)
        if skipped:
            self.status.setText(f"{skipped} features skipped (only points and polygons are supported).")
        if feats:
            self.add(feats)

    def _band(self):
        try:
            from qgis.core import Qgis
            return QgsRubberBand(self.canvas, Qgis.GeometryType.Polygon)
        except (ImportError, AttributeError, TypeError):
            from qgis.core import QgsWkbTypes
            return QgsRubberBand(self.canvas, QgsWkbTypes.PolygonGeometry)

    def _color(self, name):
        if name not in self.colors:
            used = set(self.colors.values())
            self.colors[name] = next((c for c in PALETTE if c not in used), PALETTE[len(self.colors) % len(PALETTE)])
        return self.colors[name]

    def add(self, feats):
        names = {f["name"] for f in feats}
        if not self.keep.isChecked():
            n = len(feats)
            self.clear(keep_marks=self.marks[-n:], keep_names=names)
        self.features = [f for f in self.features if f["name"] not in names] + feats
        self.run(feats)

    def clear(self, keep_marks=(), keep_names=()):
        for m in self.marks:
            if m not in keep_marks:
                self.canvas.scene().removeItem(m)
        self.marks = list(keep_marks)
        self.features, self.rows, self.post = [], [], {}
        self.colors = {k: v for k, v in self.colors.items() if k in keep_names}
        self.redraw()

    # --- extraction ---------------------------------------------------------------
    def rerun(self, reset=False):
        if reset:
            self.extractor = None
        if self.features:
            self.rows = []
            self.run(list(self.features))

    def run(self, feats):
        if not self.scenes:
            self.status.setText("Choose a scenes folder first.")
            return
        try:
            formula = resolve(self.index.currentText())
        except (ValueError, SyntaxError) as e:
            self.status.setText(f"Index: {e}")
            return
        if self.extractor is None:
            self.extractor = Extractor(gdal_io, self.mask.isChecked(), (), self.buffer.value())
        ex, scenes = self.extractor, list(self.scenes)
        self.status.setText(f"Reading {len(scenes)} scenes…")

        def work(task):
            def prog(i, n):
                task.setProgress(100.0 * i / n)
            return extract(scenes, feats, [formula], gdal_io, progress=prog, cancelled=task.isCanceled, extractor=ex)

        def done(res, err):
            if err:
                self.status.setText(f"Failed: {err}")
                return
            rows, notes = res
            names = {f["name"] for f in feats}
            self.rows = [r for r in self.rows if r["feature"] not in names] + rows
            clear = sum(r["status"] == "clear" for r in rows)
            msg = f"{clear} clear observations of {len(rows)} for {len(feats)} place(s)."
            if not rows:
                msg = "No scene covers that place."
            elif notes:
                msg += f" {len(notes)} note(s), e.g. {notes[0]}"
            self.status.setText(msg)
            self.redraw(recompute=True)
        self._start("Time Profile: extracting", work, done)

    def _start(self, title, fn, done):
        def finish(res, err):
            self._tasks = [t for t in self._tasks if t is not task]
            done(res, err)
        task = _Task(title, fn, finish)
        self._tasks.append(task)  # keep the Python object alive while the task runs
        QgsApplication.taskManager().addTask(task)

    # --- chart --------------------------------------------------------------------
    def redraw(self, recompute=False):
        start = self.season.currentIndex() + 1
        if recompute:
            self.post = report.postprocess(self.rows, season_start=start)
        idx = resolve(self.index.currentText()).name if self.index.currentText().strip() else ""
        feats = list(dict.fromkeys(r["feature"] for r in self.rows if r["index"] == idx))
        cur = self.which.currentText()
        self.which.blockSignals(True)
        self.which.clear()
        self.which.addItems(feats)
        if cur in feats:
            self.which.setCurrentText(cur)
        elif feats:
            self.which.setCurrentIndex(len(feats) - 1)
        self.which.blockSignals(False)
        self.which.setEnabled(self.view.currentIndex() == 1)
        if self.view.currentIndex() == 1 and self.which.currentText():
            s = chartdata.season_series(self.rows, self.post, idx, self.which.currentText(), start)
            self.chart.set_data(s, "season", idx, start, title=f"{self.which.currentText()}: {idx} by season")
        else:
            s = chartdata.time_series(self.rows, self.post, idx, self.colors)
            self.chart.set_data(s, "time", idx, start)

    def save_csv(self):
        if not self.rows:
            return
        p, _ = QFileDialog.getSaveFileName(self, "Save CSV", "time_profile.csv", "CSV (*.csv)")
        if p:
            report.write_csv(p, self.rows)

    def save_png(self):
        p, _ = QFileDialog.getSaveFileName(self, "Save chart", "time_profile.png", "PNG (*.png)")
        if p:
            self.chart.save_png(p)

    def cleanup(self):
        self.clear()
        if self.canvas.mapTool() is self.tool:
            self.canvas.unsetMapTool(self.tool)
