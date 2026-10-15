"""Processing provider: one 'Build QA mask' tool per product, plus apply, decode and the HLS CRS fix.

Written against the QGIS 3.28+ API with fallbacks so it also loads on QGIS 4
(Qt6). Parameters use the newer Qgis.* enums when they exist.
"""

import os

from qgis.core import (
    Qgis,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingLayerPostProcessorInterface,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterDestination,
    QgsProcessingParameterRasterLayer,
    QgsProcessingProvider,
)
from qgis.PyQt.QtCore import QCoreApplication

os.environ.setdefault("QAMASK_BACKEND", "gdal")  # QGIS has osgeo, rarely rasterio
from .qamask import PRODUCTS, ops  # noqa: E402

_INT = getattr(getattr(Qgis, "ProcessingNumberParameterType", None), "Integer", None) or QgsProcessingParameterNumber.Integer
_OPTIONAL = getattr(getattr(Qgis, "ProcessingParameterFlag", None), "Optional", None) or 8  # FlagOptional


def tr(s):
    return QCoreApplication.translate("QAMaskBuilder", s)


class _StylePostProcessor(QgsProcessingLayerPostProcessorInterface):
    """Load the .qml sidecar onto the output layer once QGIS adds it to the map."""

    instances = []  # Processing keeps only a raw pointer, so keep the Python object alive

    def __init__(self, qml):
        super().__init__()
        self.qml = qml

    def postProcessLayer(self, layer, context, feedback):
        if layer and self.qml and os.path.exists(self.qml):
            layer.loadNamedStyle(self.qml)
            layer.triggerRepaint()

    @classmethod
    def create(cls, qml):
        p = cls(qml)
        cls.instances.append(p)
        return p


