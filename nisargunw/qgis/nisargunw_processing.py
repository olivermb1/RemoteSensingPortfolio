"""QGIS Processing script: NISAR GUNW to GeoTIFF.

Converts a NISAR L2 GUNW interferogram (HDF5) into GeoTIFFs: unwrapped phase,
coherence, connected components, and line-of-sight displacement in metres
with the ionosphere, troposphere and solid Earth tide layers subtracted.

Install: Processing Toolbox > Scripts > Add Script to Toolbox... and pick this
file. The script needs the `nisargunw` package folder (the folder holding
nisargunw/convert.py). It looks, in order, in: an installed package, the
NISARGUNW_PATH environment variable, and the folder above this script.

Reads HDF5 through GDAL's multidimensional API (QGIS builds of GDAL include
HDF5) and uses h5py only if it happens to be installed. Written against the
QGIS 3.34+/4.x Processing API (Qt5 and Qt6 both work via qgis.PyQt). Tested
headless in QGIS 3.34; not tested in QGIS 4 or in the desktop app.
"""

import os
import sys

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterEnum,
    QgsProcessingParameterExtent,
    QgsProcessingParameterFile,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterNumber,
    QgsProcessingParameterPoint,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterString,
    QgsProject,
)
from qgis.PyQt.QtCore import QCoreApplication


def _import_package():
    try:
        import nisargunw  # noqa: F401
    except ImportError:
        candidates = [os.environ.get("NISARGUNW_PATH", "")]
        try:
            candidates.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        except NameError:
            pass
        for c in candidates:
            if c and os.path.isdir(os.path.join(c, "nisargunw")):
                sys.path.insert(0, c)
                break
    from nisargunw import convert, gdal_io, product
    return convert, gdal_io, product


REF_MODES = ["largest", "median", "none"]
COMPONENTS = ["largest", "all"]
PRESETS = [
    ("Displacement set (default)", "default"),
    ("Displacement set + vertical + LOS vectors", "default,vertical_displacement,los_east,los_north,los_up"),
    ("Everything", "all"),
    ("Only what I type below", ""),
]


