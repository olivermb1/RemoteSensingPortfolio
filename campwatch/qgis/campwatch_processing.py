"""QGIS Processing script: Camp Growth Watch.

When did new shelter areas (refugee or displacement camps, informal
extensions) appear, and how fast did they grow? Monthly Sentinel-2 composites
are compared with the same calendar month of a baseline year.

Install: Processing Toolbox > Scripts > Add Script to Toolbox... and pick this
file. The script needs the `campwatch` package folder (the folder holding
campwatch/core.py). It looks, in order, in: an installed package, the
CAMPWATCH_PATH environment variable, and the folder above this script.

Uses GDAL/OGR (bundled with QGIS) and numpy only; scipy is used if present.
"""

import os
import sys

from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterMultipleLayers,
    QgsProcessingParameterNumber,
    QgsProcessingParameterString,
    QgsProcessingParameterVectorLayer,
)
from qgis.PyQt.QtCore import QCoreApplication


def _import_package():
    try:
        import campwatch  # noqa: F401
    except ImportError:
        candidates = [os.environ.get("CAMPWATCH_PATH", "")]
        try:
            candidates.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        except NameError:
            pass
        for c in candidates:
            if c and os.path.isdir(os.path.join(c, "campwatch")):
                sys.path.insert(0, c)
                break
    from campwatch import core, gdal_run
    return core, gdal_run


class CampGrowthWatch(QgsProcessingAlgorithm):
    SCENES, UNITS, OUT = "SCENES", "UNITS", "OUTPUT"
    STRS = [("BASELINE", "Baseline months, FROM TO (YYYY-MM YYYY-MM)", "2021-11 2022-05"),
            ("PERIOD", "Months to track, FROM TO (YYYY-MM YYYY-MM)", "2023-01 2025-03"),
            ("DRY", "Months used (comma-separated)", "11,12,1,2,3,4,5")]
    NUMS = [("T_RATIO", "Blue/red rise", 0.07), ("T_BLUE", "Blue rise", 0.015), ("MAX_NDVI", "Maximum NDVI", 0.30),
            ("MIN_AREA_HA", "Minimum detected area (ha)", 5.0)]

    def tr(self, s):
        return QCoreApplication.translate("CampGrowthWatch", s)

    def createInstance(self):
        return CampGrowthWatch()

    def name(self):
        return "campgrowthwatch"

    def displayName(self):
        return self.tr("Camp Growth Watch")

    def group(self):
        return self.tr("Conflict and humanitarian")

    def groupId(self):
        return "conflicthumanitarian"

    def shortHelpString(self):
        return self.tr(
            "Scenes: Sentinel-2 files from 'python -m campwatch fetch-s2' (6 bands + SCL, date in the file name), "
            "covering a baseline year and the months to track. Units (optional): camp outlines or admin units; if "
            "empty, new shelter areas are detected. Writes summary.csv, timeseries.csv (footprint in ha per area per "
            "month), first_seen.tif (YYYYMM) and areas.geojson. Works where shelters are lighter and greyer than the "
            "surrounding soil; check results against imagery and UNHCR site data.")

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterMultipleLayers(self.SCENES, self.tr("Sentinel-2 scenes"),
                                                               QgsProcessing.TypeRaster))
        self.addParameter(QgsProcessingParameterVectorLayer(self.UNITS, self.tr("Areas to report (optional)"),
                                                            [QgsProcessing.TypeVectorPolygon], optional=True))
        for k, label, default in self.STRS:
            self.addParameter(QgsProcessingParameterString(k, self.tr(label), default))
        for k, label, default in self.NUMS:
            self.addParameter(QgsProcessingParameterNumber(k, self.tr(label), QgsProcessingParameterNumber.Double,
                                                           default))
        self.addParameter(QgsProcessingParameterFolderDestination(self.OUT, self.tr("Output folder")))

    def processAlgorithm(self, parameters, context, feedback):
        core, gdal_run = _import_package()
        scenes = sorted(l.source().split("|")[0] for l in self.parameterAsLayerList(parameters, self.SCENES, context))
        if not scenes:
            raise QgsProcessingException("Give the Sentinel-2 scenes.")
        s = {k: self.parameterAsString(parameters, k, context).split() for k, _, _ in self.STRS}
        if len(s["BASELINE"]) != 2 or len(s["PERIOD"]) != 2:
            raise QgsProcessingException("Baseline and period need two months each, e.g. 2021-11 2022-05.")
        dry = tuple(int(x) for x in "".join(s["DRY"]).split(","))
        params = {k.lower(): self.parameterAsDouble(parameters, k, context) for k, _, _ in self.NUMS}
        ul = self.parameterAsVectorLayer(parameters, self.UNITS, context)
        out = self.parameterAsString(parameters, self.OUT, context)
        gdal_run.run(scenes, tuple(s["BASELINE"]), tuple(s["PERIOD"]), out,
                     ul.source().split("|")[0] if ul else None, dry, params, log=feedback.pushInfo)
        return {self.OUT: out}
