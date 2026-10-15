"""QGIS Processing script: ClassSpectra, per-class spectral signatures.

Install: Processing Toolbox > Scripts > Add Script to Toolbox... and pick this
file. The script needs the `classspectra` package folder (the folder that
holds classspectra/core.py). It looks, in order, in: an installed package,
the CLASSSPECTRA_PATH environment variable, and the folder above this script.

Uses GDAL (bundled with QGIS) for reading and alignment, numpy for the maths
and matplotlib for the chart, so no extra install is needed in QGIS.
Written against the QGIS 3.34+/4.x Processing API (Qt5 and Qt6 both work via
qgis.PyQt).
"""

import os
import sys

import numpy as np
from osgeo import gdal
from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterEnum,
    QgsProcessingParameterExtent,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterString,
)
from qgis.PyQt.QtCore import QCoreApplication

gdal.UseExceptions()


def _import_package():
    try:
        import classspectra  # noqa: F401
    except ImportError:
        candidates = [os.environ.get("CLASSSPECTRA_PATH", "")]
        try:
            candidates.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        except NameError:
            pass
        for c in candidates:
            if c and os.path.isdir(os.path.join(c, "classspectra")):
                sys.path.insert(0, c)
                break
    from classspectra import core, report, sensors, legends  # noqa: F401
    return core, report, sensors, legends


PRESET_KEYS = ["s2_l2a", "s2_l2a_offset", "hls_s30", "hls_l30", "none"]
LEGEND_KEYS = ["worldcover", "io", "dynamicworld", "none"]


def _warp_to(src_path, ref_ds, resampling, band=1, dtype=gdal.GDT_Int16):
    """Warp one band of src_path onto ref_ds's grid; return numpy array."""
    gt, w, h = ref_ds.GetGeoTransform(), ref_ds.RasterXSize, ref_ds.RasterYSize
    bounds = (gt[0], gt[3] + gt[5] * h, gt[0] + gt[1] * w, gt[3])
    out = gdal.Warp("", src_path, format="MEM", outputBounds=bounds, width=w, height=h,
                    dstSRS=ref_ds.GetProjection(), resampleAlg=resampling, outputType=dtype,
                    srcBands=[band], dstNodata=0)
    return out.GetRasterBand(1).ReadAsArray()


def _purity(map_path, ref_ds, labels):
    """Share of each coarse pixel covered by its majority class (map finer than image)."""
    src = gdal.Open(map_path)
    arr = src.GetRasterBand(1).ReadAsArray()
    purity = np.zeros(labels.shape, "float32")
    drv = gdal.GetDriverByName("MEM")
    for v in np.unique(labels):
        if v == 0:
            continue
        tmp = drv.Create("", src.RasterXSize, src.RasterYSize, 1, gdal.GDT_Float32)
        tmp.SetGeoTransform(src.GetGeoTransform())
        tmp.SetProjection(src.GetProjection())
        tmp.GetRasterBand(1).WriteArray((arr == v).astype("float32"))
        frac = _warp_to(tmp, ref_ds, "average", dtype=gdal.GDT_Float32)
        purity[labels == v] = frac[labels == v]
    return purity


