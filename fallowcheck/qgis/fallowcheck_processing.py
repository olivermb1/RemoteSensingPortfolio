"""QGIS Processing script: Abandoned Fields.

Which normally farmed fields were not farmed this season? Compares a target
season's peak greenness (Sentinel-2 NDVI) with earlier, normal seasons, field
by field, and checks whether the patchwork of separate fields survived.

Install: Processing Toolbox > Scripts > Add Script to Toolbox... and pick this
file. The script needs the `fallowcheck` package folder (the folder holding
fallowcheck/core.py). It looks, in order, in: an installed package, the
FALLOWCHECK_PATH environment variable, and the folder above this script.

Uses GDAL/OGR (bundled with QGIS) and numpy only.
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
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterString,
    QgsProcessingParameterVectorLayer,
)
from qgis.PyQt.QtCore import QCoreApplication


def _import_package():
    try:
        import fallowcheck  # noqa: F401
    except ImportError:
        candidates = [os.environ.get("FALLOWCHECK_PATH", "")]
        try:
            candidates.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        except NameError:
            pass
        for c in candidates:
            if c and os.path.isdir(os.path.join(c, "fallowcheck")):
                sys.path.insert(0, c)
                break
    from fallowcheck import gdal_run
    return gdal_run


class AbandonedFields(QgsProcessingAlgorithm):
    def tr(self, s):
        return QCoreApplication.translate("AbandonedFields", s)

    def createInstance(self):
        return AbandonedFields()

    def name(self):
        return "abandonedfields"

    def displayName(self):
        return self.tr("Abandoned Fields")

    def group(self):
        return self.tr("Conflict and humanitarian")

    def groupId(self):
        return "conflicthumanitarian"

    def shortHelpString(self):
        return self.tr(
            "Scenes: Sentinel-2 files from 'python -m fallowcheck fetch-s2' (6 bands + SCL, date in the file name) "
            "for the same growing-season window in several years. Baseline years are normal seasons; the target "
            "year is the one to check. Cropland (optional) is a land cover raster such as ESA WorldCover (class "
            "40). Writes summary.csv (hectares not farmed per unit, normal-year rate, field-pattern ratio) and "
            "field_classes.tif. A wet season can green unmanaged fields: read not_farmed and pattern_lost together.")

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterMultipleLayers("SCENES", self.tr("Sentinel-2 scenes"),
                                                               QgsProcessing.TypeRaster))
        self.addParameter(QgsProcessingParameterString("BASELINE", self.tr("Baseline years (space-separated)"),
                                                       "2021 2022 2023"))
        self.addParameter(QgsProcessingParameterNumber("TARGET", self.tr("Target year"),
                                                       QgsProcessingParameterNumber.Integer, 2024))
        self.addParameter(QgsProcessingParameterString("SEASON", self.tr("Season window MM-DD MM-DD"), "07-15 11-30"))
        self.addParameter(QgsProcessingParameterRasterLayer("CROPLAND", self.tr("Cropland / land cover (optional)"),
                                                            optional=True))
        self.addParameter(QgsProcessingParameterString("CLASSES", self.tr("Cropland class values"), "40"))
        self.addParameter(QgsProcessingParameterVectorLayer("UNITS", self.tr("Reporting units (optional)"),
                                                            [QgsProcessing.TypeVectorPolygon], optional=True))
        self.addParameter(QgsProcessingParameterNumber("CELL", self.tr("Grid cell size (m) when no units"),
                                                       QgsProcessingParameterNumber.Double, 1000.0))
        for k, label, default in [("MIN_BASE", "Normal-year peak NDVI at least", 0.40),
                                  ("MAX_TARGET", "Target peak NDVI below", 0.30),
                                  ("MIN_DROP", "Drop from normal at least", 0.15)]:
            self.addParameter(QgsProcessingParameterNumber(k, self.tr(label), QgsProcessingParameterNumber.Double,
                                                           default))
        self.addParameter(QgsProcessingParameterFolderDestination("OUTPUT", self.tr("Output folder")))

    def processAlgorithm(self, parameters, context, feedback):
        gdal_run = _import_package()
        scenes = sorted(l.source().split("|")[0] for l in self.parameterAsLayerList(parameters, "SCENES", context))
        if not scenes:
            raise QgsProcessingException("Give the Sentinel-2 scenes.")
        base = [int(x) for x in self.parameterAsString(parameters, "BASELINE", context).split()]
        season = self.parameterAsString(parameters, "SEASON", context).split()
        crop = self.parameterAsRasterLayer(parameters, "CROPLAND", context)
        units = self.parameterAsVectorLayer(parameters, "UNITS", context)
        out = self.parameterAsString(parameters, "OUTPUT", context)
        params = {k.lower(): self.parameterAsDouble(parameters, k, context) for k in ("MIN_BASE", "MAX_TARGET", "MIN_DROP")}
        gdal_run.run(scenes, base, self.parameterAsInt(parameters, "TARGET", context), season, out,
                     crop.source() if crop else None,
                     tuple(int(x) for x in self.parameterAsString(parameters, "CLASSES", context).split(",")),
                     units.source().split("|")[0] if units else None,
                     self.parameterAsDouble(parameters, "CELL", context), params, log=feedback.pushInfo)
        return {"OUTPUT": out}
