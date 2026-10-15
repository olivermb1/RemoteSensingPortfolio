"""Smoke-test the QGIS Processing script outside QGIS, with stubbed qgis modules.

Needs GDAL Python bindings. Usage: python tests/qgis_smoke.py nakuru_s2_30m.tif OUT_DIR
"""
import os, sys, types, importlib.util
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
qgis = types.ModuleType("qgis"); core = types.ModuleType("qgis.core")
pyqt = types.ModuleType("qgis.PyQt"); qtcore = types.ModuleType("qgis.PyQt.QtCore")
class Base:
    def __init__(self, *a, **k): pass
for n in ["QgsProcessingAlgorithm","QgsProcessingParameterBoolean","QgsProcessingParameterEnum",
          "QgsProcessingParameterExtent","QgsProcessingParameterFolderDestination","QgsProcessingParameterRasterLayer",
          "QgsProcessingParameterString"]:
    setattr(core, n, type(n, (Base,), {}))
class Num(Base):
    Double, Integer = 1, 0
core.QgsProcessingParameterNumber = Num
core.QgsProcessingException = Exception
class QCA:
    @staticmethod
    def translate(c, s): return s
qtcore.QCoreApplication = QCA
sys.modules.update({"qgis": qgis, "qgis.core": core, "qgis.PyQt": pyqt, "qgis.PyQt.QtCore": qtcore})

class Crs:
    def __init__(s, geo): s.geo = geo
    def isGeographic(s): return s.geo
    def __eq__(s, o): return s.geo == o.geo
class Layer:
    def __init__(s, path, geo, name): s.p, s.g, s.n = path, geo, name
    def source(s): return s.p
    def crs(s): return Crs(s.g)
    def name(s): return s.n

spec = importlib.util.spec_from_file_location("cs", os.path.join(ROOT, "qgis", "classspectra_processing.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
alg = m.ClassSpectraAlgorithm()
D = os.path.join(ROOT, "demo", "data") + os.sep
img = sys.argv[1]; out = sys.argv[2]
P = {"IMAGE": Layer(D + img, False, img), "LANDCOVER": Layer(D + "worldcover_2021_v200.tif", True, "WorldCover 2021"),
     "LEGEND": 0, "PRESET": 0, "SCALE": 0.0, "OFFSET": 0.0, "MASK": Layer(D + "nakuru_s2_scl.tif", False, "SCL"),
     "MASK_INVALID": "0,1,3,8,9,10,11", "MASK_BITS": 0, "EXTENT": None, "EROSION": 1, "PURITY": 0.75,
     "OUTLIER_Z": 3.5, "MIN_PIXELS": 30, "SEPARABILITY": True, "OUTPUT_FOLDER": out}
g = lambda p, k, c, *a: P[k]
for fn in ["parameterAsRasterLayer","parameterAsEnum","parameterAsString","parameterAsDouble","parameterAsInt","parameterAsBool","parameterAsExtent"]:
    setattr(alg, fn, g)
class FB:
    def pushInfo(s, t): print(t)
    def setProgress(s, p): pass
print(alg.processAlgorithm(P, None, FB()))