class NisarGunwToGeoTiff(QgsProcessingAlgorithm):
    INPUT = "INPUT"
    OUTPUT = "OUTPUT"
    PRESET = "PRESET"
    LAYERS = "LAYERS"
    EXTENT = "EXTENT"
    DEM = "DEM"
    HEIGHT = "HEIGHT"
    IONO = "IONO"
    TROPO = "TROPO"
    SET = "SET"
    REF = "REF"
    REF_POINT = "REF_POINT"
    COMP = "COMP"
    MINCOH = "MINCOH"
    LOAD = "LOAD"

    def tr(self, s):
        return QCoreApplication.translate("NisarGunw", s)

    def createInstance(self):
        return NisarGunwToGeoTiff()

    def name(self):
        return "nisargunwtogeotiff"

    def displayName(self):
        return self.tr("NISAR GUNW to GeoTIFF")

    def group(self):
        return self.tr("NISAR")

    def groupId(self):
        return "nisar"

    def shortHelpString(self):
        return self.tr(
            "Converts a NISAR L2 GUNW (geocoded unwrapped interferogram) HDF5 file into GeoTIFFs.\n\n"
            "Line-of-sight displacement is in metres, positive towards the satellite, after "
            "subtracting the corrections you tick. Pixels in water, outside the swath, in "
            "connected component 0, and (by default) outside the largest connected component are "
            "blanked. A DEM makes the troposphere correction and incidence angle use real ground "
            "heights; without one they use the constant height.\n\n"
            "Synthetic-data tested only: check the README before trusting numbers from real files.")

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFile(self.INPUT, self.tr("GUNW file (.h5)"),
                                                     extension="h5"))
        self.addParameter(QgsProcessingParameterEnum(self.PRESET, self.tr("Layers"),
                                                     options=[p[0] for p in PRESETS], defaultValue=0))
        self.addParameter(QgsProcessingParameterString(
            self.LAYERS, self.tr("Extra layers (comma list, e.g. wrapped_phase,ionosphere)"),
            defaultValue="", optional=True))
        self.addParameter(QgsProcessingParameterExtent(self.EXTENT, self.tr("Clip to extent"),
                                                       optional=True))
        self.addParameter(QgsProcessingParameterRasterLayer(self.DEM, self.tr("DEM (recommended)"),
                                                            optional=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.HEIGHT, self.tr("Constant height if no DEM (m above ellipsoid)"),
            type=QgsProcessingParameterNumber.Double, defaultValue=0.0))
        self.addParameter(QgsProcessingParameterBoolean(self.IONO, self.tr("Subtract ionosphere"), True))
        self.addParameter(QgsProcessingParameterBoolean(self.TROPO, self.tr("Subtract troposphere"), True))
        self.addParameter(QgsProcessingParameterBoolean(self.SET, self.tr("Subtract solid Earth tide"), True))
        self.addParameter(QgsProcessingParameterEnum(
            self.REF, self.tr("Zero the displacement at"),
            options=[self.tr("median of the largest component"), self.tr("median of all kept pixels"),
                     self.tr("do not re-reference")], defaultValue=0))
        self.addParameter(QgsProcessingParameterPoint(
            self.REF_POINT, self.tr("...or at this point (a spot you know is stable)"), optional=True))
        self.addParameter(QgsProcessingParameterEnum(
            self.COMP, self.tr("Connected components"),
            options=[self.tr("keep only the largest"), self.tr("keep all (may be 2*pi apart)")],
            defaultValue=0))
        self.addParameter(QgsProcessingParameterNumber(
            self.MINCOH, self.tr("Minimum coherence (0 = off)"),
            type=QgsProcessingParameterNumber.Double, minValue=0, maxValue=1, defaultValue=0.0))
        self.addParameter(QgsProcessingParameterBoolean(self.LOAD, self.tr("Add results to the map"), True))
        self.addParameter(QgsProcessingParameterFolderDestination(self.OUTPUT, self.tr("Output folder")))

    def processAlgorithm(self, parameters, context, feedback):
        convert, gdal_io, product = _import_package()
        path = self.parameterAsFile(parameters, self.INPUT, context)
        out = self.parameterAsString(parameters, self.OUTPUT, context)
        layers = PRESETS[self.parameterAsEnum(parameters, self.PRESET, context)][1]
        extra = (self.parameterAsString(parameters, self.LAYERS, context) or "").strip()
        layers = ",".join(x for x in (layers, extra) if x) or "default"

        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        bbox = None
        if parameters.get(self.EXTENT):
            r = self.parameterAsExtent(parameters, self.EXTENT, context, wgs84)
            if not r.isEmpty():
                bbox = (r.xMinimum(), r.yMinimum(), r.xMaximum(), r.yMaximum())
        ref_ll = None
        if parameters.get(self.REF_POINT):
            p = self.parameterAsPoint(parameters, self.REF_POINT, context, wgs84)
            ref_ll = (p.x(), p.y())
        dem_layer = self.parameterAsRasterLayer(parameters, self.DEM, context)
        dem = dem_layer.source() if dem_layer else None
        corr = [c for c, flag in (("ionosphere", self.IONO), ("troposphere", self.TROPO),
                                  ("solid_earth_tide", self.SET))
                if self.parameterAsBoolean(parameters, flag, context)]

        def log(msg):
            if msg.startswith("WARNING"):
                feedback.reportError(msg, fatalError=False)
            else:
                feedback.pushInfo(msg)

        try:
            meta = convert.convert(
                path, out, gdal_io, layers=layers, bbox=bbox, corrections=corr, dem=dem,
                height=self.parameterAsDouble(parameters, self.HEIGHT, context),
                ref_mode=REF_MODES[self.parameterAsEnum(parameters, self.REF, context)],
                ref_lonlat=ref_ll,
                components=COMPONENTS[self.parameterAsEnum(parameters, self.COMP, context)],
                min_coherence=self.parameterAsDouble(parameters, self.MINCOH, context),
                quicklook=False, log=log)
        except Exception as e:
            raise QgsProcessingException(str(e))

        if self.parameterAsBoolean(parameters, self.LOAD, context):
            for key, o in meta["outputs"].items():
                f = os.path.join(out, o["file"])
                context.addLayerToLoadOnCompletion(
                    f, context.LayerDetails(o["file"].rsplit(".", 1)[0], context.project() or QgsProject.instance(), key))
        files = {k: os.path.join(out, v["file"]) for k, v in meta["outputs"].items()}
        files[self.OUTPUT] = out
        files["METADATA"] = os.path.join(out, meta["metadata_file"])
        return files