class ClassSpectraAlgorithm(QgsProcessingAlgorithm):
    IMAGE, LANDCOVER, LEGEND, PRESET, SCALE, OFFSET = "IMAGE", "LANDCOVER", "LEGEND", "PRESET", "SCALE", "OFFSET"
    MASK, MASK_INVALID, MASK_BITS, EXTENT = "MASK", "MASK_INVALID", "MASK_BITS", "EXTENT"
    EROSION, PURITY, OUTLIER_Z, MIN_PIXELS, SEPARABILITY, OUT = (
        "EROSION", "PURITY", "OUTLIER_Z", "MIN_PIXELS", "SEPARABILITY", "OUTPUT_FOLDER")

    def tr(self, s):
        return QCoreApplication.translate("ClassSpectra", s)

    def createInstance(self):
        return ClassSpectraAlgorithm()

    def name(self):
        return "classspectra"

    def displayName(self):
        return self.tr("Land cover class spectra (ClassSpectra)")

    def group(self):
        return self.tr("Map QA")

    def groupId(self):
        return "mapqa"

    def shortHelpString(self):
        return self.tr(
            "Per-class spectral signatures (median and spread) from a multispectral image and a land "
            "cover map. The map is aligned to the image grid; edge pixels, impure coarse pixels and "
            "spectral outliers are dropped before statistics. Outputs signatures.csv, "
            "class_summary.csv, separability.csv and charts in the output folder.\n\n"
            "Presets: s2_l2a = Sentinel-2 L2A with offset already removed (AWS COGs); "
            "s2_l2a_offset = raw ESA L2A DN from baseline 04.00 on; hls_s30/hls_l30 = NASA HLS v2.0 "
            "band stacks in native band order.")

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer(self.IMAGE, self.tr("Multispectral image (band stack)")))
        self.addParameter(QgsProcessingParameterRasterLayer(self.LANDCOVER, self.tr("Land cover map")))
        self.addParameter(QgsProcessingParameterEnum(self.LEGEND, self.tr("Map legend"), LEGEND_KEYS, defaultValue=0))
        self.addParameter(QgsProcessingParameterEnum(self.PRESET, self.tr("Sensor preset"), PRESET_KEYS, defaultValue=0))
        self.addParameter(QgsProcessingParameterNumber(self.SCALE, self.tr("Scale override (0 = use preset)"),
                                                       QgsProcessingParameterNumber.Double, 0.0))
        self.addParameter(QgsProcessingParameterNumber(self.OFFSET, self.tr("Offset override (used if scale override set)"),
                                                       QgsProcessingParameterNumber.Double, 0.0))
        self.addParameter(QgsProcessingParameterRasterLayer(self.MASK, self.tr("Quality layer (SCL / Fmask)"), optional=True))
        self.addParameter(QgsProcessingParameterString(self.MASK_INVALID, self.tr("Quality values to reject (comma list)"),
                                                       "0,1,3,8,9,10,11", optional=True))
        self.addParameter(QgsProcessingParameterNumber(self.MASK_BITS, self.tr("Quality bits to reject (HLS Fmask: 15)"),
                                                       QgsProcessingParameterNumber.Integer, 0))
        self.addParameter(QgsProcessingParameterExtent(self.EXTENT, self.tr("Area (optional)"), optional=True))
        self.addParameter(QgsProcessingParameterNumber(self.EROSION, self.tr("Edge erosion (pixels)"),
                                                       QgsProcessingParameterNumber.Integer, 1, minValue=0, maxValue=5))
        self.addParameter(QgsProcessingParameterNumber(self.PURITY, self.tr("Minimum purity (map finer than image)"),
                                                       QgsProcessingParameterNumber.Double, 0.75, minValue=0, maxValue=1))
        self.addParameter(QgsProcessingParameterNumber(self.OUTLIER_Z, self.tr("Outlier robust z (0 = off)"),
                                                       QgsProcessingParameterNumber.Double, 3.5, minValue=0))
        self.addParameter(QgsProcessingParameterNumber(self.MIN_PIXELS, self.tr("Minimum pixels per class"),
                                                       QgsProcessingParameterNumber.Integer, 30, minValue=1))
        self.addParameter(QgsProcessingParameterBoolean(self.SEPARABILITY, self.tr("Compute JM separability"), True))
        self.addParameter(QgsProcessingParameterFolderDestination(self.OUT, self.tr("Output folder")))

    def processAlgorithm(self, parameters, context, feedback):
        core, report, sensors, _ = _import_package()
        img_layer = self.parameterAsRasterLayer(parameters, self.IMAGE, context)
        lc_layer = self.parameterAsRasterLayer(parameters, self.LANDCOVER, context)
        legend = LEGEND_KEYS[self.parameterAsEnum(parameters, self.LEGEND, context)]
        preset_key = PRESET_KEYS[self.parameterAsEnum(parameters, self.PRESET, context)]
        out = self.parameterAsString(parameters, self.OUT, context)
        os.makedirs(out, exist_ok=True)

        preset = sensors.PRESETS.get(preset_key, {"bands": None, "wavelengths": None,
                                                  "scale": 1.0, "offset": 0.0, "nodata": None})
        scale, offset = preset["scale"], preset["offset"]
        s_over = self.parameterAsDouble(parameters, self.SCALE, context)
        if s_over:
            scale, offset = s_over, self.parameterAsDouble(parameters, self.OFFSET, context)

        # Clip the image to the extent (in the image CRS) into memory
        src_path = img_layer.source()
        extent = self.parameterAsExtent(parameters, self.EXTENT, context, img_layer.crs())
        if extent is not None and not extent.isNull() and not extent.isEmpty():
            ds = gdal.Translate("", src_path, format="MEM",
                                projWin=[extent.xMinimum(), extent.yMaximum(), extent.xMaximum(), extent.yMinimum()])
        else:
            ds = gdal.Open(src_path)
        if ds is None:
            raise QgsProcessingException("Could not read the image")
        feedback.pushInfo(f"Image grid {ds.RasterXSize} x {ds.RasterYSize}, {ds.RasterCount} bands")

        raw = ds.ReadAsArray().astype("float32")
        if raw.ndim == 2:
            raw = raw[None]
        nodata = ds.GetRasterBand(1).GetNoDataValue()
        if nodata is None:
            nodata = preset["nodata"]
        img = raw * scale + offset
        if nodata is not None:
            img[raw == nodata] = np.nan

        names = preset["bands"] or [ds.GetRasterBand(i + 1).GetDescription() or f"band{i+1}" for i in range(ds.RasterCount)]
        if len(names) != img.shape[0]:
            raise QgsProcessingException(f"Image has {img.shape[0]} bands but preset {preset_key} expects {len(names)}")
        wl = preset["wavelengths"]
        red_nir = None
        if preset_key in sensors.RED_NIR:
            r, n = sensors.RED_NIR[preset_key]
            red_nir = (names.index(r), names.index(n))

        valid = np.all(np.isfinite(img), axis=0)
        mask_layer = self.parameterAsRasterLayer(parameters, self.MASK, context)
        if mask_layer is not None:
            q = _warp_to(mask_layer.source(), ds, "near", dtype=gdal.GDT_Int32)
            invalid = [int(v) for v in (self.parameterAsString(parameters, self.MASK_INVALID, context) or "").split(",") if v.strip()]
            bits = self.parameterAsInt(parameters, self.MASK_BITS, context)
            if invalid:
                valid &= ~np.isin(q, invalid)
            if bits:
                valid &= (q & bits) == 0

        # Align the map; use majority + purity if the map is much finer than the image
        lc = gdal.Open(lc_layer.source())
        ratio = abs(ds.GetGeoTransform()[1]) / max(abs(lc.GetGeoTransform()[1]), 1e-12)
        same_units = (lc_layer.crs() == img_layer.crs())
        finer = same_units and ratio >= 1.5
        if not same_units:
            # rough check in metres for a geographic map (degrees)
            if lc_layer.crs().isGeographic() and not img_layer.crs().isGeographic():
                finer = abs(ds.GetGeoTransform()[1]) / (abs(lc.GetGeoTransform()[1]) * 111_320) >= 1.5
        labels = _warp_to(lc_layer.source(), ds, "mode" if finer else "near").astype(int)
        purity = _purity(lc_layer.source(), ds, labels) if finer else None
        feedback.pushInfo(f"Map aligned ({'majority + purity' if finer else 'nearest neighbour'})")
        feedback.setProgress(30)

        res = core.class_signatures(
            img, labels, erosion=self.parameterAsInt(parameters, self.EROSION, context),
            purity=purity, min_purity=self.parameterAsDouble(parameters, self.PURITY, context),
            outlier_z=self.parameterAsDouble(parameters, self.OUTLIER_Z, context),
            min_pixels=self.parameterAsInt(parameters, self.MIN_PIXELS, context),
            red_nir=red_nir, valid=valid & (labels > 0))
        feedback.setProgress(70)

        report.write_signatures_csv(os.path.join(out, "signatures.csv"), res, names, wl, legend)
        rows = report.summary_rows(res, legend)
        report.write_summary_csv(os.path.join(out, "class_summary.csv"), rows)
        try:
            import matplotlib  # noqa: F401
            charts = True
        except ImportError:
            charts = False
            feedback.reportError("matplotlib not found: CSVs written, charts skipped", fatalError=False)
        if charts:
            report.plot_signatures(os.path.join(out, "signatures.png"), res, names, wl, legend,
                                   title=f"{img_layer.name()} by {lc_layer.name()}")
        if self.parameterAsBool(parameters, self.SEPARABILITY, context):
            cls, m = core.separability_matrix(res)
            report.write_separability_csv(os.path.join(out, "separability.csv"), cls, m, legend)
            if charts:
                report.plot_separability(os.path.join(out, "separability.png"), cls, m, legend)
        for r in rows:
            feedback.pushInfo(f"{r['class_name']}: {r['used']} of {r['pixels']} px, outliers "
                              f"{r['outlier_share']*100:.1f}%, NDVI {r['ndvi_median']} {r['warnings']}")
        feedback.setProgress(100)
        return {self.OUT: out}
