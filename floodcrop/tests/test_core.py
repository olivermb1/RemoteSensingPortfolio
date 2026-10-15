"""Unit tests: python -m pytest tests/ (needs numpy; the end-to-end test needs rasterio)."""
import itertools
import json
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from floodcrop import core  # noqa: E402


def test_decode_dswx():
    a = np.array([0, 1, 2, 252, 253, 254, 255, 250, 251])
    assert core.decode_dswx(a).tolist() == [0, 1, 2, 255, 255, 3, 255, 255, 255]


def test_dswe_table_covers_all_codes_once():
    sets = [core._HIGH, core._MOD, core._PSW_CONS, core._PSW_AGGR]
    not_water = {0, 1, 10, 100, 1000}
    allc = {int("".join(map(str, bits))) for bits in itertools.product([0, 1], repeat=5)}
    seen = set()
    for s in sets + [not_water]:
        assert not (seen & s)
        seen |= s
    assert seen == allc


def test_dswx_tests_water_and_land():
    # clear deep water vs green vegetation vs bare soil, reflectance x 10000
    blue = np.array([600, 400, 1200]); green = np.array([700, 800, 1500]); red = np.array([500, 500, 1900])
    nir = np.array([200, 3500, 2500]); sw1 = np.array([100, 1800, 3200]); sw2 = np.array([50, 900, 2800])
    code, cls = core.dswx_hls_tests(blue, green, red, nir, sw1, sw2)
    assert cls[0] == 1 and code[0] == 11111
    assert cls[1] == 0 and cls[2] == 0
    # same water pixel given as 0-1 floats with scale
    _, cls2 = core.dswx_hls_tests(blue / 1e4, green / 1e4, red / 1e4, nir / 1e4, sw1 / 1e4, sw2 / 1e4, scale=1e4)
    assert (cls2 == cls).all()


def test_optical_water_invalid():
    one = np.ones(2)
    out = core.optical_water(600 * one, 700 * one, 500 * one, 200 * one, 100 * one, 50 * one, invalid=np.array([False, True]))
    assert out.tolist() == [core.WATER, core.NODATA]


def test_combine():
    W, D, P, N = core.WATER, core.DRY, core.PARTIAL, core.NODATA
    a = np.array([W, D, N, P, D, N])
    b = np.array([D, D, N, D, P, W])
    c = np.array([N, D, N, D, D, W])
    assert core.combine([a, b, c], "any").tolist() == [W, D, N, P, P, W]
    assert core.combine([a, b, c], "majority").tolist() == [D, D, N, D, D, W]


def test_flood_classes():
    W, D, P, N = core.WATER, core.DRY, core.PARTIAL, core.NODATA
    ev = np.array([W, W, P, D, N, W, W])
    bl = np.array([D, W, D, D, D, N, D])
    perm = np.array([0, 0, 0, 0, 0, 0, 1], bool)
    f = core.flood_classes(ev, bl, perm)
    assert f.tolist() == [core.F_NEW_WATER, core.F_STANDING, core.F_NEW_PARTIAL, core.F_DRY,
                          core.F_UNOBSERVED, core.F_NEW_WATER, core.F_STANDING]


def test_pixel_area_geographic():
    # 1 x 1 degree cell at the equator: 12,308.8 km2 on WGS84
    a = core.pixel_area_m2((1.0, 0, 34.0, 0, -1.0, 0.5), (1, 1), True)
    assert a[0, 0] / 1e6 == pytest.approx(12308.8, rel=1e-4)
    # rows sum to the band area regardless of how finely it is cut
    fine = core.pixel_area_m2((0.0002, 0, 34.0, 0, -0.0002, 0.5), (5000, 1), True)
    assert fine.sum() * 5000 == pytest.approx(a[0, 0], rel=1e-9)
    assert core.pixel_area_m2((30, 0, 0, 0, -30, 0), (3, 3), False) == 900


def test_otsu_bimodal():
    rng = np.random.default_rng(0)
    v = np.concatenate([rng.normal(-22, 1, 5000), rng.normal(-8, 1.5, 20000)])
    t = core.otsu(v)
    assert -20 < t < -12


def test_boxcar_matches_naive():
    rng = np.random.default_rng(1)
    a = rng.normal(size=(9, 11)).astype(np.float32)
    a[3, 4] = np.nan
    k = 3
    out = core.boxcar(a, k)
    p = np.pad(a, 1, constant_values=np.nan)
    for i in range(9):
        for j in range(11):
            if np.isnan(a[i, j]):
                assert np.isnan(out[i, j])
            else:
                assert out[i, j] == pytest.approx(np.nanmean(p[i:i + k, j:j + k]), abs=1e-5)


