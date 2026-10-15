import os

from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon

from .algorithm import TimeProfileAlgorithm


class TimeProfileProvider(QgsProcessingProvider):
    def loadAlgorithms(self):
        self.addAlgorithm(TimeProfileAlgorithm())

    def id(self):
        return "timeprofile"

    def name(self):
        return "Time Profile"

    def icon(self):
        return QIcon(os.path.join(os.path.dirname(__file__), "icon.svg"))
