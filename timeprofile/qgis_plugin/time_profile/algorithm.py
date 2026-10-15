"""Processing tool: time series for every feature of a layer -> series.csv,
seasons.csv, run.json and (if matplotlib is available) chart images."""

import json

from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsGeometry, QgsProcessing,
                       QgsProcessingAlgorithm, QgsProcessingException, QgsProcessingParameterBoolean,
                       QgsProcessingParameterEnum, QgsProcessingParameterFeatureSource, QgsProcessingParameterField,
                       QgsProcessingParameterFile, QgsProcessingParameterFolderDestination,
                       QgsProcessingParameterNumber, QgsProcessingParameterString, QgsProject)

from .timeprofile import catalog, gdal_io, geom, report
from .timeprofile.extract import extract

try:  # QGIS 3.36+ and QGIS 4 name these enums on Qgis; older QGIS 3 only has the class attributes
    from qgis.core import Qgis
    POINT, POLYGON = Qgis.ProcessingSourceType.VectorPoint, Qgis.ProcessingSourceType.VectorPolygon
    FOLDER = Qgis.ProcessingFileParameterBehavior.Folder
    DOUBLE = Qgis.ProcessingNumberParameterType.Double
except AttributeError:
    POINT, POLYGON = QgsProcessing.TypeVectorPoint, QgsProcessing.TypeVectorPolygon
    FOLDER = QgsProcessingParameterFile.Folder
    DOUBLE = QgsProcessingParameterNumber.Double

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


class TimeProfileAlgorithm(QgsProcessingAlgorithm):
    def name(self):
        return "timeseries"

    def displayName(self):
        return "Time series for features"

    def shortHelpString(self):
        return ("For every point or polygon in the layer, reads the given index (NDVI, EVI, NDMI, MNDWI, NBR, a "
                "band name, or NAME=formula; several separated by commas) from every scene in the folder, with "
                "clouds masked. Writes series.csv (one row per place, index and date), seasons.csv (peak, low "
                "and mean per season) and run.json to the output folder, plus chart images when matplotlib is "
                "installed. Reads HLS v2.0, Sentinel-2 L2A, Landsat Collection 2 and dated GeoTIFFs.")

    def createInstance(self):
        return TimeProfileAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            "FEATURES", "Points or polygons", [POINT, POLYGON]))
        self.addParameter(QgsProcessingParameterField("NAME_FIELD", "Name field", parentLayerParameterName="FEATURES",
                                                      optional=True))
        self.addParameter(QgsProcessingParameterFile("SCENES", "Scenes folder",
                                                     behavior=FOLDER))
        self.addParameter(QgsProcessingParameterString("INDEX", "Index or indices", defaultValue="NDVI"))
        self.addParameter(QgsProcessingParameterString("START", "First date (YYYY-MM-DD)", optional=True))
        self.addParameter(QgsProcessingParameterString("END", "Last date (YYYY-MM-DD)", optional=True))
        self.addParameter(QgsProcessingParameterBoolean("MASK", "Mask clouds with the quality layer", True))
        self.addParameter(QgsProcessingParameterNumber("BUFFER", "Points: pixels around the point", defaultValue=0,
                                                       minValue=0, maxValue=10))
        self.addParameter(QgsProcessingParameterNumber("MIN_CLEAR", "Polygons: % of pixels that must be clear",
                                                       DOUBLE, 50.0, minValue=0,
                                                       maxValue=100))
        self.addParameter(QgsProcessingParameterEnum("SEASON_START", "Season starts in", MONTHS, defaultValue=0))
        self.addParameter(QgsProcessingParameterFolderDestination("OUTPUT", "Output folder"))

    def processAlgorithm(self, parameters, context, feedback):
        src = self.parameterAsSource(parameters, "FEATURES", context)
        name_field = self.parameterAsString(parameters, "NAME_FIELD", context)
        folder = self.parameterAsFile(parameters, "SCENES", context)
        out = self.parameterAsString(parameters, "OUTPUT", context)
        ct = QgsCoordinateTransform(src.sourceCrs(), QgsCoordinateReferenceSystem("EPSG:4326"), QgsProject.instance())
        feats = []
        for ft in src.getFeatures():
            g = QgsGeometry(ft.geometry())
            if g.isEmpty():
                continue
            g.transform(ct)
            nm = str(ft[name_field]) if name_field and ft[name_field] not in (None, "") else f"feature {ft.id()}"
            try:
                feats.append(geom.feature(nm, json.loads(g.asJson(7))))
            except ValueError as e:
                feedback.reportError(str(e))
        if not feats:
            raise QgsProcessingException("no usable points or polygons")
        scenes = catalog.scan(folder, gdal_io.info)
        scenes = catalog.filter_scenes(scenes, self.parameterAsString(parameters, "START", context) or None,
                                       self.parameterAsString(parameters, "END", context) or None)
        feedback.pushInfo(catalog.describe(scenes))
        if not scenes:
            raise QgsProcessingException("no scenes found in that folder")
        idx = [s.strip() for s in self.parameterAsString(parameters, "INDEX", context).split(",") if s.strip()]
        rows, notes = extract(scenes, feats, idx, gdal_io, self.parameterAsBool(parameters, "MASK", context),
                              buffer=self.parameterAsInt(parameters, "BUFFER", context),
                              min_clear=self.parameterAsDouble(parameters, "MIN_CLEAR", context),
                              progress=lambda i, n: feedback.setProgress(100.0 * i / n),
                              cancelled=feedback.isCanceled)
        for n in notes:
            feedback.pushInfo(n)
        settings = {"scenes": folder, "index": idx, "features": len(feats), "backend": "gdal (QGIS)"}
        paths = report.outputs(out, rows, notes, settings, self.parameterAsEnum(parameters, "SEASON_START", context) + 1)
        feedback.pushInfo(f"{sum(r['status'] == 'clear' for r in rows)} clear observations of {len(rows)}")
        return {"OUTPUT": out, "SERIES": paths["series"], "SEASONS": paths["seasons"]}