class BuildMaskAlgorithm(QgsProcessingAlgorithm):
    INPUT, BAND, PRESET, DROP, KEEP, BUFFER, FIX_CRS, OUTPUT = "INPUT", "BAND", "PRESET", "DROP", "KEEP", "BUFFER", "FIX_CRS", "OUTPUT"

    def __init__(self, key):
        super().__init__()
        self.key = key
        self.p = PRODUCTS[key]
        self.flag_names = list(self.p.flags)
        self.preset_names = list(self.p.presets)

    def createInstance(self):
        return BuildMaskAlgorithm(self.key)

    def name(self):
        return f"build_{self.key}"

    def displayName(self):
        return tr(f"Build mask: {self.p.title}")

    def group(self):
        return tr("Build QA mask")

    def groupId(self):
        return "build"

    def shortHelpString(self):
        return tr(
            f"Turns the {self.p.layer} quality layer into a mask: 1 usable, 0 masked, 255 no data.<br>"
            "Pick a preset, or choose 'Use the flags ticked below' and tick the flags to drop. "
            "'Keep only' is for class layers (water, disturbance): a pixel must carry one of those flags to be usable.<br>"
            "The fix option relabels southern-hemisphere HLS and OPERA tiles from EPSG:326xx to EPSG:327xx, without resampling.<br>"
            f"Bit definitions: {self.p.source}")

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer(self.INPUT, tr(f"{self.p.layer} layer")))
        self.addParameter(QgsProcessingParameterNumber(self.BAND, tr("Band"), _INT, 1, minValue=1))
        presets = [tr("Use the flags ticked below")] + [f"{k}: {', '.join(v)}" for k, v in self.p.presets.items()]
        default = 1 + self.preset_names.index(self.p.default_preset) if self.p.default_preset in self.preset_names else 0
        self.addParameter(QgsProcessingParameterEnum(self.PRESET, tr("Preset"), presets, defaultValue=default))
        labels = [f"{n}: {self.p.flags[n]['label']}" for n in self.flag_names]
        tick = [self.flag_names.index(f) for f in self.p.presets.get(self.p.default_preset, [])]
        p = QgsProcessingParameterEnum(self.DROP, tr("Flags to drop"), labels, allowMultiple=True, defaultValue=tick)
        p.setFlags(p.flags() | _OPTIONAL)
        self.addParameter(p)
        p = QgsProcessingParameterEnum(self.KEEP, tr("Keep only pixels with one of these flags (optional)"), labels, allowMultiple=True)
        p.setFlags(p.flags() | _OPTIONAL)
        self.addParameter(p)
        self.addParameter(QgsProcessingParameterNumber(self.BUFFER, tr("Grow masked areas by (pixels)"), _INT, 0, minValue=0, maxValue=50))
        self.addParameter(QgsProcessingParameterBoolean(self.FIX_CRS, tr("Fix HLS/OPERA southern-hemisphere CRS (EPSG:326xx to 327xx)"),
                                                        defaultValue=self.p.is_hls_family))
        self.addParameter(QgsProcessingParameterRasterDestination(self.OUTPUT, tr("Mask")))

    def processAlgorithm(self, parameters, context, feedback):
        layer = self.parameterAsRasterLayer(parameters, self.INPUT, context)
        if layer is None:
            raise QgsProcessingException(tr("No input layer"))
        src = layer.source().split("|")[0]
        preset = self.parameterAsEnum(parameters, self.PRESET, context)
        if preset > 0:
            drop = [self.preset_names[preset - 1]]
        else:
            drop = [self.flag_names[i] for i in self.parameterAsEnums(parameters, self.DROP, context)]
            if not drop:
                raise QgsProcessingException(tr("Tick at least one flag to drop, or pick a preset"))
        keep = [self.flag_names[i] for i in self.parameterAsEnums(parameters, self.KEEP, context)]
        out = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)
        fix = "yes" if self.parameterAsBool(parameters, self.FIX_CRS, context) else "no"
        try:
            r = ops.build(src, out, self.key, drop, keep, self.parameterAsInt(parameters, self.BUFFER, context), fix,
                          self.parameterAsInt(parameters, self.BAND, context))
        except (KeyError, ValueError) as e:
            raise QgsProcessingException(str(e))
        m, c = r["mask"], r["crs"]
        feedback.pushInfo(f"Dropped: {', '.join(r['drop'])}" + (f"; keep only: {', '.join(r['keep'])}" if r["keep"] else ""))
        feedback.pushInfo(f"Usable: {m['usable_share_of_valid']:.1%} of valid pixels ({m['usable']} usable, {m['masked']} masked, {m['nodata']} no data)")
        if c.get("applied"):
            feedback.pushInfo(f"CRS fixed: EPSG:{c['input_epsg']} to EPSG:{c['output_epsg']}")
        elif c.get("needed"):
            feedback.pushWarning(f"CRS note: {c['reason']}. Not applied.")
        if context.willLoadLayerOnCompletion(out):
            context.layerToLoadOnCompletionDetails(out).setPostProcessor(_StylePostProcessor.create(r.get("style")))
        return {self.OUTPUT: out}


class ApplyMaskAlgorithm(QgsProcessingAlgorithm):
    def createInstance(self):
        return ApplyMaskAlgorithm()

    def name(self):
        return "apply_mask"

    def displayName(self):
        return tr("Apply mask to image")

    def group(self):
        return tr("Tools")

    def groupId(self):
        return "tools"

    def shortHelpString(self):
        return tr("Copies an image with every pixel the mask doesn't mark usable (1) set to no data. "
                  "The image must be on the mask's grid, e.g. a band from the same scene.")

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer("DATA", tr("Image")))
        self.addParameter(QgsProcessingParameterRasterLayer("MASK", tr("Mask from 'Build mask'")))
        self.addParameter(QgsProcessingParameterRasterDestination("OUTPUT", tr("Masked image")))

    def processAlgorithm(self, parameters, context, feedback):
        d = self.parameterAsRasterLayer(parameters, "DATA", context).source().split("|")[0]
        m = self.parameterAsRasterLayer(parameters, "MASK", context).source().split("|")[0]
        out = self.parameterAsOutputLayer(parameters, "OUTPUT", context)
        try:
            r = ops.apply(d, m, out)
        except ValueError as e:
            raise QgsProcessingException(str(e))
        feedback.pushInfo(f"Kept {r['usable']} pixels; no data value {r['nodata']}")
        return {"OUTPUT": out}


