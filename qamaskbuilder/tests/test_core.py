import os
import re
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from qamask import core, io, ops  # noqa: E402
from qamask.crsfix import hls_crs_fix, mgrs_tile  # noqa: E402
from qamask.registry import PRODUCTS, detect_product, get_product  # noqa: E402

D = os.path.join(ROOT, "demo", "data")
HLS = os.path.join(D, "HLS.L30.T19JHN.2024279T141847.v2.0.Fmask.tif")
LS = os.path.join(D, "LC08_L2SP_169060_20241104_20241113_02_T1_QA_PIXEL_crop.tif")
CONF = os.path.join(D, "OPERA_L3_DSWx-HLS_T19JHN_20241005T141847Z_L8_30_v1.0_B03_CONF.tif")
WTR = os.path.join(D, "OPERA_L3_DSWx-HLS_T19JHN_20241005T141847Z_L8_30_v1.0_B01_WTR.tif")


def test_registry_is_consistent():
    for p in PRODUCTS.values():
        for f in p.flags.values():
            n = p.fields[f["field"]]["bits"][1]
            assert all(0 <= v < 2 ** n for v in f["in"]), (p.key, f["name"])
        assert p.default_preset in p.presets, p.key


def test_fmask_table_matches_the_files_own_description():
    desc = io.info(HLS).tags["Fmask bit description"]
    p = get_product("hls_fmask")
    for m in re.finditer(r"^(\d)(?:-(\d))?\s+([a-z /]+?):?\s*$", desc, re.M):
        hi, lo = int(m.group(1)), int(m.group(2) or m.group(1))
        name = {"cirrus cloud": "cirrus", "adjacent to cloud": "adjacent", "cloud shadow": "shadow",
                "snow/ice": "snow"}.get(m.group(3).strip(), m.group(3).strip())
        assert p.fields[name]["bits"] == [lo, hi - lo + 1], name


def test_landsat_reference_values():
    # USGS example QA_PIXEL values for Landsat 8/9: clear land, water, high-confidence cloud, fill
    p = get_product("landsat_c2_qa_pixel")
    qa = np.array([[21824, 21952, 22280, 1]], np.uint16)
    m = core.build_mask(qa, p, ["clear"])
    assert m.tolist() == [[1, 1, 0, 255]]
    assert core.build_mask(qa, p, ["clear_land"]).tolist() == [[1, 0, 0, 255]]
    assert core.flag_array(qa, p, "cloud_conf_high").tolist() == [[False, False, True, False]]


def test_fmask_aerosol_and_fill():
    p = get_product("hls_fmask")
    qa = np.array([[0b00000000, 0b11000000, 0b10000000, 0b00000010, 255]], np.uint8)
    assert core.build_mask(qa, p, ["clear"]).tolist() == [[1, 0, 1, 0, 255]]
    assert core.build_mask(qa, p, ["strict"]).tolist() == [[1, 0, 0, 0, 255]]


def test_signed_summary_qa():
    p = get_product("modis_mod13_summary_qa")
    qa = np.array([[-1, 0, 1, 2, 3]], np.int16)
    assert core.build_mask(qa, p).tolist() == [[255, 1, 0, 0, 0]]


def test_keep_and_buffer():
    p = get_product("opera_dswx_hls_wtr")
    qa = np.zeros((7, 7), np.uint8)
    qa[3, 3] = 253
    qa[0, 0] = 1
    m = core.build_mask(qa, p, ["observed"], buffer=1)
    assert m.sum() == 49 - 9 and m[2:5, 2:5].max() == 0
    w = core.build_mask(qa, p, ["observed"], keep=["open_water"])
    assert w[0, 0] == 1 and w.sum() == 1


def test_unknown_flag_is_a_clear_error():
    with pytest.raises(KeyError, match="Flags:"):
        get_product("hls_fmask").resolve(["clouds"])


def test_detect_product():
    assert detect_product(HLS).key == "hls_fmask"
    assert detect_product(LS).key == "landsat_c2_qa_pixel"
    assert detect_product(CONF).key == "opera_dswx_hls_conf"
    assert detect_product(WTR).key == "opera_dswx_hls_wtr"
    assert detect_product("ECOv002_L2T_LSTE_1_QC.tif").key == "ecostress_lste_qc"
    assert detect_product("ECOv002_L2T_LSTE_1_cloud.tif").key == "ecostress_cloud"


