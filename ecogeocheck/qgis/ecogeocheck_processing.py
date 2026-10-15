"""QGIS Processing script: ECOSTRESS Geo Check, find ECOSTRESS scenes whose
geolocation is flagged or measured as off, and keep them out of your work.

Install: Processing Toolbox > Scripts > Add Script to Toolbox... and pick this
file. The script needs the `ecogeocheck` package folder. It looks, in order,
in: an installed package, the ECOGEOCHECK_PATH environment variable, and the
folder above this script.

Uses GDAL and numpy (both ship with QGIS). h5py is optional: without it, L1B
GEO .h5 files are read through GDAL's HDF5 driver. Written for the QGIS
3.34+ and 4.x Processing API (Qt5 and Qt6 via qgis.PyQt).
"""

import os
import sys

from qgis.core import (
    Qgis,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFile,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterLayer,
    QgsProcessingOutputNumber,
    QgsProcessingOutputVectorLayer,
    QgsRasterLayer,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QCoreApplication


def _import_package():
    try:
        import ecogeocheck  # noqa: F401
    except ImportError:
        candidates = [os.environ.get("ECOGEOCHECK_PATH", "")]
        try:
            candidates.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        except NameError:
            pass
        for c in candidates:
            if c and os.path.isdir(os.path.join(c, "ecogeocheck")):
                sys.path.insert(0, c)
                break
    from ecogeocheck import core, gdal_io
    return core, gdal_io


LEVELS = ["best", "good", "suspect", "poor"]

try:
    DOUBLE = Qgis.ProcessingNumberParameterType.Double
    FOLDER = Qgis.ProcessingFileParameterBehavior.Folder
    FILE = Qgis.ProcessingFileParameterBehavior.File
except AttributeError:
    DOUBLE = QgsProcessingParameterNumber.Double
    FOLDER = QgsProcessingParameterFile.Folder
    FILE = QgsProcessingParameterFile.File


class EcoGeoCheckAlgorithm(QgsProcessingAlgorithm):
    INPUT, SUMMARY, REFERENCE, ACCEPT = "INPUT", "SUMMARY", "REFERENCE", "ACCEPT"
    TOLERANCE, MAX_SHIFT, MEASURE, FIX, RESCUE = "TOLERANCE", "MAX_SHIFT", "MEASURE", "FIX", "RESCUE"
    LOAD_KEPT, OUTPUT_FOLDER = "LOAD_KEPT", "OUTPUT_FOLDER"

    def tr(self, s):
        return QCoreApplication.translate("EcoGeoCheck", s)

    def createInstance(self):
        return EcoGeoCheckAlgorithm()

    def name(self):
        return "ecogeocheck"

    def displayName(self):
        return self.tr("ECOSTRESS geolocation check")

    def group(self):
        return self.tr("NASA tools")

    def groupId(self):
        return "nasatools"

    def shortHelpString(self):
        return self.tr(
            "Reads NASA's GeolocationAccuracyQA flag for each ECOSTRESS scene (from L1B GEO files, the "
            "granule's metadata or a summary table) and measures each tiled LST scene's offset against its "
            "own water layer, a reference raster, or the 'best' scenes of the same tile. Scenes flagged "
            "suspect or poor, or measured off by more than the tolerance, are dropped. Outputs a scene "
            "table (scenes.csv, scenes.geojson), keep.txt and drop.txt, and a summary.\n\n"
            "Input folder: ECOSTRESS files with their NASA names, e.g. "
            "ECOv002_L2T_LSTE_<orbit>_<scene>_<tile>_<time>_<build>_<iter>_LST.tif, plus the matching "
            "ECOv002_L1B_GEO_...h5 files if you have them.")

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFile(self.INPUT, self.tr("Folder of ECOSTRESS files"), behavior=FOLDER))
        self.addParameter(QgsProcessingParameterFile(self.SUMMARY, self.tr("Flag table (optional: NASA summary "
                                                     "file or geo_flags.csv)"), behavior=FILE, optional=True))
        self.addParameter(QgsProcessingParameterRasterLayer(self.REFERENCE, self.tr("Reference raster (optional: "
                                                            "water mask or HLS NDVI)"), optional=True))
        self.addParameter(QgsProcessingParameterEnum(self.ACCEPT, self.tr("NASA flags to keep"), options=LEVELS,
                                                     allowMultiple=True, defaultValue=[0, 1]))
        self.addParameter(QgsProcessingParameterNumber(self.TOLERANCE, self.tr("Largest offset to accept (m)"),
                                                       type=DOUBLE, defaultValue=140, minValue=0))
        self.addParameter(QgsProcessingParameterNumber(self.MAX_SHIFT, self.tr("Search radius (m)"), type=DOUBLE,
                                                       defaultValue=7700, minValue=200))
        self.addParameter(QgsProcessingParameterBoolean(self.MEASURE, self.tr("Measure offsets"), defaultValue=True))
        self.addParameter(QgsProcessingParameterBoolean(self.FIX, self.tr("Write shifted copies of offset scenes"),
                                                        defaultValue=False))
        self.addParameter(QgsProcessingParameterBoolean(self.RESCUE, self.tr("Keep flagged scenes that measure "
                                                        "within tolerance"), defaultValue=False))
        self.addParameter(QgsProcessingParameterBoolean(self.LOAD_KEPT, self.tr("Add kept LST layers to the map"),
                                                        defaultValue=True))
        self.addParameter(QgsProcessingParameterFolderDestination(self.OUTPUT_FOLDER, self.tr("Output folder")))
        self.addOutput(QgsProcessingOutputVectorLayer("SCENES", self.tr("Scenes")))
        for k in ("KEEP", "DROP"):
            self.addOutput(QgsProcessingOutputNumber(k, k.lower()))

    def processAlgorithm(self, parameters, context, feedback):
        core, gdal_io = _import_package()
        folder = self.parameterAsFile(parameters, self.INPUT, context)
        summary = self.parameterAsFile(parameters, self.SUMMARY, context) or None
        ref_layer = self.parameterAsRasterLayer(parameters, self.REFERENCE, context)
        accept = tuple(LEVELS[i] for i in self.parameterAsEnums(parameters, self.ACCEPT, context))
        out = self.parameterAsString(parameters, self.OUTPUT_FOLDER, context)
        if not folder or not os.path.isdir(folder):
            raise QgsProcessingException(self.tr("Choose a folder of ECOSTRESS files."))
        if not summary and os.path.exists(os.path.join(folder, "geo_flags.csv")):
            summary = os.path.join(folder, "geo_flags.csv")
        results, info = core.run(
            [folder], out=out, summary=summary, reference=ref_layer.source() if ref_layer else None, io=gdal_io,
            log=feedback.pushInfo, accept=accept,
            tolerance_m=self.parameterAsDouble(parameters, self.TOLERANCE, context),
            max_shift_m=self.parameterAsDouble(parameters, self.MAX_SHIFT, context),
            measure=self.parameterAsBool(parameters, self.MEASURE, context),
            fix=self.parameterAsBool(parameters, self.FIX, context),
            rescue=self.parameterAsBool(parameters, self.RESCUE, context))
        c = info["counts"]
        feedback.pushInfo(f"keep {c['keep']}, caution {c['caution']}, fixed {c['fixed']}, check {c['check']}, "
                          f"drop {c['drop']}")
        scenes = os.path.join(out, "scenes.geojson")
        lyr = QgsVectorLayer(scenes, "ECOSTRESS scenes (geolocation check)", "ogr")
        if lyr.isValid():
            context.temporaryLayerStore().addMapLayer(lyr)
            context.addLayerToLoadOnCompletion(lyr.id(), context.LayerDetails(lyr.name(), context.project(), "SCENES"))
        if self.parameterAsBool(parameters, self.LOAD_KEPT, context) and context.project() is not None:
            for r in results.values():
                if r["decision"] not in ("keep", "caution", "fixed"):
                    continue
                files = r.get("shifted_files") or r["files"]
                lst = next((f for f in files if f.endswith("_LST.tif")), None)
                if lst:
                    rl = QgsRasterLayer(lst, f"LST {r['time'][:16]} ({r['decision']})")
                    if rl.isValid():
                        context.temporaryLayerStore().addMapLayer(rl)
                        context.addLayerToLoadOnCompletion(rl.id(), context.LayerDetails(rl.name(), context.project(), ""))
        return {"SCENES": scenes, "KEEP": c["keep"] + c["caution"] + c["fixed"], "DROP": c["drop"],
                self.OUTPUT_FOLDER: out}
