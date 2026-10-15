"""QGIS Processing script: DIST Watch, new vegetation loss since your last run
from NASA OPERA DIST-ALERT-HLS, summarised per area.

Install: Processing Toolbox > Scripts > Add Script to Toolbox... and pick this
file. The script needs the `distwatch` package folder (the folder holding
distwatch/core.py). It looks, in order, in: an installed package, the
DISTWATCH_PATH environment variable, and the folder above this script.

Uses GDAL/OGR (bundled with QGIS) and numpy. Written against the QGIS
3.34+/4.x Processing API (Qt5 and Qt6 both work via qgis.PyQt). Untested in
QGIS: it was written where QGIS was not available.
"""

import json
import os
import sys

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProcessingAlgorithm,
    QgsProcessingContext,
    QgsProcessingException,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterFile,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterString,
    QgsProject,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QCoreApplication


def _import_package():
    try:
        import distwatch  # noqa: F401
    except ImportError:
        candidates = [os.environ.get("DISTWATCH_PATH", "")]
        try:
            candidates.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        except NameError:
            pass
        for c in candidates:
            if c and os.path.isdir(os.path.join(c, "distwatch")):
                sys.path.insert(0, c)
                break
    from distwatch import gdal_io, watch
    return gdal_io, watch


LEVELS = ["confirmed", "provisional", "first"]

try:
    INTEGER = Qgis.ProcessingNumberParameterType.Integer
    FOLDER = Qgis.ProcessingFileParameterBehavior.Folder
except AttributeError:
    INTEGER = QgsProcessingParameterNumber.Integer
    FOLDER = QgsProcessingParameterFile.Folder


