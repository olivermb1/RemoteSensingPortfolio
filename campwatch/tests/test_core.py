"""Unit tests for the pure-numpy rules. Run: python -m pytest tests -q (from the tool folder)."""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from campwatch import core  # noqa: E402


def comp(r=60, c=60, ratio=0.5, blue=0.10, ndvi=0.15):
    x = np.empty((3, r, c), "float32")
    x[0], x[1], x[2] = ratio, blue, ndvi
    return x


def test_indices_and_mask():
    dn = np.zeros((6, 2, 2), "uint16")
    dn[0], dn[2], dn[3] = 1000, 2000, 3000
    scl = np.array([[4, 9], [5, 3]])
    x = core.indices(dn, scl)
    assert np.isclose(x[0, 0, 0], 0.5) and np.isclose(x[1, 0, 0], 0.1) and np.isclose(x[2, 0, 0], 0.2)
    assert np.isnan(x[:, 0, 1]).all() and np.isnan(x[:, 1, 1]).all()


def test_shelter_needs_ratio_blue_and_not_green():
    base = comp()
    cur = comp(ratio=0.52, blue=0.105)            # whole area shifts a little with the season
    cur[:, 10:20, 10:20] = comp(10, 10, ratio=0.70, blue=0.14)   # new tarps
    cur[:, 30:40, 30:40] = comp(10, 10, ratio=0.70, blue=0.10)   # ratio only (e.g. darker red soil): no
    cur[:, 40:50, 40:50] = comp(10, 10, ratio=0.70, blue=0.14, ndvi=0.5)  # green crop: no
    s = core.shelter_month(cur, base)
    assert s[10:20, 10:20].all()
    assert not s[30:50, 30:50].any() and s[50:, :10].sum() == 0


def test_smooth_and_first_seen():
    T = np.array([0, 0, 1, 0, 1, 1, 1, np.nan, 1], "float32")[:, None, None]  # one pixel over 9 months
    P = core.smooth(T)
    assert P[3, 0, 0] == 1           # single gap filled by neighbours
    assert np.isnan(P[7, 0, 0])
    assert P[2, 0, 0] == 0 and core.first_seen(P)[0, 0] == 3   # lone first 1 is smoothed away
    flicker = np.array([1, 0, 0, 0, 0, 0], "float32")[:, None, None]
    assert core.first_seen(core.smooth(flicker))[0, 0] == -1


def test_label_and_area_series():
    m = np.zeros((20, 20), bool)
    m[2:5, 2:5] = True
    m[2:5, 7:9] = True                # 2 px gap: joined with join_px=2
    m[15:18, 15:18] = True
    lab, n = core.label(m, join_px=2)
    assert n == 2 and lab[3, 3] == lab[3, 8] != lab[16, 16]
    lab_py, n_py = core._label_py(core.label(m, 0)[0] > 0)
    assert n_py == 3
    first = np.full((20, 20), -1, "int16")
    first[m] = 1
    P = np.zeros((3, 20, 20), "float32")
    foot, obs = core.area_series(P, lab, n, first, 0.01)
    assert foot[0].sum() == 0 and np.isclose(foot[1, 1:].sum(), m.sum() * 0.01) and np.allclose(obs[:, 1:], 100)
