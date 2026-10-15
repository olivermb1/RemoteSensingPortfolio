"""QGIS Processing script: Composite Check, quality layers for a Landsat /
Sentinel-2 / HLS composite.

Install: Processing Toolbox > Scripts > Add Script to Toolbox... and pick this
file. The script needs the `compositecheck` package folder (the folder that
holds compositecheck/core.py). It looks, in order, in: an installed package,
the COMPOSITECHECK_PATH environment variable, and the folder above this script.

Uses GDAL (bundled with QGIS) for reading and writing, numpy for the maths and
matplotlib, if present, for the one-page chart. Written against the QGIS
3.34+/4.x Processing API (Qt5 and Qt6 both work via qgis.PyQt).
"""

import os
import sys

import numpy as np
from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterEnum,
    QgsProcessingParameterExtent,
    QgsProcessingParameterFile,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterDestination,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterString,
)
from qgis.PyQt.QtCore import QCoreApplication


def _import_package():
    try:
        import compositecheck  # noqa: F401
    except ImportError:
        candidates = [os.environ.get("COMPOSITECHECK_PATH", "")]
        try:
            candidates.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        except NameError:
            pass
        for c in candidates:
            if c and os.path.isdir(os.path.join(c, "compositecheck")):
                sys.path.insert(0, c)
                break
    from compositecheck import core, gdal_io, report, sensors
    return core, gdal_io, report, sensors


METHODS = ["medoid", "median", "target"]

# QGIS 3.36+ and 4.x use scoped enums on Qgis; older 3.x only has the class attributes
try:
    INTEGER, DOUBLE = Qgis.ProcessingNumberParameterType.Integer, Qgis.ProcessingNumberParameterType.Double
    FOLDER = Qgis.ProcessingFileParameterBehavior.Folder
except AttributeError:
    INTEGER, DOUBLE = QgsProcessingParameterNumber.Integer, QgsProcessingParameterNumber.Double
    FOLDER = QgsProcessingParameterFile.Folder


