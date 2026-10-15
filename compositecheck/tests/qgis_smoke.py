"""Smoke-test the QGIS Processing script outside QGIS, with stubbed qgis modules.

Needs GDAL Python bindings (osgeo) and numpy, as QGIS has. Runs the demo's
closest-date composite through the script's own code path.
Usage: python tests/qgis_smoke.py OUT_DIR [--geomad]
"""
import importlib.util
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
qgis = types.ModuleType("qgis")
core = types.ModuleType("qgis.core")
pyqt = types.ModuleType("qgis.PyQt")
qtcore = types.ModuleType("qgis.PyQt.QtCore")


class Base:
    def __init__(self, *a, **k):
        pass


class Alg(Base):
    def addParameter(self, p):
        self.__dict__.setdefault("params", []).append(p)


core.QgsProcessingAlgorithm = Alg
for n in ["QgsProcessingParameterEnum", "QgsProcessingParameterExtent",
          "QgsProcessingParameterFolderDestination", "QgsProcessingParameterRasterDestination",
          "QgsProcessingParameterRasterLayer", "QgsProcessingParameterString", "QgsCoordinateReferenceSystem"]:
    setattr(core, n, type(n, (Base,), {}))
core.QgsProcessingParameterNumber = type("Num", (Base,), {"Integer": 0, "Double": 1})
core.QgsProcessingParameterFile = type("File", (Base,), {"File": 0, "Folder": 1})
core.Qgis = types.SimpleNamespace()  # no scoped enums: exercises the QGIS 3.x fallback
core.QgsProcessingException = Exception


class QCA:
    @staticmethod
    def translate(c, s):
        return s


qtcore.QCoreApplication = QCA
sys.modules.update({"qgis": qgis, "qgis.core": core, "qgis.PyQt": pyqt, "qgis.PyQt.QtCore": qtcore})


class Layer:
    def __init__(self, path):
        self.p = path

    def source(self):
        return self.p


spec = importlib.util.spec_from_file_location("cc", os.path.join(ROOT, "qgis", "compositecheck_processing.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
alg = m.CompositeCheckAlgorithm()
alg.initAlgorithm()
print(len(alg.params), "parameters declared")
D = os.path.join(ROOT, "demo", "data")
out = sys.argv[1]
geomad = "--geomad" in sys.argv
P = {"MANIFEST": os.path.join(D, "manifest.csv"), "HLS_FOLDER": "", "START": "2024-01-01", "END": "2024-06-30",
     "TARGET": "2024-03-31", "METHOD": 2, "COMPOSITE": Layer(os.path.join(D, "geomad_2024H1.tif")) if geomad else None,
     "COMPOSITE_BANDS": "1,2,3,4,5,6", "EXTENT": None, "SENSORS": "S" if geomad else "",
     "FMASK_BITS": "0,1,2,3", "DILATE": 1, "DOMINANCE": 0.5, "PAIR_DAYS": 1,
     "QA_LAYERS": os.path.join(out, "qa_layers.tif"), "COMPOSITE_OUT": os.path.join(out, "composite.tif"),
     "OUTPUT_FOLDER": out}
g = lambda p, k, c, *a: P[k]  # noqa: E731
for fn in ["parameterAsFile", "parameterAsString", "parameterAsEnum", "parameterAsInt", "parameterAsDouble",
           "parameterAsRasterLayer", "parameterAsExtent", "parameterAsOutputLayer"]:
    setattr(alg, fn, g)


class FB:
    def pushInfo(self, t):
        print(t)

    def setProgress(self, p):
        pass


os.makedirs(out, exist_ok=True)
print(alg.processAlgorithm(P, None, FB()))
