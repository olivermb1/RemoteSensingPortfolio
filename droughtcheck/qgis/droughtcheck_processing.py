"""QGIS Processing script: Drought Check, SPI / SPEI drought maps and drought events
from monthly rainfall (e.g. CHIRPS).

Install: Processing Toolbox > Scripts > Add Script to Toolbox... and pick this file.
It needs the `droughtcheck` package folder. It looks, in order, in: an installed
package, the DROUGHTCHECK_PATH environment variable, and the folder above this script.

Uses GDAL (bundled with QGIS), numpy and scipy. If the `climate-indices` package is
installed in QGIS's Python it is used for SPI/SPEI; otherwise a built-in version that
gives identical results on the test data. matplotlib, if present, draws report.png.
Written against the QGIS 3.34+/4.x Processing API.
"""

import os
import sys

from qgis.core import (
    Qgis,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterEnum,
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
    INTEGER, DOUBLE = Qgis.ProcessingNumberParameterType.Integer, Qgis.ProcessingNumberParameterType.Double
except AttributeError:
    INTEGER, DOUBLE = QgsProcessingParameterNumber.Integer, QgsProcessingParameterNumber.Double

BACKENDS = ["auto", "builtin", "climate-indices"]


def _ints(s):
    return [int(x) for x in str(s).replace(";", ",").split(",") if x.strip()]


class DroughtCheckAlgorithm(QgsProcessingAlgorithm):
    PRECIP, TEMPS, PET, SCALES, SPEI_SCALES = "PRECIP", "TEMPS", "PET", "SCALES", "SPEI_SCALES"
    CAL_START, CAL_END, CLASS_SCALE, THRESHOLD = "CAL_START", "CAL_END", "CLASS_SCALE", "THRESHOLD"
    MIN_DURATION, EVENTS_SINCE, BACKEND, OUTPUT_FOLDER = "MIN_DURATION", "EVENTS_SINCE", "BACKEND", "OUTPUT_FOLDER"

    def tr(self, s):
        return QCoreApplication.translate("DroughtCheck", s)

    def createInstance(self):
        return DroughtCheckAlgorithm()

    def name(self):
        return "droughtcheck"

    def displayName(self):
        return self.tr("Drought maps and events (Drought Check)")

    def group(self):
        return self.tr("Drought Check")

    def groupId(self):
        return "droughtcheck"

    def shortHelpString(self):
        return self.tr(
            "Computes the Standardized Precipitation Index (SPI) and, with temperature or PET, the "
            "Standardized Precipitation-Evapotranspiration Index (SPEI) for every pixel of a monthly "
            "rainfall stack, then maps the latest drought class and summarises drought events "
            "(run theory: spells below the threshold).\n\n"
            "Rainfall: one band per month, band descriptions 'YYYY-MM' (python -m droughtcheck.fetch "
            "chirps writes this for CHIRPS). Temperature: bands 'tmax YYYY-MM' and 'tmin YYYY-MM' "
            "(droughtcheck.fetch temps, NASA POWER); PET is then Hargreaves.\n\n"
            "Outputs in the folder: spi_N.tif and spei_N.tif (one band per month), "
            "drought_class_latest.tif, drought_events.tif (event count, longest spell, worst peak, "
            "worst magnitude, months in drought, current spell), area_timeseries.csv, events.csv, "
            "report.json and report.png. Use the folder as the input of 'Greenness link'.")

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer(self.PRECIP, self.tr("Monthly rainfall stack (mm)")))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.TEMPS, self.tr("Monthly Tmax/Tmin stack (for SPEI)"), optional=True))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.PET, self.tr("Monthly PET stack in mm (for SPEI, instead of temperature)"), optional=True))
        self.addParameter(QgsProcessingParameterString(self.SCALES, self.tr("SPI scales (months)"), "1,3,6,12"))
        self.addParameter(QgsProcessingParameterString(self.SPEI_SCALES, self.tr("SPEI scales (months)"), "3,6,12"))
        self.addParameter(QgsProcessingParameterNumber(self.CAL_START, self.tr("Calibration start year"), INTEGER, 1991))
        self.addParameter(QgsProcessingParameterNumber(self.CAL_END, self.tr("Calibration end year"), INTEGER, 2020))
        self.addParameter(QgsProcessingParameterNumber(
            self.CLASS_SCALE, self.tr("SPI scale for the class map and events"), INTEGER, 3, minValue=1))
        self.addParameter(QgsProcessingParameterNumber(self.THRESHOLD, self.tr("Drought threshold"), DOUBLE, -1.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.MIN_DURATION, self.tr("Minimum event length (months)"), INTEGER, 2, minValue=1))
        self.addParameter(QgsProcessingParameterString(
            self.EVENTS_SINCE, self.tr("Count per-pixel events from (YYYY-MM)"), "", optional=True))
        self.addParameter(QgsProcessingParameterEnum(self.BACKEND, self.tr("SPI/SPEI engine"), BACKENDS, defaultValue=0))
        self.addParameter(QgsProcessingParameterFolderDestination(self.OUTPUT_FOLDER, self.tr("Output folder")))

    def processAlgorithm(self, parameters, context, feedback):
        gdal_io, pipeline = _import_package()
        precip = self.parameterAsRasterLayer(parameters, self.PRECIP, context)
        temps = self.parameterAsRasterLayer(parameters, self.TEMPS, context)
        pet = self.parameterAsRasterLayer(parameters, self.PET, context)
        out = self.parameterAsString(parameters, self.OUTPUT_FOLDER, context)
        try:
            pipeline.drought_files(
                gdal_io, precip.source(), out,
                temps=temps.source() if temps else None, pet=pet.source() if pet else None,
                scales=_ints(self.parameterAsString(parameters, self.SCALES, context)),
                spei_scales=_ints(self.parameterAsString(parameters, self.SPEI_SCALES, context)),
                calibration=(self.parameterAsInt(parameters, self.CAL_START, context),
                             self.parameterAsInt(parameters, self.CAL_END, context)),
                class_scale=self.parameterAsInt(parameters, self.CLASS_SCALE, context),
                threshold=self.parameterAsDouble(parameters, self.THRESHOLD, context),
                min_duration=self.parameterAsInt(parameters, self.MIN_DURATION, context),
                events_since=self.parameterAsString(parameters, self.EVENTS_SINCE, context) or None,
                backend=BACKENDS[self.parameterAsEnum(parameters, self.BACKEND, context)],
                log=feedback.pushInfo)
        except Exception as e:
            raise QgsProcessingException(str(e))
        return {self.OUTPUT_FOLDER: out}
