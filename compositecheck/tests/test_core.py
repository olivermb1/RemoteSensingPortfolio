"""Synthetic tests for the maths and the HLS file finder. Run: python -m pytest tests/ (or python tests/test_core.py)."""
import os
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from compositecheck import catalog, core  # noqa: E402
from compositecheck.sensors import COMMON_BANDS  # noqa: E402

BASE = np.array([0.04, 0.07, 0.06, 0.30, 0.20, 0.10])  # a vegetated pixel, blue..swir2


def make_stack(dates, sensors, h=20, w=20, seed=0, clear=None):
    rng = np.random.default_rng(seed)
    T = len(dates)
    refl = BASE[None, :, None, None] + rng.normal(0, 0.003, (T, 6, h, w))
    stack = core.Stack(
        refl=np.round(refl * 10000).astype("int16"),
        clear=np.ones((T, h, w), bool) if clear is None else clear,
        dates=np.array([np.datetime64(d) for d in dates]), sensors=list(sensors),
        ids=[f"{s}_{d}" for s, d in zip(sensors, dates)], band_names=list(COMMON_BANDS))
    return stack


def test_fmask_bits():
    fm = np.array([0, 2, 4, 8, 16, 32, 64 | 128, 255], "uint8")
    assert core.fmask_clear(fm).tolist() == [True, False, False, False, True, True, True, False]
    assert core.fmask_clear(fm, bits=(1, 2, 3, 4)).tolist()[4] is False
    assert core.fmask_aerosol_high(fm).tolist() == [False] * 6 + [True, False]


def test_count_and_gap():
    dates = np.array(["2024-01-10", "2024-01-20", "2024-03-01"], "datetime64[D]")
    clear = np.zeros((3, 1, 3), bool)
    clear[:, 0, 0] = True           # all three
    clear[0, 0, 1] = True           # only the first
    # pixel 2: never clear
    assert core.clear_count(clear)[0].tolist() == [3, 1, 0]
    gap = core.max_gap_days(clear, dates, "2024-01-01", "2024-03-31")[0]
    assert gap[0] == 41             # 20 Jan -> 1 Mar
    assert gap[1] == 81             # 10 Jan -> 31 Mar
    assert gap[2] == 90             # whole period


def test_closest_date_and_doyd():
    s = make_stack(["2024-03-01", "2024-03-28", "2024-04-20"], ["S2A", "L8", "S2B"])
    s.clear[1, :5] = False          # the closest scene is cloudy in the top rows
    idx = core.closest_to_date(s, "2024-03-31")
    assert (idx[5:] == 1).all() and (idx[:5] == 2).all()   # 20 Apr (20 d) beats 1 Mar (30 d)
    doy, doyd = core.selection_dates(idx, s.dates, "2024-03-31")
    assert doyd[10, 0] == 3 and doyd[0, 0] == 20
    assert doy[10, 0] == 88         # 28 Mar 2024 (leap year)


def test_dominance():
    d = core.dominance([0.8, 0.2, 0.0])
    assert d["dominated"] and d["top_scene_index"] == 0
    assert abs(d["effective_scenes"] - 1 / 0.68) < 1e-9
    d = core.dominance([0.25] * 4)
    assert not d["dominated"] and abs(d["effective_scenes"] - 4) < 1e-9


def test_outlier_screen_flags_haze():
    dates = [f"2024-0{1 + i // 3}-{1 + 9 * (i % 3):02d}" for i in range(9)]
    s = make_stack(dates, ["S2A"] * 9)
    s.refl[4, :3] += 400            # +0.04 reflectance in blue, green, red: a hazy scene
    med, mad = core.robust_stats(s)
    share, zblue, outlier = core.scene_outliers(s, med, mad)
    assert share[4] > 0.9 and zblue[4] > 3
    assert np.nanmax(np.delete(share, 4)) < 0.05
    rows = core.scene_table(s, core.scene_contribution(np.full((20, 20), 4), 9), share, zblue)
    assert rows[4]["suspect"] and not rows[0]["suspect"]


def test_medoid_avoids_the_hazy_scene():
    dates = [f"2024-02-{d:02d}" for d in range(1, 10)]
    s = make_stack(dates, ["S2A"] * 9)
    s.refl[0, :3] += 400
    comp, idx, exact = core.build_composite(s, "medoid")
    assert exact and not (idx == 0).any()
    comp_t, idx_t, _ = core.build_composite(s, "target", "2024-02-01")
    assert (idx_t == 0).all()       # closest-date picks the hazy one


def test_pairs_and_envelope():
    s = make_stack(["2024-03-01", "2024-03-01", "2024-03-10"], ["L9", "S2B", "S2A"], h=40, w=40)
    s.refl[1] = s.refl[0]           # identical same-day pair
    s.refl[2] = np.round(s.refl[0] * 1.10).astype("int16")  # 10% brighter, but 9 days apart
    rows = core.near_coincident_pairs(s, max_days=1, min_pixels=100)
    assert len(rows) == 1 and rows[0]["within_envelope"] and rows[0]["red_rel_diff"] == 0
    rows = core.near_coincident_pairs(s, max_days=10, min_pixels=100)
    bad = [r for r in rows if r["sentinel2"].startswith("S2A")][0]
    assert not bad["within_envelope"] and abs(bad["red_bias"] - 0.0953) < 0.01
    assert abs(bad["red_gain"] - 1.10) < 0.02


def test_run_checks_end_to_end():
    dates = [f"2024-{m:02d}-{d:02d}" for m in (1, 2, 3) for d in (3, 13, 23)]
    sensors = ["L8" if i % 3 == 0 else "S2A" for i in range(9)]
    s = make_stack(dates, sensors)
    layers, comp, rep, scenes = core.run_checks(s, "2024-01-01", "2024-03-31", "2024-02-15")
    assert layers["nclear"].max() == 9 and rep["pixels_with_no_clear_obs"] == 0
    assert comp.shape == (6, 20, 20) and np.isfinite(comp).all()
    assert len(scenes) == 9 and rep["dominance"]["scenes_used"] >= 1


def test_hls_file_finder():
    with tempfile.TemporaryDirectory() as d:
        names = {"S30": ["B02", "B03", "B04", "B8A", "B11", "B12", "Fmask", "B01"],
                 "L30": ["B02", "B03", "B04", "B05", "B06", "B07", "Fmask"]}
        for prod, bands in names.items():
            for b in bands:
                open(os.path.join(d, f"HLS.{prod}.T36MZE.2024092T075619.v2.0.{b}.tif"), "w").close()
        # incomplete granule is skipped
        open(os.path.join(d, "HLS.S30.T36MZE.2024095T075619.v2.0.B02.tif"), "w").close()
        scenes = catalog.hls_scenes(d)
        assert len(scenes) == 2
        s = {x["sensor"]: x for x in scenes}
        assert str(s["S30"]["date"]) == "2024-04-01"   # day 92 of 2024
        assert s["S30"]["bands"][3][0].endswith(".B8A.tif") and s["L30"]["bands"][3][0].endswith(".B05.tif")
        assert s["L30"]["fmask"].endswith(".Fmask.tif")
        kept = catalog.filter_scenes(scenes, sensors=["L"])
        assert [x["sensor"] for x in kept] == ["L30"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