class CompositeCheckAlgorithm(QgsProcessingAlgorithm):
    MANIFEST, HLS_FOLDER, START, END, TARGET = "MANIFEST", "HLS_FOLDER", "START", "END", "TARGET"
    METHOD, COMPOSITE, COMPOSITE_BANDS, EXTENT, SENSORS = "METHOD", "COMPOSITE", "COMPOSITE_BANDS", "EXTENT", "SENSORS"
    FMASK_BITS, DILATE, DOMINANCE, PAIR_DAYS = "FMASK_BITS", "DILATE", "DOMINANCE", "PAIR_DAYS"
    QA_LAYERS, COMPOSITE_OUT, OUTPUT_FOLDER = "QA_LAYERS", "COMPOSITE_OUT", "OUTPUT_FOLDER"

    def tr(self, s):
        return QCoreApplication.translate("CompositeCheck", s)

    def createInstance(self):
        return CompositeCheckAlgorithm()

    def name(self):
        return "compositecheck"

    def displayName(self):
        return self.tr("Composite quality check (Composite Check)")

    def group(self):
        return self.tr("Map QA")

    def groupId(self):
        return "mapqa"

    def shortHelpString(self):
        return self.tr(
            "Per-pixel quality layers and a one-page report for a pixel-based composite built from "
            "Landsat, Sentinel-2 or NASA HLS scenes: clear-observation count, longest gap, source date "
            "and distance to the target date, which scene each pixel came from and whether one scene "
            "dominates, an outlier screen for scenes with missed cloud or haze, and a Landsat vs "
            "Sentinel-2 consistency check against the HLS v2.0 envelope (under 4.2% for red, NIR and SWIR; "
            "Ju et al. 2025).\n\n"
            "Input: either a manifest CSV (columns path, date, sensor, fmask, scene_id; one 6-band file "
            "per scene, blue..swir2) or a folder of HLS v2.0 granules. Either build a composite here "
            "(medoid, median or closest-to-target-date) or assess an existing one, such as a "
            "Digital Earth Africa GeoMAD.\n\n"
            "Operationalises and extends criteria 1, 4 and 5 of Francini et al. 2023 (ISPRS J. 202:1-12). "
            "Scene dominance and the outlier screen are new diagnostics without published validation."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFile(self.MANIFEST, self.tr("Scene manifest (CSV)"),
                                                     extension="csv", optional=True))
        self.addParameter(QgsProcessingParameterFile(self.HLS_FOLDER, self.tr("…or folder of HLS v2.0 granules"),
                                                     behavior=FOLDER, optional=True))
        self.addParameter(QgsProcessingParameterString(self.START, self.tr("Period start (YYYY-MM-DD)")))
        self.addParameter(QgsProcessingParameterString(self.END, self.tr("Period end (YYYY-MM-DD)")))
        self.addParameter(QgsProcessingParameterString(self.TARGET, self.tr("Target date (blank = middle of period)"),
                                                       optional=True))
        self.addParameter(QgsProcessingParameterEnum(self.METHOD, self.tr("Composite to build"),
                                                     options=[self.tr("Medoid (observation nearest the median)"),
                                                              self.tr("Per-band median"),
                                                              self.tr("Closest clear date to target")],
                                                     defaultValue=0))
        self.addParameter(QgsProcessingParameterRasterLayer(self.COMPOSITE,
                                                            self.tr("…or assess this existing composite"), optional=True))
        self.addParameter(QgsProcessingParameterString(self.COMPOSITE_BANDS,
                                                       self.tr("Existing composite: band numbers of blue,green,red,nir,swir1,swir2"),
                                                       defaultValue="1,2,3,4,5,6", optional=True))
        self.addParameter(QgsProcessingParameterExtent(self.EXTENT, self.tr("Area"), optional=True))
        self.addParameter(QgsProcessingParameterString(self.SENSORS, self.tr("Only these sensors (prefix, e.g. S or L)"),
                                                       optional=True))
        self.addParameter(QgsProcessingParameterString(self.FMASK_BITS, self.tr("Fmask bits to reject"),
                                                       defaultValue="0,1,2,3"))
        self.addParameter(QgsProcessingParameterNumber(self.DILATE, self.tr("Grow cloud masks by (pixels)"),
                                                       INTEGER, 0, minValue=0, maxValue=10))
        self.addParameter(QgsProcessingParameterNumber(self.DOMINANCE, self.tr("Flag when one scene supplies more than"),
                                                       DOUBLE, 0.5, minValue=0.05, maxValue=1))
        self.addParameter(QgsProcessingParameterNumber(self.PAIR_DAYS, self.tr("Landsat/Sentinel-2 pairs: max days apart"),
                                                       INTEGER, 1, minValue=0, maxValue=5))
        self.addParameter(QgsProcessingParameterRasterDestination(self.QA_LAYERS, self.tr("QA layers")))
        self.addParameter(QgsProcessingParameterRasterDestination(self.COMPOSITE_OUT, self.tr("Composite"),
                                                                  optional=True, createByDefault=True))
        self.addParameter(QgsProcessingParameterFolderDestination(self.OUTPUT_FOLDER, self.tr("Report folder")))

    def processAlgorithm(self, parameters, context, feedback):
        core, gio, report, sensors = _import_package()
        manifest = self.parameterAsFile(parameters, self.MANIFEST, context)
        folder = self.parameterAsFile(parameters, self.HLS_FOLDER, context)
        stack_path = manifest or folder
        if not stack_path:
            raise QgsProcessingException(self.tr("Give a scene manifest CSV or a folder of HLS granules."))
        start = self.parameterAsString(parameters, self.START, context).strip()
        end = self.parameterAsString(parameters, self.END, context).strip()
        target = self.parameterAsString(parameters, self.TARGET, context).strip() or \
            str(np.datetime64(start) + (np.datetime64(end) - np.datetime64(start)) // 2)
        method = METHODS[self.parameterAsEnum(parameters, self.METHOD, context)]
        sens = self.parameterAsString(parameters, self.SENSORS, context).strip()
        bits = tuple(int(b) for b in self.parameterAsString(parameters, self.FMASK_BITS, context).split(",") if b.strip())

        bbox = None
        if parameters.get(self.EXTENT):
            ext = self.parameterAsExtent(parameters, self.EXTENT, context, QgsCoordinateReferenceSystem("EPSG:4326"))
            if ext is not None and not ext.isEmpty():
                bbox = (ext.xMinimum(), ext.yMinimum(), ext.xMaximum(), ext.yMaximum())

        feedback.pushInfo(self.tr("Reading scenes…"))
        try:
            stack = gio.load(stack_path, bbox=bbox, fmask_bits=bits,
                             dilate=self.parameterAsInt(parameters, self.DILATE, context),
                             start=start, end=end, sensors=sens.split(",") if sens else None,
                             progress=lambda f: feedback.setProgress(int(60 * f)))
        except ValueError as e:
            raise QgsProcessingException(str(e))
        grid = stack.meta["grid"]
        feedback.pushInfo(f"{stack.T} scenes, {grid.width} x {grid.height} pixels")

        comp_in = None
        comp_layer = self.parameterAsRasterLayer(parameters, self.COMPOSITE, context)
        if comp_layer is not None:
            bands = [int(b) for b in (self.parameterAsString(parameters, self.COMPOSITE_BANDS, context) or "1,2,3,4,5,6").split(",")]
            comp_in = gio.read_composite(comp_layer.source(), grid, bands)

        feedback.pushInfo(self.tr("Running checks…"))
        layers, comp, rep, scenes = core.run_checks(
            stack, start, end, target, method=method, composite=comp_in,
            dominance_threshold=self.parameterAsDouble(parameters, self.DOMINANCE, context),
            pair_days=self.parameterAsInt(parameters, self.PAIR_DAYS, context))
        feedback.setProgress(85)

        out = self.parameterAsString(parameters, self.OUTPUT_FOLDER, context)
        os.makedirs(out, exist_ok=True)
        qa_path = self.parameterAsOutputLayer(parameters, self.QA_LAYERS, context)
        names = gio.write_layers(layers, grid, qa_path, sensors.LAYER_ORDER)
        results = {self.QA_LAYERS: qa_path, self.OUTPUT_FOLDER: out}
        comp_path = self.parameterAsOutputLayer(parameters, self.COMPOSITE_OUT, context)
        if comp_in is None and comp_path:
            gio.write_composite(comp, grid, comp_path)
            results[self.COMPOSITE_OUT] = comp_path
        rep["settings"] = {"stack": stack_path, "method": method, "bbox": bbox}
        rep = report.write_tables(out, rep, scenes, names)
        if report.plot(out, layers, rep, scenes, "Composite Check") is None:
            feedback.pushInfo(self.tr("matplotlib not found: wrote the tables and layers but no chart."))
        for f in rep["findings"]:
            feedback.pushInfo(f"{f['level'].upper()}: {f['check']}: {f['text']}")
        feedback.setProgress(100)
        return results
