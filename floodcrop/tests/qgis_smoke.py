"""Smoke-test the QGIS Processing script outside QGIS, with stubbed qgis modules.

Needs GDAL Python bindings (osgeo) and numpy, as QGIS has; NOT rasterio, so
this also checks the GDAL-only code path. Runs the demo's main Sentinel-1 case
and compares the per-zone hectares with the rasterio CLI output.
Usage: python3.12 tests/qgis_smoke.py OUT_DIR
"""
import csv
import importlib.util
import os
import sys
import types

from osgeo import ogr

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
mods = {n: types.ModuleType(n) for n in ["qgis", "qgis.core", "qgis.PyQt", "qgis.PyQt.QtCore"]}
core = mods["qgis.core"]


class Base:
    def __init__(self, *a, **k):
        self.a = a


class Alg(Base):
    def addParameter(self, p):
        self.__dict__.setdefault("params", []).append(p)


core.QgsProcessingAlgorithm = Alg
for n in ["QgsProcessingParameterEnum", "QgsProcessingParameterFeatureSink", "QgsProcessingParameterFeatureSource",
          "QgsProcessingParameterField", "QgsProcessingParameterFolderDestination", "QgsProcessingParameterBoolean",
          "QgsProcessingParameterMultipleLayers", "QgsProcessingParameterRasterLayer"]:
    setattr(core, n, type(n, (Base,), {}))
core.QgsProcessingParameterNumber = type("Num", (Base,), {"Integer": 0, "Double": 1})
core.QgsProcessing = types.SimpleNamespace(TypeRaster=3, TypeVectorPolygon=2)
core.Qgis = types.SimpleNamespace()  # no scoped enums: exercises the QGIS 3.x fallback
core.QgsProcessingException = Exception
core.QgsFeatureSink = types.SimpleNamespace(FastInsert=2)


class Field:
    def __init__(self, name, t=None):
        self._n = name

    def name(self):
        return self._n


class Fields(list):
    def __init__(self, other=None):
        super().__init__(other or [])

    def append(self, f):
        super().append(f)


class Feature:
    def __init__(self, fields=None):
        self.attrs, self.geom = [], None

    def setGeometry(self, g):
        self.geom = g

    def setAttributes(self, a):
        self.attrs = a


core.QgsField, core.QgsFields, core.QgsFeature = Field, Fields, Feature
mods["qgis.PyQt.QtCore"].QCoreApplication = type("Q", (), {"translate": staticmethod(lambda c, s: s)})
mods["qgis.PyQt.QtCore"].QVariant = types.SimpleNamespace(Double=6, String=10)
sys.modules.update(mods)


class Geom:
    def __init__(self, wkt):
        self.wkt = wkt

    def asWkt(self):
        return self.wkt


class QF:
    def __init__(self, f, names):
        self.f, self.names = f, names

    def __getitem__(self, k):
        return self.f.GetField(k)

    def geometry(self):
        return Geom(self.f.GetGeometryRef().ExportToWkt())

    def attributes(self):
        return [self.f.GetField(n) for n in self.names]


class Source:
    def __init__(self, path):
        self.ds = ogr.Open(path)
        lyr = self.ds.GetLayer(0)
        d = lyr.GetLayerDefn()
        self.names = [d.GetFieldDefn(i).GetName() for i in range(d.GetFieldCount())]
        self.feats = [QF(f, self.names) for f in lyr]

    def getFeatures(self):
        return self.feats

    def fields(self):
        return Fields([Field(n) for n in self.names])

    def sourceCrs(self):
        return types.SimpleNamespace(toWkt=lambda: "EPSG:4326")

    def wkbType(self):
        return 6


class Sink:
    def __init__(self):
        self.feats = []

    def addFeature(self, f, flag=None):
        self.feats.append(f)


class Layer:
    def __init__(self, p):
        self.p = p

    def source(self):
        return self.p


spec = importlib.util.spec_from_file_location("fc", os.path.join(ROOT, "qgis", "floodcrop_processing.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
alg = m.FloodCropAlgorithm()
alg.initAlgorithm()
print(len(alg.params), "parameters declared")

D = os.path.join(ROOT, "demo", "data")
out = sys.argv[1]
sink = Sink()
P = {"SOURCE": 1, "EVENT": [Layer(f"{D}/s1/S1_VV_20240506.tif")],
     "BASELINE": [Layer(f"{D}/s1/S1_VV_20240224.tif"), Layer(f"{D}/s1/S1_VV_20240307.tif")],
     "CROPLAND": Layer(f"{D}/deafrica_cropmask_2019.tif"), "PRESET": 1, "ZONES": Source(f"{D}/zones_subcounties.geojson"),
     "NAME_FIELD": "name", "PERMANENT": Layer(f"{D}/wofs_alltime_frequency.tif"), "PERM_T": 0.8,
     "EVENT_CLOUDS": [], "BASE_CLOUDS": [], "FMASK": False, "SCALE": 1.0, "CHANGE": True, "SAR_T": 0.0,
     "DROP": 3.0, "LOOSE": -14.0, "SMOOTH": 5, "FOLDER": out}
g = lambda p, k, c, *a: P[k]  # noqa: E731
for fn in ["parameterAsEnum", "parameterAsLayerList", "parameterAsRasterLayer", "parameterAsString", "parameterAsBool",
           "parameterAsSource", "parameterAsDouble", "parameterAsInt"]:
    setattr(alg, fn, g)
alg.parameterAsSink = lambda *a: (sink, "memory:out")


class FB:
    def pushInfo(self, t):
        print(t)


r = alg.processAlgorithm({}, None, FB())
print(r, len(sink.feats), "features written")
ref = os.path.join(ROOT, "demo", "output_sar_deafrica", "summary.csv")
if os.path.exists(ref):
    a = {x["zone"]: float(x["flooded_crop_ha"]) for x in csv.DictReader(open(ref))}
    b = {x["zone"]: float(x["flooded_crop_ha"]) for x in csv.DictReader(open(os.path.join(out, "summary.csv")))}
    worst = max(abs(a[k] - b[k]) for k in a)
    print("max per-zone difference vs rasterio CLI:", round(worst, 2), "ha")
    for k in sorted(a, key=lambda k: -a[k])[:4]:
        print(f"  {k:<16} rasterio {a[k]:8.1f}  gdal {b[k]:8.1f}")
