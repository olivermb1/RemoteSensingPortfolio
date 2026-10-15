"""QGIS Processing script: Greenness link, is vegetation browning because of drought
or for some other reason? Pairs a monthly NDVI anomaly stack with the SPI from
'Drought maps and events' and a land cover map.

Install: Processing Toolbox > Scripts > Add Script to Toolbox... and pick this file.
It needs the `droughtcheck` package folder (see droughtcheck_processing.py).
Uses GDAL, numpy and scipy; matplotlib, if present, draws greenness.png.
"""

import os
import sys

from qgis.core import (
    Qgis,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFile,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterString,
)
from qgis.PyQt.QtCore import QCoreApplication


def _import_package():
    try:
        import droughtcheck  # noqa: F401
    except ImportError:
        candidates = [os.environ.get("DROUGHTCHECK_PATH", "")]
        try:
            candidates.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        except NameError:
            pass
        for c in candidates:
            if c and os.path.isdir(os.path.join(c, "droughtcheck")):
                sys.path.insert(0, c)
                break
    from droughtcheck import gdal_io, pipeline
    return gdal_io, pipeline


try:
    INTEGER = Qgis.ProcessingNumberParameterType.Integer
    FOLDER = Qgis.ProcessingFileParameterBehavior.Folder
except AttributeError:
    INTEGER = QgsProcessingParameterNumber.Integer
    FOLDER = QgsProcessingParameterFile.Folder

LEGENDS = ["worldcover", "io", "dynamicworld", "none"]


class GreennessLinkAlgorithm(QgsProcessingAlgorithm):
    NDVI, CLEAR, DROUGHT_DIR, LANDCOVER, LEGEND = "NDVI", "CLEAR", "DROUGHT_DIR", "LANDCOVER", "LEGEND"
    TARGET, SCALE, LAG, RECENT, MIN_PIXELS, OUTPUT_FOLDER = "TARGET", "SCALE", "LAG", "RECENT", "MIN_PIXELS", "OUTPUT_FOLDER"

    def tr(self, s):
        return QCoreApplication.translate("DroughtCheck", s)

    def createInstance(self):
        return GreennessLinkAlgorithm()

    def name(self):
        return "greennesslink"

    def displayName(self):
        return self.tr("Greenness link: drought or something else? (Drought Check)")

    def group(self):
        return self.tr("Drought Check")

    def groupId(self):
        return "droughtcheck"

    def shortHelpString(self):
        return self.tr(
            "For each land cover class, measures how closely the NDVI anomaly follows SPI (by SPI scale "
            "and lag), and for a target month labels each pixel: drought-linked browning, browning "
            "without drought, holding up in drought, or browning with mild dryness. It also maps "
            "'unexplained' greenness: how much browner or greener each pixel has been over the recent "
            "months than its own rainfall response predicts, and flags land change candidates.\n\n"
            "NDVI anomaly: one band per month, descriptions 'YYYY-MM' (python -m droughtcheck.fetch ndvi "
            "writes DE Africa's monthly NDVI standardised anomaly this way). Drought folder: the output "
            "folder of 'Drought maps and events'.\n\n"
            "Outputs: greenness_layers.tif (r, slope, n_baseline, unexplained_recent, "
            "nonclimatic_months_recent, diagnosis_target, landchange_flag), class_link.csv, "
            "lag_table.csv, class_series.csv, greenness.json and greenness.png.")

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer(self.NDVI, self.tr("Monthly NDVI anomaly stack")))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.CLEAR, self.tr("Clear-observation counts (optional)"), optional=True))
        self.addParameter(QgsProcessingParameterFile(self.DROUGHT_DIR, self.tr("Drought Check output folder"),
                                                     behavior=FOLDER))
        self.addParameter(QgsProcessingParameterRasterLayer(self.LANDCOVER, self.tr("Land cover map")))
        self.addParameter(QgsProcessingParameterEnum(self.LEGEND, self.tr("Land cover legend"), LEGENDS, defaultValue=0))
        self.addParameter(QgsProcessingParameterString(self.TARGET, self.tr("Target month YYYY-MM (blank: last)"),
                                                       "", optional=True))
        self.addParameter(QgsProcessingParameterString(self.SCALE, self.tr("SPI scale (auto or months)"), "auto"))
        self.addParameter(QgsProcessingParameterString(self.LAG, self.tr("Lag in months (auto or 0, 1, 2)"), "auto"))
        self.addParameter(QgsProcessingParameterNumber(self.RECENT, self.tr("Recent window (months)"), INTEGER, 12, minValue=3))
        self.addParameter(QgsProcessingParameterNumber(self.MIN_PIXELS, self.tr("Minimum pixels per class"), INTEGER, 50))
        self.addParameter(QgsProcessingParameterFolderDestination(self.OUTPUT_FOLDER, self.tr("Output folder")))

    def processAlgorithm(self, parameters, context, feedback):
        gdal_io, pipeline = _import_package()
        ndvi = self.parameterAsRasterLayer(parameters, self.NDVI, context)
        clear = self.parameterAsRasterLayer(parameters, self.CLEAR, context)
        lc = self.parameterAsRasterLayer(parameters, self.LANDCOVER, context)
        out = self.parameterAsString(parameters, self.OUTPUT_FOLDER, context)
        try:
            pipeline.greenness_files(
                gdal_io, ndvi.source(), self.parameterAsString(parameters, self.DROUGHT_DIR, context),
                lc.source(), out, clear=clear.source() if clear else None,
                legend=LEGENDS[self.parameterAsEnum(parameters, self.LEGEND, context)],
                target=self.parameterAsString(parameters, self.TARGET, context) or None,
                scale=self.parameterAsString(parameters, self.SCALE, context) or "auto",
                lag=self.parameterAsString(parameters, self.LAG, context) or "auto",
                recent=self.parameterAsInt(parameters, self.RECENT, context),
                min_class_pixels=self.parameterAsInt(parameters, self.MIN_PIXELS, context),
                log=feedback.pushInfo)
        except Exception as e:
            raise QgsProcessingException(str(e))
        return {self.OUTPUT_FOLDER: out}
