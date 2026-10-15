"""pytest tests/ -q   (from the tool folder)"""

import json
import os
import sys
from datetime import datetime

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ecogeocheck import core, flags, known_issues, names, shift  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DEMO = os.path.join(os.path.dirname(HERE), "demo", "data")


def test_names():
    a = names.parse("ECOv002_L2T_LSTE_33138_005_37MBU_20240505T081052_0712_01_LST.tif")
    assert (a["orbit"], a["scene"], a["tile"], a["layer"], a["product"]) == (33138, 5, "37MBU", "LST", "L2T_LSTE")
    g = names.parse("ECOv002_L1B_GEO_33138_005_20240505T081052_0712_01.h5")
    assert names.scene_key(g) == names.scene_key(a) and names.is_geo_file(g) and g["tile"] is None
    v1 = names.parse("ECOSTRESS_L1B_GEO_05542_007_20190706T143255_0601_01.h5")
    assert v1["collection"] == 1 and v1["orbit"] == 5542
    e = names.parse("ECOv002_L2T_LSTE_33138_005_37MBU_20240505T081052_0712_01_LST_err.tif")
    assert e["layer"] == "LST_err"
    ap = names.parse("ECO_L2T_LSTE.002_LST_doy2024126081052_aid0001_37N.tif")
    assert ap["orbit"] is None and ap["time"] == datetime(2024, 5, 5, 8, 10, 52) and ap["layer"] == "LST"
    assert names.parse("random.tif") is None


def test_flag_normalising():
    assert flags.norm_qa(b"Best") == "best" and flags.norm_qa("SUSPECT ") == "suspect"
    assert flags.norm_qa("No Match") == "poor" and flags.norm_qa("whatever") is None
    assert flags.norm_bool("False") is False and flags.norm_bool(np.bytes_("True")) is True
    r = flags.from_tags({"L1GEOMetadata_GeolocationAccuracyQA": "Good",
                         "L1GEOMetadata_GeolocationAccuracyQAExplanation": "nearby scene",
                         "StandardMetadata_FieldOfViewObstruction": "False"})
    assert r["geo_qa"] == "good" and r["geo_qa_note"] == "nearby scene" and r["fov_obstruction"] is False
    u = flags.from_umm({"AdditionalAttributes": [{"Name": "GeolocationAccuracyQA", "Values": ["Poor"]}]})
    assert u["geo_qa"] == "poor"
    assert flags.from_tags({"unrelated": "x"}) is None


def test_hdf5(tmp_path):
    h5py = pytest.importorskip("h5py")
    p = tmp_path / "ECOv002_L1B_GEO_00001_001_20250101T000000_0712_01.h5"
    with h5py.File(p, "w") as f:
        f.create_group("L1GEOMetadata")["GeolocationAccuracyQA"] = np.bytes_("Suspect")
        f["L1GEOMetadata"]["OrbitCorrectionPerformed"] = np.bytes_("False")
    r = flags.from_hdf5(str(p))
    assert r["geo_qa"] == "suspect" and r["orbit_corrected"] is False


@pytest.mark.parametrize("text,delim", [
    ("Orbit,Scene,GeolocationAccuracyQA\n100,1,Best\n100,2,Poor\n", ","),
    ("orbit\tscene\tflag\n100\t1\tBest\n100\t2\tPoor\n", "\t"),
    ("100 001 2025-01-01T10:00:00 Best\n100 002 2025-01-01T10:01:00 Poor\n", " "),
    ("granule|geo_qa\nECOv002_L1B_GEO_00100_001_20250101T100000_0712_01|best\n"
     "ECOv002_L1B_GEO_00100_002_20250101T100100_0712_01|poor\n", "|"),
])
def test_summary_table(tmp_path, text, delim):
    p = tmp_path / "s.txt"
    p.write_text(text)
    t, desc = flags.read_summary(str(p))
    assert t[(100, 1)]["geo_qa"] == "best" and t[(100, 2)]["geo_qa"] == "poor", desc


def test_known_issues():
    assert any(l == "caution" for l, _ in known_issues.check(datetime(2025, 6, 1)))
    assert known_issues.check(datetime(2025, 9, 1)) == []
    assert known_issues.check(datetime(2025, 9, 1), True)[0][0] == "caution"
    assert known_issues.check(datetime(2024, 1, 1), True)[-1][0] == "note"


