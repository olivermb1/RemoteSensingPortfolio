"""QGIS Processing script: Flooded Cropland Calculator.

Hectares of cropland newly under water per polygon (admin units or FEWS NET
livelihood zones), from OPERA DSWx, Sentinel-1 backscatter, optical surface
reflectance or any water mask, compared with a pre-event baseline.

Install: Processing Toolbox > Scripts > Add Script to Toolbox... and pick this
file. The script needs the `floodcrop` package folder (the folder holding
floodcrop/core.py). It looks, in order, in: an installed package, the
FLOODCROP_PATH environment variable, and the folder above this script.

Uses GDAL/OGR (bundled with QGIS) and numpy only. Written against the QGIS
3.34+/4.x Processing API (Qt5 and Qt6 both work via qgis.PyQt).
"""

import os
import sys

from qgis.core import (
    Qgis,
    QgsFeature,
    QgsFeatureSink,
    QgsField,
    QgsFields,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterMultipleLayers,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterLayer,
)
from qgis.PyQt.QtCore import QCoreApplication

try:
    from qgis.PyQt.QtCore import QMetaType
    DOUBLE_T, STRING_T = QMetaType.Type.Double, QMetaType.Type.QString
except (ImportError, AttributeError):  # QGIS 3.x before 3.38
    from qgis.PyQt.QtCore import QVariant
    DOUBLE_T, STRING_T = QVariant.Double, QVariant.String


def _import_package():
    try:
        import floodcrop  # noqa: F401
    except ImportError:
        candidates = [os.environ.get("FLOODCROP_PATH", "")]
        try:
            candidates.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        except NameError:
            pass
        for c in candidates:
            if c and os.path.isdir(os.path.join(c, "floodcrop")):
                sys.path.insert(0, c)
                break
    from floodcrop import core, gdal_io, pipeline, report
    return core, gdal_io, pipeline, report


SOURCES = ["dswx", "sar", "optical", "mask"]
SOURCE_LABELS = ["OPERA DSWx (WTR/BWTR layer)", "Sentinel-1 VV backscatter (linear or dB)",
                 "Optical reflectance, 6 bands: blue green red nir swir1 swir2 (DSWx-HLS tests)",
                 "Water mask (1 water, 0 dry)"]
PRESETS = ["worldcover", "deafrica", "worldcereal", "binary"]
PRESET_LABELS = ["ESA WorldCover (class 40)", "Digital Earth Africa crop mask (1)", "ESA WorldCereal (100)",
                 "Any value > 0"]

try:
    DOUBLE = Qgis.ProcessingNumberParameterType.Double
    INTEGER = Qgis.ProcessingNumberParameterType.Integer
    RASTER_T = Qgis.ProcessingSourceType.Raster
    POLY_T = Qgis.ProcessingSourceType.VectorPolygon
except AttributeError:
    DOUBLE, INTEGER = QgsProcessingParameterNumber.Double, QgsProcessingParameterNumber.Integer
    RASTER_T, POLY_T = QgsProcessing.TypeRaster, QgsProcessing.TypeVectorPolygon


