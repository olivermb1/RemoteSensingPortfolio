"""QGIS Processing script: HLS access doctor.

Runs the doctor's checks inside QGIS, with QGIS's own Python and GDAL. That
matters because QGIS often has a different GDAL and different environment
variables from a terminal, which is why HLS streams in a notebook but not in
QGIS (or the other way round).

Install: Processing Toolbox > Scripts > Add Script to Toolbox... and pick this
file. It needs the `hlsdoctor` package folder (the one holding
hlsdoctor/cli.py). It looks, in order, in: an installed package, the
HLSDOCTOR_PATH environment variable, and the folder above this script.
The doctor uses only the Python standard library plus QGIS's GDAL, so nothing
else needs installing. Written against the QGIS 3.34+/4.x Processing API.
"""

import os
import sys

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProcessingAlgorithm,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterExtent,
    QgsProcessingParameterFile,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterNumber,
    QgsProcessingParameterString,
    QgsProject,
)
from qgis.PyQt.QtCore import QCoreApplication


def _import_package():
    try:
        import hlsdoctor  # noqa: F401
    except ImportError:
        candidates = [os.environ.get("HLSDOCTOR_PATH", "")]
        try:
            candidates.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        except NameError:
            pass
        for c in candidates:
            if c and os.path.isdir(os.path.join(c, "hlsdoctor")):
                sys.path.insert(0, c)
                break
    from hlsdoctor import cli, endpoints, env, report  # noqa: F401
    return cli, endpoints, env, report


class HlsDoctorAlgorithm(QgsProcessingAlgorithm):
    EXTENT, DAYS, OFFLINE, FOLDER, URL, APPLY, OUTPUT = (
        "EXTENT", "DAYS", "OFFLINE", "FOLDER", "STREAM_URL", "APPLY_GDAL", "OUTPUT")

    def tr(self, s):
        return QCoreApplication.translate("HlsDoctor", s)

    def createInstance(self):
        return HlsDoctorAlgorithm()

    def name(self):
        return "hlsdoctor"

    def displayName(self):
        return self.tr("HLS access doctor")

    def group(self):
        return self.tr("NASA HLS")

    def groupId(self):
        return "nasahls"

    def shortHelpString(self):
        return self.tr(
            "Checks whether this QGIS can get NASA HLS data: Earthdata login (~/.netrc), token, network, "
            "CMR search, a test download, GDAL streaming with QGIS's own GDAL, and direct S3 access. "
            "It can also check a folder of downloaded HLS files for login pages saved as .tif, cut-off "
            "downloads, the southern-hemisphere CRS label, missing EPSG codes and missing no-data.\n\n"
            "Every problem comes with a plain-words fix. Tick 'Apply recommended GDAL settings' to set "
            "the cookie jar and related options for this QGIS session, so /vsicurl/ HLS layers load.")

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterExtent(
            self.EXTENT, self.tr("Area for the test search (default: Nakuru, Kenya)"), optional=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.DAYS, self.tr("Search this many days back"), defaultValue=90, minValue=1, maxValue=3650))
        self.addParameter(QgsProcessingParameterBoolean(
            self.OFFLINE, self.tr("Offline: skip checks that need the internet"), defaultValue=False))
        self.addParameter(QgsProcessingParameterFile(
            self.FOLDER, self.tr("Also check downloaded HLS files in this folder"),
            behavior=QgsProcessingParameterFile.Folder, optional=True))
        self.addParameter(QgsProcessingParameterString(
            self.URL, self.tr("Test streaming on this https URL instead (optional)"), optional=True))
        self.addParameter(QgsProcessingParameterBoolean(
            self.APPLY, self.tr("Apply recommended GDAL settings for this QGIS session"), defaultValue=False))
        self.addParameter(QgsProcessingParameterFileDestination(
            self.OUTPUT, self.tr("Report (Markdown)"), "Markdown (*.md)", optional=True))

    def _bbox(self, parameters, context):
        rect = self.parameterAsExtent(parameters, self.EXTENT, context)
        if rect is None or rect.isNull() or rect.isEmpty():
            return None
        crs = self.parameterAsExtentCrs(parameters, self.EXTENT, context)
        wgs = QgsCoordinateReferenceSystem("EPSG:4326")
        if crs.isValid() and crs != wgs:
            rect = QgsCoordinateTransform(crs, wgs, QgsProject.instance()).transformBoundingBox(rect)
        return (rect.xMinimum(), rect.yMinimum(), rect.xMaximum(), rect.yMaximum())

    def processAlgorithm(self, parameters, context, feedback):
        cli, endpoints, env, report = _import_package()
        if self.parameterAsBoolean(parameters, self.APPLY, context):
            from osgeo import gdal
            for k, v in env.GDAL_RECOMMENDED.items():
                gdal.SetConfigOption(k, v)
                os.environ.setdefault(k, v)
            feedback.pushInfo("Applied for this session: " + ", ".join(f"{k}={v}" for k, v in env.GDAL_RECOMMENDED.items()))
            feedback.pushInfo("To keep them, add the same names under Settings > Options > System > Environment.")
        bbox = self._bbox(parameters, context) or endpoints.DEFAULT_BBOX
        folder = self.parameterAsFile(parameters, self.FOLDER, context)
        url = self.parameterAsString(parameters, self.URL, context).strip() or None
        res = cli.run_check(bbox=bbox, days=self.parameterAsInt(parameters, self.DAYS, context),
                            offline=self.parameterAsBoolean(parameters, self.OFFLINE, context),
                            stream_url=url, files=[folder] if folder else None,
                            log=lambda s: feedback.pushInfo("... " + s))
        for line in report.to_text(res).splitlines():
            if line.startswith("[FAIL]"):
                feedback.reportError(line, fatalError=False)
            elif line.startswith("[WARN]"):
                feedback.pushWarning(line)
            else:
                feedback.pushInfo(line)
        out = self.parameterAsFileOutput(parameters, self.OUTPUT, context)
        if out:
            with open(out, "w", encoding="utf-8") as f:
                f.write("# HLS access doctor report\n\n" + report.to_markdown(res))
        head, counts = report.summary(res)
        return {self.OUTPUT: out, "SUMMARY": head, **{k.upper(): v for k, v in counts.items()}}
