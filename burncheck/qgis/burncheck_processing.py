"""QGIS Processing script: Burned Settlement Check.

Which settlements (or town blocks) show new burn scars between two dates?
Compares Sentinel-2 (or any 6-band surface reflectance) before and after an
event inside building footprints, and returns one row per settlement with the
share of building pixels that burned.

Install: Processing Toolbox > Scripts > Add Script to Toolbox... and pick this
file. The script needs the `burncheck` package folder (the folder holding
burncheck/core.py). It looks, in order, in: an installed package, the
BURNCHECK_PATH environment variable, and the folder above this script.

Uses GDAL/OGR (bundled with QGIS) and numpy only; scipy is used if present.
Written against the QGIS 3.34+/4.x Processing API (Qt5 and Qt6 via qgis.PyQt).
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
    QgsProcessingParameterVectorLayer,
)
from qgis.PyQt.QtCore import QCoreApplication


def _import_package():
    try:
        import burncheck  # noqa: F401
    except ImportError:
        candidates = [os.environ.get("BURNCHECK_PATH", "")]
        try:
            candidates.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        except NameError:
            pass
        for c in candidates:
            if c and os.path.isdir(os.path.join(c, "burncheck")):
                sys.path.insert(0, c)
                break
    from burncheck import core, gdal_run
    return core, gdal_run


def _src(layer):
    """Data source path of a layer, without '|layername=' suffixes."""
    return layer.source().split("|")[0]


class BurnedSettlementCheck(QgsProcessingAlgorithm):
    BEFORE, AFTER, BUILDINGS, UNITS, OUT = "BEFORE", "AFTER", "BUILDINGS", "UNITS", "OUTPUT"
    NUMS = [  # name, label, default, is_int
        ("T_DNBR", "dNBR rise above local building background", 0.10, False),
        ("T_DARK", "Minimum darkening (fraction of before brightness)", 0.05, False),
        ("LIKELY_PCT", "Likely burned: % of building pixels", 20.0, False),
        ("POSSIBLE_PCT", "Possible: % of building pixels", 7.0, False),
        ("MIN_CLEAR_PCT", "Minimum clear building pixels (%)", 50.0, False),
        ("LINK", "Join buildings closer than (m)", 40.0, False),
        ("MAX_KM2", "Split settlements larger than (km2) into blocks", 0.5, False),
        ("CELL", "Block size (m)", 250.0, False),
        ("MIN_BUILDINGS", "Minimum buildings per unit", 5, True),
    ]

    def tr(self, s):
        return QCoreApplication.translate("BurnedSettlementCheck", s)

    def createInstance(self):
        return BurnedSettlementCheck()

    def name(self):
        return "burnedsettlementcheck"

    def displayName(self):
        return self.tr("Burned Settlement Check")

    def group(self):
        return self.tr("Conflict and humanitarian")

    def groupId(self):
        return "conflicthumanitarian"

    def shortHelpString(self):
        return self.tr(
            "Before and after rasters: burncheck scenes (6 bands + SCL from 'python -m burncheck fetch-s2') or any "
            "6-band reflectance GeoTIFF in the order blue, green, red, NIR, SWIR1, SWIR2 (scale 0.0001). Several "
            "per side are combined by median. Buildings: footprint polygons (e.g. Overture, Google Open Buildings). "
            "Units (optional): your own polygons; if empty, settlements and town blocks are built from the "
            "buildings. Outputs summary.csv, units.geojson and burn_classes.tif in the output folder. A burn scar "
            "is evidence of fire or removed shelters, not proof of an attack: check every flagged unit by eye.")

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterMultipleLayers(self.BEFORE, self.tr("Before images"),
                                                               QgsProcessing.TypeRaster))
        self.addParameter(QgsProcessingParameterMultipleLayers(self.AFTER, self.tr("After images"),
                                                               QgsProcessing.TypeRaster))
        self.addParameter(QgsProcessingParameterVectorLayer(self.BUILDINGS, self.tr("Building footprints"),
                                                            [QgsProcessing.TypeVectorPolygon]))
        self.addParameter(QgsProcessingParameterVectorLayer(self.UNITS, self.tr("Reporting units (optional)"),
                                                            [QgsProcessing.TypeVectorPolygon], optional=True))
        for key, label, default, is_int in self.NUMS:
            self.addParameter(QgsProcessingParameterNumber(
                key, self.tr(label),
                QgsProcessingParameterNumber.Integer if is_int else QgsProcessingParameterNumber.Double,
                default))
        self.addParameter(QgsProcessingParameterFolderDestination(self.OUT, self.tr("Output folder")))

    def processAlgorithm(self, parameters, context, feedback):
        core, gdal_run = _import_package()
        before = [_src(l) for l in self.parameterAsLayerList(parameters, self.BEFORE, context)]
        after = [_src(l) for l in self.parameterAsLayerList(parameters, self.AFTER, context)]
        if not before or not after:
            raise QgsProcessingException("Give at least one before and one after image.")
        bld = _src(self.parameterAsVectorLayer(parameters, self.BUILDINGS, context))
        ul = self.parameterAsVectorLayer(parameters, self.UNITS, context)
        out = self.parameterAsString(parameters, self.OUT, context)
        num = {k: (self.parameterAsInt if i else self.parameterAsDouble)(parameters, k, context)
               for k, _, _, i in self.NUMS}
        params = dict(t_dnbr=num["T_DNBR"], t_dark=num["T_DARK"], likely_pct=num["LIKELY_PCT"],
                      possible_pct=num["POSSIBLE_PCT"], min_clear_pct=num["MIN_CLEAR_PCT"])
        _, counts = gdal_run.run(before, after, bld, out, _src(ul) if ul else None, params, num["LINK"],
                                 num["MAX_KM2"], num["CELL"], num["MIN_BUILDINGS"], log=feedback.pushInfo)
        feedback.pushInfo(f"Classes: {counts}")
        return {self.OUT: out}