class FloodCropAlgorithm(QgsProcessingAlgorithm):
    SOURCE, EVENT, BASELINE, CROPLAND, PRESET = "SOURCE", "EVENT", "BASELINE", "CROPLAND", "PRESET"
    ZONES, NAME_FIELD, PERMANENT, PERM_T = "ZONES", "NAME_FIELD", "PERMANENT", "PERM_T"
    EVENT_CLOUDS, BASE_CLOUDS, FMASK, SCALE = "EVENT_CLOUDS", "BASE_CLOUDS", "FMASK", "SCALE"
    SAR_T, DROP, LOOSE, SMOOTH, CHANGE = "SAR_T", "DROP", "LOOSE", "SMOOTH", "CHANGE"
    OUTPUT, FOLDER = "OUTPUT", "FOLDER"

    def tr(self, s):
        return QCoreApplication.translate("FloodCrop", s)

    def createInstance(self):
        return FloodCropAlgorithm()

    def name(self):
        return "floodcrop"

    def displayName(self):
        return self.tr("Flooded cropland per area (Flooded Cropland Calculator)")

    def group(self):
        return self.tr("Remote sensing tools")

    def groupId(self):
        return "rstools"

    def shortHelpString(self):
        return self.tr(
            "Hectares of cropland newly under water in each polygon.\n\n"
            "Event layers: water data on/after the event (several dates are merged: water on any date). "
            "Baseline layers: the same kind of data from before the event; anything wet then is not counted. "
            "The first event layer sets the analysis grid.\n\n"
            "Cropland is resampled as a fraction of each grid pixel, so a 10 m crop map on a 30 m water grid "
            "counts partly-cropped pixels proportionally.\n\n"
            "Outputs: the polygons with flooded_crop_ha, flooded_crop_pct (of observed cropland), "
            "crop_observed_pct and more; and, in the output folder, flood_classes.tif "
            "(1 new water, 2 new partial water, 3 water before/permanent, 255 not observed), "
            "flooded_crop_fraction.tif, summary.csv and run.json.\n\n"
            "Sentinel-1 water is a simple threshold + backscatter-drop rule, and the optical option is a "
            "re-implementation of the DSWx-HLS tests without its terrain masks. Both are stand-ins for the "
            "OPERA DSWx products and are not validated.")

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterEnum(self.SOURCE, self.tr("Water data"), SOURCE_LABELS, defaultValue=0))
        self.addParameter(QgsProcessingParameterMultipleLayers(self.EVENT, self.tr("Event layer(s)"), RASTER_T))
        self.addParameter(QgsProcessingParameterMultipleLayers(self.BASELINE, self.tr("Baseline (pre-event) layer(s)"),
                                                               RASTER_T, optional=True))
        self.addParameter(QgsProcessingParameterRasterLayer(self.CROPLAND, self.tr("Cropland map"), optional=True))
        self.addParameter(QgsProcessingParameterEnum(self.PRESET, self.tr("Cropland map type"), PRESET_LABELS,
                                                     defaultValue=0))
        self.addParameter(QgsProcessingParameterFeatureSource(self.ZONES, self.tr("Areas (admin units or livelihood zones)"),
                                                              [POLY_T]))
        self.addParameter(QgsProcessingParameterField(self.NAME_FIELD, self.tr("Area name field"),
                                                      parentLayerParameterName=self.ZONES, optional=True))
        self.addParameter(QgsProcessingParameterRasterLayer(self.PERMANENT, self.tr(
            "Permanent water frequency (WOfS 0-1 or JRC occurrence 0-100), optional"), optional=True))
        self.addParameter(QgsProcessingParameterNumber(self.PERM_T, self.tr("Permanent water if frequency >="),
                                                       DOUBLE, 0.8, minValue=0, maxValue=1))
        self.addParameter(QgsProcessingParameterMultipleLayers(self.EVENT_CLOUDS, self.tr(
            "Optical: cloud layer per event layer (SCL or Fmask), same order"), RASTER_T, optional=True))
        self.addParameter(QgsProcessingParameterMultipleLayers(self.BASE_CLOUDS, self.tr(
            "Optical: cloud layer per baseline layer"), RASTER_T, optional=True))
        self.addParameter(QgsProcessingParameterBoolean(self.FMASK, self.tr("Optical: cloud layers are HLS Fmask "
                                                                            "(unticked = Sentinel-2 SCL)"), False))
        self.addParameter(QgsProcessingParameterNumber(self.SCALE, self.tr(
            "Optical: multiply reflectance onto 0-10000 (10000 for 0-1 floats)"), DOUBLE, 1.0))
        self.addParameter(QgsProcessingParameterBoolean(self.CHANGE, self.tr(
            "Sentinel-1: also count a backscatter drop vs baseline as water"), True))
        self.addParameter(QgsProcessingParameterNumber(self.SAR_T, self.tr(
            "Sentinel-1: VV water threshold dB (0 = automatic Otsu)"), DOUBLE, 0.0, maxValue=0))
        self.addParameter(QgsProcessingParameterNumber(self.DROP, self.tr("Sentinel-1: drop (dB)"), DOUBLE, 3.0))
        self.addParameter(QgsProcessingParameterNumber(self.LOOSE, self.tr(
            "Sentinel-1: dropped pixels must be below (dB)"), DOUBLE, -14.0))
        self.addParameter(QgsProcessingParameterNumber(self.SMOOTH, self.tr("Sentinel-1: smoothing window (pixels)"),
                                                       INTEGER, 5, minValue=1))
        self.addParameter(QgsProcessingParameterFeatureSink(self.OUTPUT, self.tr("Flooded cropland per area")))
        self.addParameter(QgsProcessingParameterFolderDestination(self.FOLDER, self.tr("Output folder (rasters, CSV)")))

    def processAlgorithm(self, parameters, context, feedback):
        core, gdal_io, pipeline, report = _import_package()
        src_i = self.parameterAsEnum(parameters, self.SOURCE, context)
        source = SOURCES[src_i]
        paths = lambda key: [lyr.source() for lyr in (self.parameterAsLayerList(parameters, key, context) or [])]  # noqa: E731
        event, baseline = paths(self.EVENT), paths(self.BASELINE)
        if not event:
            raise QgsProcessingException(self.tr("Give at least one event layer."))
        crop_lyr = self.parameterAsRasterLayer(parameters, self.CROPLAND, context)
        perm_lyr = self.parameterAsRasterLayer(parameters, self.PERMANENT, context)
        preset = PRESETS[self.parameterAsEnum(parameters, self.PRESET, context)]
        folder = self.parameterAsString(parameters, self.FOLDER, context)
        os.makedirs(folder, exist_ok=True)
        change = self.parameterAsBool(parameters, self.CHANGE, context)
        if source == "sar" and change and not baseline:
            raise QgsProcessingException(self.tr("The backscatter-drop rule needs baseline layers (or untick it)."))

        # zones -> WKT in the source layer CRS
        zsrc = self.parameterAsSource(parameters, self.ZONES, context)
        name_field = self.parameterAsString(parameters, self.NAME_FIELD, context) or None
        zones, feats = [], []
        for i, f in enumerate(zsrc.getFeatures()):
            props = {fld.name(): f[fld.name()] for fld in zsrc.fields()}
            nm = f[name_field] if name_field else None
            if nm is None:
                for k in ("name", "NAME", "shapeName", "ADM2_EN", "ADM1_EN", "LZNAMEEN", "LZNAME", "FNID"):
                    if k in props and props[k]:
                        nm = props[k]
                        break
            zones.append((str(nm if nm is not None else i), props, f.geometry().asWkt()))
            feats.append(f)
        sar_t = self.parameterAsDouble(parameters, self.SAR_T, context)
        feedback.pushInfo(f"{source}: {len(event)} event, {len(baseline)} baseline layers; {len(zones)} areas")
        res = pipeline.run(
            source, event, baseline, crop_lyr.source() if crop_lyr else None, preset,
            (zones, zsrc.sourceCrs().toWkt()), None, perm_lyr.source() if perm_lyr else None,
            self.parameterAsDouble(parameters, self.PERM_T, context), paths(self.EVENT_CLOUDS) or None,
            paths(self.BASE_CLOUDS) or None, "any", "any", folder, backend=gdal_io,
            cloud_kind="fmask" if self.parameterAsBool(parameters, self.FMASK, context) else "scl",
            scale=self.parameterAsDouble(parameters, self.SCALE, context),
            sar_method="change" if change else "threshold", sar_threshold=sar_t if sar_t < 0 else None,
            drop_db=self.parameterAsDouble(parameters, self.DROP, context),
            loose_db=self.parameterAsDouble(parameters, self.LOOSE, context),
            smooth=self.parameterAsInt(parameters, self.SMOOTH, context))
        res["geoms"] = []  # polygons go to the QGIS sink, not GeoJSON
        report.write_tables(res, folder)

        fields = QgsFields(zsrc.fields())
        fields.append(QgsField("fc_zone", STRING_T))
        for k in core.SUMMARY_FIELDS:
            fields.append(QgsField(k, DOUBLE_T))
        sink, dest = self.parameterAsSink(parameters, self.OUTPUT, context, fields, zsrc.wkbType(), zsrc.sourceCrs())
        for f, r in zip(feats, res["rows"]):
            nf = QgsFeature(fields)
            nf.setGeometry(f.geometry())
            nf.setAttributes(list(f.attributes()) + [r["zone"]] + [round(r[k], 3) for k in core.SUMMARY_FIELDS])
            sink.addFeature(nf, QgsFeatureSink.FastInsert)
        w = res["whole"]
        feedback.pushInfo(f"Whole grid: {w['flooded_crop_ha']:,.0f} ha flooded cropland of {w['crop_ha']:,.0f} ha "
                          f"({w['flooded_crop_pct']:.2f}% of observed cropland); thresholds: "
                          f"{res['meta'].get('event_detail')}")
        return {self.OUTPUT: dest, self.FOLDER: folder}