def _scene(rng, shape=(300, 260)):
    yy, xx = np.mgrid[: shape[0], : shape[1]]
    water = (((yy - 120) / 40.0) ** 2 + ((xx - 100) / 55.0) ** 2 < 1) | ((xx > 190) & (yy > 200))
    lst = 305 - 8 * water + rng.normal(0, 0.5, shape)
    return water.astype(float), lst


@pytest.mark.parametrize("dy,dx", [(0, 0), (3, -2), (-25, 31), (40, 0)])
def test_shift_recovers_offset(dy, dx):
    rng = np.random.default_rng(1)
    water, lst = _scene(rng)
    moved = np.roll(np.roll(lst, dy, 0), dx, 1)
    valid = np.ones_like(lst, bool)
    valid[rng.random(lst.shape) < 0.1] = False  # scattered cloud
    r = shift.measure(water, np.ones_like(water, bool), moved, valid, max_shift=60)
    assert r["ok"] and abs(r["dy"] - dy) < 0.6 and abs(r["dx"] - dx) < 0.6, r


def test_shift_refuses_featureless():
    rng = np.random.default_rng(2)
    flat = np.zeros((200, 200))
    r = shift.measure(flat, np.ones_like(flat, bool), rng.normal(size=flat.shape), np.ones_like(flat, bool), 40)
    assert not r["ok"]


def test_corrected_geotransform_round_trip():
    gt = (1000.0, 70.0, 0.0, 5000.0, 0.0, -70.0)
    # content sits 2 px east and 3 px south: origin must move 140 m west and 210 m north
    assert shift.corrected_geotransform(gt, 2, 3) == (860.0, 70.0, 0.0, 5210.0, 0.0, -70.0)


def _res(**kw):
    r = {"geo_qa": None, "orbit_corrected": None, "conflict": "", "issues": [], "m_ok": False, "m_why": ""}
    r.update(kw)
    return r


def test_decisions():
    o = dict(core.DEFAULTS)
    assert core.decide(_res(geo_qa="best"), o)["decision"] == "keep"
    assert core.decide(_res(geo_qa="suspect"), o)["decision"] == "drop"
    assert core.decide(_res(orbit_corrected=False), o)["decision"] == "drop"
    assert core.decide(_res(), o)["decision"] == "check"
    m_small = dict(m_ok=True, offset_m=50, dx_m=50, dy_m=0, reference="x")
    m_big = dict(m_ok=True, offset_m=900, dx_m=900, dy_m=0, reference="x")
    assert core.decide(_res(**m_small), o)["decision"] == "keep"
    assert core.decide(_res(geo_qa="best", **m_big), o)["decision"] == "drop"
    assert core.decide(_res(geo_qa="suspect", **m_small), o)["decision"] == "drop"
    assert core.decide(_res(geo_qa="suspect", **m_small), dict(o, rescue=True))["decision"] == "keep"
    assert core.decide(_res(geo_qa="poor", **m_big), dict(o, fix=True))["decision"] == "fixed"
    assert core.decide(_res(geo_qa="best", issues=[("caution", "noisy")]), o)["decision"] == "caution"


@pytest.mark.skipif(not os.path.isdir(os.path.join(DEMO, "scenes")), reason="run demo/make_demo_data.py first")
def test_demo_end_to_end(tmp_path):
    truth = json.load(open(os.path.join(DEMO, "truth.json")))
    res, info = core.run([os.path.join(DEMO, "scenes")], out=str(tmp_path),
                         summary=os.path.join(DEMO, "geolocation_summary_example.txt"), log=lambda *a: None)
    rows = list(res.values())
    assert len(rows) == len(truth) == 12
    for r, t in zip(sorted(rows, key=lambda r: r["time"]), truth):
        assert r["time"] == t["time"]
        assert r["geo_qa"] == t["flag"], (r["time"], r["geo_qa_source"])
        assert r["m_ok"]
        assert abs(r["dx_m"] - t["applied_east_m"]) < 75 and abs(-r["dy_m"] - t["applied_north_m"]) < 75
    assert info["counts"]["drop"] == 4 and os.path.exists(tmp_path / "scenes.geojson")