def test_sar_change_water():
    ev = np.full((20, 20), -9.0, np.float32)
    bl = np.full((20, 20), -9.0, np.float32)
    ev[2:8, 2:8] = -16.0  # dropped 7 dB, below loose -14 -> water by the change rule
    ev[12:18, 12:18] = -24.0  # dark -> water by the absolute threshold
    out = core.sar_change_water(ev, bl, threshold=-18, drop_db=3, loose_db=-14, smooth=1)
    assert out[4, 4] == core.WATER and out[14, 14] == core.WATER and out[0, 19] == core.DRY
    only_t = core.sar_water(ev, -18, smooth=1)
    assert only_t[4, 4] == core.DRY and only_t[14, 14] == core.WATER


def test_zone_summary():
    flood = np.array([[1, 1, 0, 255], [2, 3, 0, 0]], np.uint8)
    crop = np.array([[1, 0.5, 1, 1], [1, 1, np.nan, 0]], np.float32)
    area = 1e4  # 1 ha pixels
    r = core.zone_summary(flood, crop, area, np.ones(flood.shape, bool))
    assert r["zone_ha"] == 8 and r["crop_ha"] == 5.5
    assert r["flooded_crop_ha"] == 1.5 and r["flooded_crop_partial_ha"] == 1
    assert r["crop_observed_pct"] == pytest.approx(100 * 4.5 / 5.5)
    assert r["flooded_crop_pct"] == pytest.approx(100 * 1.5 / 4.5)
    assert r["flooded_all_ha"] == 2 and r["standing_water_crop_ha"] == 1


def test_end_to_end_dswx(tmp_path):
    """Synthetic DSWx + 10 m cropland + two zones -> exact hectares."""
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin
    from floodcrop import pipeline
    crs = "EPSG:32736"
    prof = dict(driver="GTiff", width=10, height=10, count=1, dtype="uint8", crs=crs,
                transform=from_origin(500000, 9990000, 30, 30))
    ev = np.zeros((10, 10), np.uint8)
    ev[:, :4] = 1          # 40 pixels water at the event
    ev[0, 9] = 253         # cloud
    bl = np.zeros((10, 10), np.uint8)
    bl[:, 0] = 1           # column 0 was already water
    for name, arr in (("ev.tif", ev), ("bl.tif", bl)):
        with rasterio.open(tmp_path / name, "w", **prof) as d:
            d.write(arr, 1)
    crop = np.zeros((30, 30), np.uint8)
    crop[:, 3:6] = 40      # 10 m columns 3-5 = left third of 30 m column 1 is cropland... (exactly 30 m col 1)
    with rasterio.open(tmp_path / "crop.tif", "w", **dict(prof, width=30, height=30,
                                                          transform=from_origin(500000, 9990000, 10, 10))) as d:
        d.write(crop, 1)
    # zone A = left half (30 m cols 0-4), zone B = right half
    def sq(x0, x1):
        return {"type": "Polygon", "coordinates": [[[x0, 9990000], [x1, 9990000], [x1, 9989700], [x0, 9989700], [x0, 9990000]]]}
    fc = {"type": "FeatureCollection", "crs": {"type": "name", "properties": {"name": crs}},
          "features": [{"type": "Feature", "properties": {"name": "A"}, "geometry": sq(500000, 500150)},
                       {"type": "Feature", "properties": {"name": "B"}, "geometry": sq(500150, 500300)}]}
    (tmp_path / "z.geojson").write_text(json.dumps(fc))
    res = pipeline.run("dswx", [str(tmp_path / "ev.tif")], [str(tmp_path / "bl.tif")], str(tmp_path / "crop.tif"),
                       "worldcover", str(tmp_path / "z.geojson"), out_dir=str(tmp_path / "out"))
    rows = {r["zone"]: r for r in res["rows"]}
    px_ha = 0.09
    # cropland = 30 m column 1 (10 pixels) fully; it is flooded and was dry before
    assert rows["A"]["crop_ha"] == pytest.approx(10 * px_ha)
    assert rows["A"]["flooded_crop_ha"] == pytest.approx(10 * px_ha)
    assert rows["A"]["flooded_all_ha"] == pytest.approx(30 * px_ha)  # cols 1-3 new; col 0 was water
    assert rows["B"]["flooded_all_ha"] == 0 and rows["B"]["observed_pct"] == pytest.approx(98.0)
    assert (tmp_path / "out" / "flood_classes.tif").exists()


def test_fetch_tile_helpers():
    pytest.importorskip("pyproj")
    from floodcrop import fetch
    bbox = (34.70, -0.42, 35.20, -0.05)
    assert fetch.s1_tiles(bbox) == ["S01E034", "S01E035"]
    assert fetch.dea_tiles(bbox) == ["x215y076", "x216y076"]
    assert fetch.worldcover_tiles(bbox)[0].endswith("ESA_WorldCover_10m_2021_v200_S03E033_Map.tif")
    assert fetch.s1_tiles((33.9, 0.1, 34.1, 0.3)) == ["N00E033", "N00E034"]
