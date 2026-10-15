"""Render the plugin's chart widget with real Qt6 (PyQt6, offscreen), using the demo
output, without QGIS. Checks the Qt6 enum spellings and draws both views to PNG.

    QT_QPA_PLATFORM=offscreen python tests/test_chart_qt6.py
"""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [os.path.join(HERE, "qt_shim"), os.path.join(ROOT, "qgis_plugin")]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPointF, Qt  # noqa: E402
from PyQt6.QtGui import QMouseEvent  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from time_profile import chartdata  # noqa: E402
from time_profile.chart import ChartWidget  # noqa: E402
from time_profile.timeprofile import report  # noqa: E402

app = QApplication([])
rows = report.read_csv(os.path.join(ROOT, "demo", "output", "series.csv"))
post = report.postprocess(rows)
out = os.path.join(ROOT, "demo", "output")

w = ChartWidget()
w.resize(900, 420)
w.set_data(chartdata.time_series(rows, post, "NDVI", {}), "time", "NDVI")
assert w.save_png(os.path.join(out, "qt6_chart_time.png"), 900, 420)
w.show()
app.processEvents()
w.grab()  # paintEvent runs, filling the hover targets
assert w._hits, "nothing drawn"
c = w._hits[5][0]
ev = QMouseEvent(QMouseEvent.Type.MouseMove, QPointF(c.x() + 2, c.y()), QPointF(c.x() + 2, c.y()),
                 Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
w.mouseMoveEvent(ev)
assert w._hover == 5, w._hover

feat = "Paddies, west block"
w.set_data(chartdata.season_series(rows, post, "NDVI", feat, 1), "season", "NDVI", title=feat + ": NDVI by season")
assert w.save_png(os.path.join(out, "qt6_chart_seasons.png"), 900, 420)
w.set_data([], "time", "", message="empty")
assert w.save_png(os.path.join(tempfile.mkdtemp(), "empty.png"), 400, 200)
print("Qt6 chart ok:", len(w._hits) if w._hits else 0, "->", out)