class DistWatchAlgorithm(QgsProcessingAlgorithm):
    AREAS, NAME_FIELD, DATA, STATE, FETCH = "AREAS", "NAME_FIELD", "DATA", "STATE", "FETCH"
    LEVEL, MIN_LOSS, SINCE, MIN_PATCH = "LEVEL", "MIN_LOSS", "SINCE", "MIN_PATCH"
    FOREST, AS_OF, DRY_RUN, OUTPUT_FOLDER = "FOREST", "AS_OF", "DRY_RUN", "OUTPUT_FOLDER"

    def tr(self, s):
        return QCoreApplication.translate("DistWatch", s)

    def createInstance(self):
        return DistWatchAlgorithm()

    def name(self):
        return "distwatch"

    def displayName(self):
        return self.tr("DIST Watch: new vegetation loss since last run")

    def group(self):
        return self.tr("NASA OPERA")

    def groupId(self):
        return "nasaopera"

    def shortHelpString(self):
        return self.tr(
            "Reports only the vegetation loss that is new since your last run, from NASA OPERA "
            "DIST-ALERT-HLS (30 m, every 2-4 days), with hectares per area.\n\n"
            "Keep the same State folder between runs: it remembers which pixels were already reported. "
            "The newest DIST-ALERT granule per MGRS tile is read from the Granules folder; tick Download "
            "to fetch them first (needs a NASA Earthdata login in ~/.netrc or EARTHDATA_TOKEN).\n\n"
            "Defaults suit EUDR deforestation checks: confirmed alerts, at least 50% vegetation cover "
            "lost, first detected after 2020-12-31. Add a forest mask (e.g. JRC GFC2020) to keep only "
            "loss of forest.")

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(self.AREAS, self.tr("Areas to watch (polygons)")))
        self.addParameter(QgsProcessingParameterField(self.NAME_FIELD, self.tr("Area name field"),
                                                      parentLayerParameterName=self.AREAS, optional=True))
        self.addParameter(QgsProcessingParameterFile(self.STATE, self.tr("State folder (keep between runs)"),
                                                     behavior=FOLDER))
        self.addParameter(QgsProcessingParameterFile(self.DATA, self.tr("Granules folder (default: <state>/granules)"),
                                                     behavior=FOLDER, optional=True))
        self.addParameter(QgsProcessingParameterBoolean(self.FETCH, self.tr("Download newest granules first"),
                                                        defaultValue=False))
        self.addParameter(QgsProcessingParameterEnum(self.LEVEL, self.tr("Alert level"), options=LEVELS,
                                                     defaultValue=0))
        self.addParameter(QgsProcessingParameterNumber(self.MIN_LOSS, self.tr("Minimum vegetation loss (%)"),
                                                       type=INTEGER, defaultValue=50, minValue=0, maxValue=100))
        self.addParameter(QgsProcessingParameterString(self.SINCE, self.tr("Only loss first detected after"),
                                                       defaultValue="2020-12-31"))
        self.addParameter(QgsProcessingParameterNumber(self.MIN_PATCH, self.tr("Smallest patch (30 m pixels)"),
                                                       type=INTEGER, defaultValue=3, minValue=1))
        self.addParameter(QgsProcessingParameterRasterLayer(self.FOREST, self.tr("Forest mask (non-zero = forest)"),
                                                            optional=True))
        self.addParameter(QgsProcessingParameterString(self.AS_OF, self.tr("Ignore granules after (YYYY-MM-DD)"),
                                                       optional=True))
        self.addParameter(QgsProcessingParameterBoolean(self.DRY_RUN, self.tr("Dry run (don't update state)"),
                                                        defaultValue=False))
        self.addParameter(QgsProcessingParameterFolderDestination(self.OUTPUT_FOLDER, self.tr("Output folder")))

    def processAlgorithm(self, parameters, context, feedback):
        gdal_io, watch = _import_package()
        src = self.parameterAsSource(parameters, self.AREAS, context)
        name_field = self.parameterAsString(parameters, self.NAME_FIELD, context) or None
        state = self.parameterAsString(parameters, self.STATE, context)
        data = self.parameterAsString(parameters, self.DATA, context) or os.path.join(state, "granules")
        out = self.parameterAsString(parameters, self.OUTPUT_FOLDER, context)
        forest = self.parameterAsRasterLayer(parameters, self.FOREST, context)
        as_of = self.parameterAsString(parameters, self.AS_OF, context) or None

        # Areas to GeoJSON in lon/lat, the form the package reads.
        to_ll = QgsCoordinateTransform(src.sourceCrs(), QgsCoordinateReferenceSystem("EPSG:4326"),
                                       QgsProject.instance())
        feats = []
        for f in src.getFeatures():
            g = f.geometry()
            if g.isEmpty():
                continue
            g.transform(to_ll)
            props = {k: (v if isinstance(v, (int, float, str)) or v is None else str(v))
                     for k, v in zip(f.fields().names(), f.attributes())}
            feats.append({"type": "Feature", "properties": props, "geometry": json.loads(g.asJson())})
        os.makedirs(out, exist_ok=True)
        areas_path = os.path.join(out, "areas_lonlat.geojson")
        with open(areas_path, "w") as fh:
            json.dump({"type": "FeatureCollection", "features": feats}, fh)

        if self.parameterAsBool(parameters, self.FETCH, context):
            import datetime as dt
            from distwatch import fetch
            start = (dt.date.today() - dt.timedelta(days=60)).isoformat()
            feedback.pushInfo("Searching NASA CMR for DIST-ALERT granules...")
            fetch.download(fetch.pick(fetch.search(fetch.bbox_of(areas_path), start, log=feedback.pushInfo)),
                           data, log=feedback.pushInfo)
        if not os.path.isdir(data):
            raise QgsProcessingException(f"No granules folder at {data}")

        record, rows, _ = watch.run(
            data, areas_path, state, out,
            level=LEVELS[self.parameterAsEnum(parameters, self.LEVEL, context)],
            min_loss=self.parameterAsInt(parameters, self.MIN_LOSS, context),
            since=self.parameterAsString(parameters, self.SINCE, context) or None,
            min_patch_px=self.parameterAsInt(parameters, self.MIN_PATCH, context),
            forest_mask=forest.source() if forest else None, as_of=as_of, name_field=name_field,
            dry_run=self.parameterAsBool(parameters, self.DRY_RUN, context), io=gdal_io,
            log=feedback.pushInfo)

        # Load the new-loss patches and the per-area table into the project when the run ends.
        for path, name in ((os.path.join(out, "new_loss.geojson"), "DIST Watch new loss"),
                           (os.path.join(out, "area_summary.csv"), "DIST Watch area summary")):
            if os.path.exists(path) and os.path.getsize(path):
                lyr = QgsVectorLayer(path, name, "ogr")
                if lyr.isValid():
                    context.temporaryLayerStore().addMapLayer(lyr)
                    context.addLayerToLoadOnCompletion(
                        lyr.id(), QgsProcessingContext.LayerDetails(name, context.project(), self.OUTPUT_FOLDER))
        feedback.pushInfo(f"{record['new_loss_ha']} ha of new loss in {record['new_patches']} patches.")
        return {self.OUTPUT_FOLDER: out}

