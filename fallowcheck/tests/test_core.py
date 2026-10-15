"""Unit tests for the pure-numpy rules. Run: python -m pytest tests -q (from the tool folder)."""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fallowcheck import core  # noqa: E402


def test_ndvi_mask():
    dn = np.zeros((6, 1, 3), "uint16")
    dn[0], dn[2], dn[3] = 500, 1000, 3000
    v = core.ndvi(dn, np.array([[4, 6, 9]]))
    assert np.isclose(v[0, 0], 0.5) and np.isnan(v[0, 1]) and np.isnan(v[0, 2])  # water and cloud dropped


def test_peak_is_robust_to_one_spike():
    s = np.full((10, 1, 1), 0.2, "float32")
    s[3] = 0.9
    peak, n = core.season_peak(s)
    assert peak[0, 0] < 0.5 and n[0, 0] == 10


def test_classes():
    base = np.array([[[0.7, 0.7, 0.7, 0.2, 0.7]]] * 3, "float32")
    target = np.array([[0.68, 0.45, 0.20, 0.10, np.nan]], "float32")
    cls = core.classify(target, base)
    assert cls.tolist() == [[1, 2, 3, 0, 255]]


def test_too_few_observations():
    base = np.full((3, 1, 1), 0.7, "float32")
    cls = core.classify(np.full((1, 1), 0.2, "float32"), base, n_target=np.array([[2]]))
    assert cls[0, 0] == 255


def test_leave_one_out_and_unit_table():
    peaks = np.full((3, 4, 4), 0.7, "float32")
    peaks[0, :2] = 0.2                          # one normal year with half the fields fallow
    loo = core.leave_one_out(peaks)
    assert (loo[0] == 3).sum() == 8 and (loo[1] == 3).sum() == 0
    uid = np.ones((4, 4), "int32")
    t = core.unit_table(uid, 1, loo[0])
    assert np.isclose(t["not_farmed_pct"][1], 50) and np.isclose(t["farmed_base_ha"][1], 0.16)


def test_field_contrast_falls_when_cover_is_uniform():
    rng = np.random.default_rng(0)
    patchwork = np.kron(rng.choice([0.2, 0.7], (8, 8)), np.ones((10, 10))).astype("float32")
    uniform = np.full_like(patchwork, 0.65) + rng.normal(0, 0.01, patchwork.shape).astype("float32")
    a, b = core.field_contrast(patchwork).mean(), core.field_contrast(uniform).mean()
    assert b < a / 3
    uid = np.ones(patchwork.shape, "int32")
    cons = np.stack([core.unit_mean(uid, 1, core.field_contrast(x)) for x in (patchwork, patchwork, uniform)])
    target, normal = core.pattern_ratios(cons, 2)
    assert target[1] < 0.4 and np.allclose(normal[:, 1], 1.0)