class DecodeAlgorithm(QgsProcessingAlgorithm):
    keys = list(PRODUCTS)

    def createInstance(self):
        return DecodeAlgorithm()

    def name(self):
        return "decode"

    def displayName(self):
        return tr("Decode QA layer into one band per field")

    def group(self):
        return tr("Tools")

    def groupId(self):
        return "tools"

    def shortHelpString(self):
        return tr("Writes each field of a quality layer (cloud, shadow, aerosol level...) as its own named band, "
                  "so you can inspect them before choosing flags.")

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer("INPUT", tr("QA layer")))
        self.addParameter(QgsProcessingParameterEnum("PRODUCT", tr("Product"), [PRODUCTS[k].title for k in self.keys], defaultValue=0))
        self.addParameter(QgsProcessingParameterBoolean("FIX_CRS", tr("Fix HLS/OPERA southern-hemisphere CRS"), defaultValue=True))
        self.addParameter(QgsProcessingParameterRasterDestination("OUTPUT", tr("Decoded fields")))

    def processAlgorithm(self, parameters, context, feedback):
        src = self.parameterAsRasterLayer(parameters, "INPUT", context).source().split("|")[0]
        key = self.keys[self.parameterAsEnum(parameters, "PRODUCT", context)]
        out = self.parameterAsOutputLayer(parameters, "OUTPUT", context)
        fix = "auto" if self.parameterAsBool(parameters, "FIX_CRS", context) else "no"
        r = ops.decode(src, out, key, fix)
        feedback.pushInfo(f"Bands: {', '.join(r['bands'])}")
        return {"OUTPUT": out}


class FixCrsAlgorithm(QgsProcessingAlgorithm):
    def createInstance(self):
        return FixCrsAlgorithm()

    def name(self):
        return "fix_hls_crs"

    def displayName(self):
        return tr("Fix HLS southern-hemisphere CRS")

    def group(self):
        return tr("Tools")

    def groupId(self):
        return "tools"

    def shortHelpString(self):
        return tr("HLS v2.0 and OPERA DSWx-HLS files south of the equator are labelled with a northern UTM zone "
                  "(EPSG:326xx) and negative northings. This writes a copy (or a small VRT) labelled EPSG:327xx "
                  "with 10,000,000 m added to Y. No pixels are resampled. Files that don't need it are left alone.")

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer("INPUT", tr("HLS or OPERA file")))
        self.addParameter(QgsProcessingParameterBoolean("VRT", tr("Write a VRT instead of copying pixels"), defaultValue=False))
        self.addParameter(QgsProcessingParameterBoolean("FORCE", tr("Also relabel files that aren't HLS/OPERA"), defaultValue=False))
        self.addParameter(QgsProcessingParameterFileDestination("OUTPUT", tr("Fixed file"), "GeoTIFF (*.tif);;VRT (*.vrt)"))

    def processAlgorithm(self, parameters, context, feedback):
        src = self.parameterAsRasterLayer(parameters, "INPUT", context).source().split("|")[0]
        out = self.parameterAsFileOutput(parameters, "OUTPUT", context)
        vrt = self.parameterAsBool(parameters, "VRT", context) or out.lower().endswith(".vrt")
        if vrt and not out.lower().endswith(".vrt"):
            out = os.path.splitext(out)[0] + ".vrt"
        r = ops.fix_crs(src, out, vrt, self.parameterAsBool(parameters, "FORCE", context))
        feedback.pushInfo(r["reason"])
        if not r.get("output"):
            feedback.pushWarning(tr("Nothing written"))
        return {"OUTPUT": r.get("output") or ""}


class QAMaskProvider(QgsProcessingProvider):
    def loadAlgorithms(self):
        for k in PRODUCTS:
            self.addAlgorithm(BuildMaskAlgorithm(k))
        for a in (ApplyMaskAlgorithm(), DecodeAlgorithm(), FixCrsAlgorithm()):
            self.addAlgorithm(a)

    def id(self):
        return "qamaskbuilder"

    def name(self):
        return tr("QA Mask Builder")

    def longName(self):
        return tr("QA Mask Builder (HLS, Landsat, MODIS, ECOSTRESS, OPERA)")
