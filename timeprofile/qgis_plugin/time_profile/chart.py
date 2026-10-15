"""A small line/dot chart drawn with QPainter, so the plugin needs nothing
beyond what QGIS ships (no matplotlib). Works with Qt5 (QGIS 3) and Qt6 (QGIS 4):
every enum is written fully scoped.

Data model (built by the dock):
    series = [{"name": str, "color": "#rrggbb",
               "points": [(x, y, tooltip, hollow, marker)],   # marker: "o", "^" or "s"
               "lines": [[(x, y), ...], ...]}]
x is a number: a date ordinal (mode "time") or days since the season start (mode "season").
"""

import datetime as dt
import math

from qgis.PyQt.QtCore import QPointF, QRectF, Qt
from qgis.PyQt.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from qgis.PyQt.QtWidgets import QSizePolicy, QToolTip, QWidget

INK, INK2, GRID, SURFACE = QColor("#1f1f1e"), QColor("#6b6a64"), QColor("#e6e5e0"), QColor("#ffffff")
MONTHS = "JFMAMJJASOND"


def nice_step(span, target=6):
    raw = span / max(target, 1)
    mag = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            return m * mag
    return 10 * mag


def date_ticks(x0, x1):
    """(x, label) at month starts, thinned to at most ~8 labels."""
    d0, d1 = dt.date.fromordinal(int(x0)), dt.date.fromordinal(int(x1))
    months = (d1.year - d0.year) * 12 + d1.month - d0.month + 1
    every = next(k for k in (1, 2, 3, 6, 12, 24, 60) if months / k <= 8)
    out = []
    y, m = d0.year, d0.month
    while (y, m) <= (d1.year, d1.month):
        if (m - 1) % every == 0:
            d = dt.date(y, m, 1)
            if x0 <= d.toordinal() <= x1:
                lab = str(y) if m == 1 or every >= 12 else d.strftime("%b")
                out.append((d.toordinal(), lab))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def season_ticks(season_start):
    out = []
    for k in range(12):
        m = (season_start - 1 + k) % 12 + 1
        y = 2001 if m >= season_start else 2002
        out.append(((dt.date(y, m, 1) - dt.date(2001, season_start, 1)).days, MONTHS[m - 1]))
    return out


class ChartWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.series, self.mode, self.season_start = [], "time", 1
        self.ylabel, self.title, self.message = "", "", "Click on the map or use selected features to draw a chart."
        self._hits, self._hover = [], None
        self.setMouseTracking(True)
        self.setMinimumHeight(220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_data(self, series, mode="time", ylabel="", season_start=1, message="", title=""):
        self.series, self.mode, self.ylabel, self.title = series, mode, ylabel, title
        self.season_start, self.message = season_start, message
        self._hover = None
        self.update()

    # --- geometry ---------------------------------------------------------------
    def _extent(self):
        xs, ys = [], []
        for s in self.series:
            xs += [p[0] for p in s["points"]]
            ys += [p[1] for p in s["points"]]
            for ln in s["lines"]:
                xs += [p[0] for p in ln]
                ys += [p[1] for p in ln]
        if not xs:
            return None
        if self.mode == "season":
            x0, x1 = 0, 366
        else:
            x0, x1 = min(xs), max(xs)
            pad = max((x1 - x0) * 0.02, 5)
            x0, x1 = x0 - pad, x1 + pad
        y0, y1 = min(ys), max(ys)
        if y1 - y0 < 1e-9:
            y0, y1 = y0 - 0.05, y1 + 0.05
        pad = (y1 - y0) * 0.08
        return x0, x1, y0 - pad, y1 + pad

    def _legend_rows(self, fm_width, width):
        rows, row, x = [], [], 0
        for s in self.series:
            w = 26 + fm_width(s["name"]) + 14
            if row and x + w > width:
                rows.append(row)
                row, x = [], 0
            row.append((s, x))
            x += w
        if row:
            rows.append(row)
        return rows

    # --- painting -----------------------------------------------------------------
    def paintEvent(self, event):
        p = QPainter(self)
        try:
            self.render_to(p, self.width(), self.height())
        finally:
            p.end()

    def render_to(self, p, W, H):
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(QRectF(0, 0, W, H), SURFACE)
        f = QFont(self.font())
        f.setPointSizeF(8.5)
        p.setFont(f)
        fm = p.fontMetrics()
        ext = self._extent()
        if ext is None:
            p.setPen(INK2)
            p.drawText(QRectF(10, 10, W - 20, H - 20), int(Qt.AlignmentFlag.AlignCenter) | int(Qt.TextFlag.TextWordWrap),
                       self.message)
            self._hits = []
            return
        x0, x1, y0, y1 = ext
        legend = self._legend_rows(fm.horizontalAdvance, W - 60)
        head = fm.height() + 6 if self.title else 0
        top = 8 + head + len(legend) * (fm.height() + 4) + 6
        left, right, bottom = 48, W - 12, H - fm.height() - 12
        if right - left < 40 or bottom - top < 40:
            return

        def X(x):
            return left + (x - x0) / (x1 - x0) * (right - left)

        def Y(y):
            return bottom - (y - y0) / (y1 - y0) * (bottom - top)

        # grid and y axis
        step = nice_step(y1 - y0, 5)
        v = math.ceil(y0 / step) * step
        while v <= y1:
            p.setPen(QPen(GRID, 1))
            p.drawLine(QPointF(left, Y(v)), QPointF(right, Y(v)))
            p.setPen(INK2)
            lab = f"{v:.2f}".rstrip("0").rstrip(".") if abs(v) < 100 else f"{v:.0f}"
            p.drawText(QRectF(0, Y(v) - 8, left - 6, 16),
                       int(Qt.AlignmentFlag.AlignRight) | int(Qt.AlignmentFlag.AlignVCenter), lab)
            v += step
        ticks = season_ticks(self.season_start) if self.mode == "season" else date_ticks(x0, x1)
        for tx, lab in ticks:
            p.setPen(QPen(GRID, 1))
            p.drawLine(QPointF(X(tx), top), QPointF(X(tx), bottom))
            p.setPen(INK2)
            p.drawText(QRectF(X(tx) - 30, bottom + 4, 60, fm.height()), int(Qt.AlignmentFlag.AlignHCenter), lab)
        p.setPen(QPen(INK2, 1))
        p.drawLine(QPointF(left, bottom), QPointF(right, bottom))
        if self.ylabel:
            p.save()
            p.translate(12, (top + bottom) / 2)
            p.rotate(-90)
            p.setPen(INK)
            p.drawText(QRectF(-80, -8, 160, 16), int(Qt.AlignmentFlag.AlignCenter), self.ylabel)
            p.restore()

        # lines, then points with a white ring so overlaps stay readable
        hits = []
        p.setClipRect(QRectF(left, top - 4, right - left, bottom - top + 8))
        for s in self.series:
            col = QColor(s["color"])
            p.setPen(QPen(col, 2))
            for ln in s["lines"]:
                if len(ln) < 2:
                    continue
                path = QPainterPath(QPointF(X(ln[0][0]), Y(ln[0][1])))
                for x, y in ln[1:]:
                    path.lineTo(QPointF(X(x), Y(y)))
                p.drawPath(path)
        for s in self.series:
            col = QColor(s["color"])
            for x, y, tip, hollow, marker in s["points"]:
                c = QPointF(X(x), Y(y))
                p.setPen(QPen(col if hollow else SURFACE, 1.2))
                p.setBrush(SURFACE if hollow else col)
                self._marker(p, c, marker, 4.0)
                hits.append((c, tip, s["color"]))
        p.setClipping(False)
        if self._hover is not None and self._hover < len(hits):
            c = hits[self._hover][0]
            p.setPen(QPen(INK, 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(c, 7, 7)
        self._hits = hits

        # title and legend
        if self.title:
            p.setPen(INK)
            p.drawText(QPointF(12, 8 + fm.ascent()), self.title)
        y = 8 + head
        for row in legend:
            for s, x in row:
                col = QColor(s["color"])
                xx = 50 + x
                p.setPen(QPen(col, 2))
                p.drawLine(QPointF(xx, y + fm.height() / 2), QPointF(xx + 18, y + fm.height() / 2))
                p.setPen(QPen(SURFACE, 1))
                p.setBrush(col)
                p.drawEllipse(QPointF(xx + 9, y + fm.height() / 2), 3.5, 3.5)
                p.setPen(INK)
                p.drawText(QPointF(xx + 24, y + fm.ascent()), s["name"])
            y += fm.height() + 4

    @staticmethod
    def _marker(p, c, marker, r):
        if marker == "^":
            p.drawPolygon(QPolygonF([QPointF(c.x(), c.y() - r * 1.2), QPointF(c.x() - r * 1.1, c.y() + r * 0.8),
                                     QPointF(c.x() + r * 1.1, c.y() + r * 0.8)]))
        elif marker == "s":
            p.drawRect(QRectF(c.x() - r * 0.9, c.y() - r * 0.9, r * 1.8, r * 1.8))
        else:
            p.drawEllipse(c, r, r)

    # --- hover ------------------------------------------------------------------
    def mouseMoveEvent(self, e):
        pos = e.position() if hasattr(e, "position") else e.localPos()
        best, bd = None, 12.0 ** 2
        for i, (c, _, _) in enumerate(self._hits):
            d = (c.x() - pos.x()) ** 2 + (c.y() - pos.y()) ** 2
            if d < bd:
                best, bd = i, d
        if best != self._hover:
            self._hover = best
            self.update()
        if best is None:
            QToolTip.hideText()
        else:
            gp = e.globalPosition().toPoint() if hasattr(e, "globalPosition") else e.globalPos()
            QToolTip.showText(gp, self._hits[best][1], self)

    def leaveEvent(self, e):
        self._hover = None
        self.update()

    def save_png(self, path, width=1200, height=600):
        from qgis.PyQt.QtGui import QImage
        img = QImage(width, height, QImage.Format.Format_ARGB32)
        img.fill(SURFACE)
        p = QPainter(img)
        try:
            self.render_to(p, width, height)
        finally:
            p.end()
        return img.save(path)
