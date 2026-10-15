"""Tests: built-in maths against climate-indices and FAO-56, run theory, diagnosis rules.

  python tests/test_indices.py        (or pytest tests/)
Tests that need climate-indices are skipped when it is not installed.
"""
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from droughtcheck import greenness as G  # noqa: E402
from droughtcheck import indices as I  # noqa: E402

HAVE_CI = I._ci() is not None


def _chirps():
    try:
        import rasterio
        with rasterio.open(os.path.join(ROOT, "demo", "data", "chirps_monthly.tif")) as d:
            return d.read().astype(float)
    except Exception:
        rng = np.random.default_rng(0)
        p = rng.gamma(1.2, 60, (480, 6, 6))
        p[rng.random(p.shape) < 0.05] = 0
        return p


def test_spi_matches_climate_indices():
    if not HAVE_CI:
        return print("skip: climate-indices not installed")
    P = _chirps()
    for s in (1, 3, 6, 12):
        a = I.spi(P, s, 1981, backend="climate-indices")
        b = I.spi(P, s, 1981, backend="builtin")
        assert np.array_equal(np.isnan(a), np.isnan(b))
        assert np.nanmax(np.abs(a - b)) < 1e-6, s


def test_spei_matches_climate_indices():
    if not HAVE_CI:
        return print("skip: climate-indices not installed")
    rng = np.random.default_rng(1)
    p = rng.gamma(1.5, 60, (480, 4, 4))
    e = rng.normal(120, 15, (480, 4, 4))
    for s in (1, 3, 6, 12):
        a = I.spei(p, e, s, 1981, backend="climate-indices")
        b = I.spei(p, e, s, 1981, backend="builtin")
        assert np.array_equal(np.isnan(a), np.isnan(b))
        assert np.nanmax(np.abs(a - b)) < 1e-6, s


def test_spi_is_standard_normal_in_calibration():
    rng = np.random.default_rng(2)
    p = rng.gamma(2.0, 40, (12 * 60, 3, 3))
    z = I.spi(p, 3, 1961, (1961, 2020), backend="builtin")
    assert abs(np.nanmean(z)) < 0.05 and abs(np.nanstd(z) - 1) < 0.05


def test_extraterrestrial_radiation_fao56_example8():
    # FAO-56 example 8: 20 deg S on 3 September -> Ra = 32.2 MJ m-2 day-1
    assert abs(I.extraterrestrial_radiation(-20.0, 246) - 32.2) < 0.1


def test_runs():
    z = np.array([0.5, -1.2, -1.5, -0.8, 0.3, -1.1, -1.3, -2.1, np.nan, -1.4])
    ev = I.runs_1d(z, -1.0, 2)
    assert [(e["start"], e["end"], e["duration"]) for e in ev] == [(1, 2, 2), (5, 7, 3)]
    assert abs(ev[1]["peak"] + 2.1) < 1e-9 and abs(ev[1]["magnitude"] - 1.5) < 1e-9


def test_classify():
    z = np.array([-2.5, -1.7, -1.2, 0.0, 1.2, 1.7, 2.5, np.nan])
    assert I.classify(z).tolist() == [-3, -2, -1, 0, 1, 2, 3, -99]


def test_diagnosis_rules():
    ndvi = np.array([-1.5, -1.5, -1.5, 0.0, -1.5, 0.0, np.nan])
    spi = np.array([-1.5, 0.0, -0.7, -1.5, -0.4, 0.0, -1.5])
    assert G.diagnose(ndvi, spi).tolist() == [1, 2, 4, 3, 2, 0, -1]


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f()
            print("ok", k)