@pytest.mark.parametrize("epsg,top,bottom,name,needed", [
    (32619, -2700000, -2809800, "HLS.L30.T19JHN.x.tif", True),
    (32636, 115815, -116715, "LC08_x.tif", False),       # crosses the equator
    (32636, 5000000, 4890000, "HLS.S30.T36TXX.tif", False),
    (32736, 7300000, 7190200, "x.tif", False),          # already southern
    (32620, -2700000, -2809800, "HLS.L30.T19JHN.x.tif", False),  # zone disagrees with the tile id
    (4326, -10, -11, "x.tif", False),
])
def test_crs_fix_decisions(epsg, top, bottom, name, needed):
    assert hls_crs_fix(epsg, top, bottom, name)["needed"] is needed


def test_mgrs_tile():
    assert mgrs_tile("HLS.S30.T36MZE.2024015T074231.v2.0.Fmask.tif") == (36, "M", "ZE")


def test_crs_fix_on_real_hls_keeps_every_pixel_in_place(tmp_path):
    out = str(tmp_path / "fixed.tif")
    r = ops.fix_crs(HLS, out)
    assert r["new_epsg"] == 32719
    a, b = io.info(HLS), io.info(out)
    assert b.epsg == 32719 and b.top == a.top + 10_000_000
    assert (io.read(HLS) == io.read(out)).all()
    try:
        from pyproj import Transformer
    except ImportError:
        pytest.skip("pyproj not installed")
    t1 = Transformer.from_crs(a.epsg, 4326, always_xy=True)
    t2 = Transformer.from_crs(b.epsg, 4326, always_xy=True)
    for x, y in ((a.gt[0], a.top), (a.gt[0] + 30 * a.width, a.bottom)):
        lon1, lat1 = t1.transform(x, y)
        lon2, lat2 = t2.transform(x, y + 10_000_000)
        assert abs(lon1 - lon2) < 1e-9 and abs(lat1 - lat2) < 1e-9


def test_build_writes_mask_style_and_report(tmp_path):
    out = str(tmp_path / "m.tif")
    r = ops.build(LS, out, drop=["clear"])
    assert os.path.exists(out[:-4] + ".qml") and os.path.exists(out[:-4] + ".json")
    m = io.read(out)
    assert set(np.unique(m)) <= {0, 1, 255}
    assert 0.3 < r["mask"]["usable_share_of_valid"] < 0.95
    assert r["crs"]["applied"] is False  # Landsat keeps its northern-zone convention by default


def test_apply_follows_the_crs_fix(tmp_path):
    m = str(tmp_path / "w.tif")
    ops.build(WTR, m)
    out = str(tmp_path / "conf_masked.tif")
    ops.apply(CONF, m, out)
    assert io.info(out).epsg == 32719
    a = io.read(out)
    assert (a[io.read(m) != 1] == 255).all()


def test_ecostress_qc_follows_the_v2_guide():
    # ECOL2 User Guide V2 rev 4.2: QC holds no cloud information in collection 2, fill is 0
    p = get_product("ecostress_lste_qc")
    assert "cloud" not in p.flags
    assert not any("cloud" in flags for flags in p.presets.values())
    with pytest.raises(KeyError):
        p.resolve(["cloud"])
    good = 0b11 << 14 | 0b10 << 12 | 0b01 << 8          # LST < 1 K, emissivity good, nominal opacity
    degraded = good | 0b01                               # mandatory QA 01
    poor_lst = 0b10 << 12 | 0b01 << 8                    # LST accuracy 00 (> 2 K)
    not_produced = good | 0b11
    bad_l1b = good | 0b11 << 2
    qa = np.array([[0, good, degraded, poor_lst, not_produced, bad_l1b]], np.uint16)
    assert core.build_mask(qa, p).tolist() == [[255, 1, 1, 0, 0, 0]]          # default 'accurate'
    assert core.build_mask(qa, p, ["strict"]).tolist() == [[255, 1, 0, 0, 0, 0]]
    assert core.build_mask(qa, p, ["produced"]).tolist() == [[255, 1, 1, 1, 0, 0]]


def test_ecostress_cloud_layer():
    p = get_product("ecostress_cloud")
    assert core.build_mask(np.array([[0, 1, 255]], np.uint8), p).tolist() == [[1, 0, 255]]
    assert detect_product("ECOv002_L2_LSTE_33138_005_20240505T081052_0712_01_cloud_mask.tif").key == "ecostress_cloud"
    assert p.gee["collections"] == ["NASA/ECOSTRESS/L2T_LSTE/V2"]
