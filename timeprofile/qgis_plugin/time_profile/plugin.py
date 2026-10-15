import os

from qgis.core import QgsApplication
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

from .provider import TimeProfileProvider


class TimeProfilePlugin:
    def __init__(self, iface):
        self.iface = iface
        self.provider = self.dock = self.action = None

    def initProcessing(self):
        self.provider = TimeProfileProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def initGui(self):
        self.initProcessing()
        icon = os.path.join(os.path.dirname(__file__), "icon.svg")
        self.action = QAction(QIcon(icon), "Time Profile", self.iface.mainWindow())
        self.action.setCheckable(True)
        self.action.toggled.connect(self._toggle)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToRasterMenu("Time Profile", self.action)

    def _toggle(self, on):
        if on and self.dock is None:
            from .dock import TimeProfileDock
            self.dock = TimeProfileDock(self.iface)
            self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)
            self.dock.visibilityChanged.connect(lambda v: self.action.setChecked(v))
        if self.dock is not None:
            self.dock.setVisible(on)

    def unload(self):
        if self.dock is not None:
            self.dock.cleanup()
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
        if self.action is not None:
            self.iface.removePluginRasterMenu("Time Profile", self.action)
            self.iface.removeToolBarIcon(self.action)
        if self.provider:
            QgsApplication.processingRegistry().removeProvider(self.provider)
