"""Smoke-test both QGIS Processing scripts outside QGIS, with stubbed qgis modules.

Needs GDAL Python bindings, numpy and scipy (what QGIS ships). Usage:
  python tests/qgis_smoke.py OUT_DIR
Runs 'Drought maps and events' then 'Greenness link' on demo/data.
"""
import importlib.util, os, sys, types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
qgis = types.ModuleType("qgis"); core = types.ModuleType("qgis.core")
pyqt = types.ModuleType("qgis.PyQt"); qtcore = types.ModuleType("qgis.PyQt.QtCore")


class Base:
    def __init__(self, *a, **k): pass


core.QgsProcessingAlgorithm = type("Alg", (), {"addParameter": lambda self, p: None})
for n in ["QgsProcessingParameterEnum", "QgsProcessingParameterFolderDestination",
          "QgsProcessingParameterRasterLayer", "QgsProcessingParameterString"]:
    setattr(core, n, type(n, (Base,), {}))
core.QgsProcessingParameterNumber = type("Num", (Base,), {"Double": 1, "Integer": 0})
core.QgsProcessingParameterFile = type("File", (Base,), {"Folder": 1})
core.QgsProcessingException = Exception
core.Qgis = type("Qgis", (), {})
qtcore.QCoreApplication = type("QCA", (), {"translate": staticmethod(lambda c, s: s)})
sys.modules.update({"qgis": qgis, "qgis.core": core, "qgis.PyQt": pyqt, "qgis.PyQt.QtCore": qtcore})


class Layer:
    def __init__(s, path): s.p = path
    def source(s): return s.p


class FB:
    def pushInfo(s, t): print("  " + t)


def load(fname, cls):
    spec = importlib.util.spec_from_file_location(fname, os.path.join(ROOT, "qgis", fname))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return getattr(m, cls)()


def run(alg, P):
    g = lambda p, k, c, *a: P[k]
    for fn in ["parameterAsRasterLayer", "parameterAsEnum", "parameterAsString", "parameterAsDouble", "parameterAsInt"]:
        setattr(alg, fn, g)
    alg.initAlgorithm()
    return alg.processAlgorithm(P, None, FB())


D = os.path.join(ROOT, "demo", "data")
out = sys.argv[1]
print("Drought maps and events")
r = run(load("droughtcheck_processing.py", "DroughtCheckAlgorithm"),
        {"PRECIP": Layer(os.path.join(D, "chirps_monthly.tif")), "TEMPS": Layer(os.path.join(D, "power_tmax_tmin.tif")),
         "PET": None, "SCALES": "1,3,6,12", "SPEI_SCALES": "3,6,12", "CAL_START": 1991, "CAL_END": 2020,
         "CLASS_SCALE": 3, "THRESHOLD": -1.0, "MIN_DURATION": 2, "EVENTS_SINCE": "2000-01", "BACKEND": 0,
         "OUTPUT_FOLDER": os.path.join(out, "drought")})
print("Greenness link")
run(load("greenness_link_processing.py", "GreennessLinkAlgorithm"),
    {"NDVI": Layer(os.path.join(D, "ndvi_anomaly_240m.tif")), "CLEAR": Layer(os.path.join(D, "ndvi_anomaly_240m_clear.tif")),
     "DROUGHT_DIR": r["OUTPUT_FOLDER"], "LANDCOVER": Layer(os.path.join(D, "worldcover_2021_240m.tif")), "LEGEND": 0,
     "TARGET": "", "SCALE": "auto", "LAG": "auto", "RECENT": 12, "MIN_PIXELS": 50,
     "OUTPUT_FOLDER": os.path.join(out, "greenness")})
print("ok")
