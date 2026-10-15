"""Unit tests for the pure-numpy rules. Run: python -m pytest tests -q (from the tool folder)."""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from burncheck import core  # noqa: E402


def scene(r=200, c=200, nir=0.30, swir2=0.25, vis=0.15):
    x = np.empty((6, r, c), "float32")
    x[[0, 1, 2]] = vis
    x[3] = nir
    x[4] = 0.30
    x[5] = swir2
    return x


def test_nbr_and_brightness():
    x = scene()
    assert np.allclose(core.nbr(x), (0.30 - 0.25) / 0.55)
    assert np.allclose(core.brightness(x), (0.15 * 3 + 0.30 + 0.25) / 5)


def test_scl_mask_and_composite():
    dn = np.full((6, 4, 4), 1000, "uint16")
    scl = np.full((4, 4), 4, "uint8")
    scl[0, 0] = 9   # cloud high probability
    scl[0, 1] = 3   # shadow
    x = core.scl_to_nan(dn, scl)
    assert np.isnan(x[:, 0, 0]).all() and np.isnan(x[:, 0, 1]).all() and np.allclose(x[:, 1, 1], 0.1)
    med, n = core.composite([x, x * 2, x * 3])
    assert np.allclose(med[:, 1, 1], 0.2) and n[0, 0] == 0 and n[1, 1] == 3


def test_burned_block_found_and_season_ignored():
    before = scene()
    after = scene(nir=0.33)          # whole town greens up a little: NBR rises, dNBR negative
    after[:, 60:80, 60:80] = scene(20, 20, nir=0.18, swir2=0.24, vis=0.09)  # charred block: darker, NBR falls
    bld = np.zeros((200, 200), bool)
    bld[40:160:2, 40:160:2] = True   # sparse buildings everywhere
    bld[60:80, 60:80] = True
    L = core.burn_layers(before, after, bld, dict(bg_block=50))
    assert L["burned"][60:80, 60:80].all()
    assert not (L["burned"] & bld)[100:160, 100:160].any()


def test_darkening_needed():
    before = scene()
    after = scene()
    after[3, 10:20, 10:20] = 0.15    # NIR drop only (e.g. harvest, leaf loss), no darkening
    bld = np.ones((200, 200), bool)
    L = core.burn_layers(before, after, bld)
    assert not L["burned"].any()


def test_background_is_local():
    d = np.zeros((300, 300), "float32")
    d[:, 150:] = 0.2                  # east half shifted by season
    bg = core.local_background(d, np.ones_like(d, bool), block=50)
    assert abs(bg[150, 10]) < 0.01 and abs(bg[150, 290] - 0.2) < 0.01


def test_unit_stats_and_classes():
    uid = np.zeros((10, 10), "int32")
    uid[:5, :5] = 1
    uid[5:, 5:] = 2
    uid[:5, 5:] = 3
    bld = np.ones((10, 10), bool)
    clear = np.ones((10, 10), bool)
    clear[:5, 5:] = False             # unit 3 not seen
    burned = np.zeros((10, 10), bool)
    burned[:3, :5] = True             # unit 1: 15 of 25 px burned
    burned[5, 5:7] = True             # unit 2: 2 of 25 px
    L = dict(clear=clear, burned=burned, anomaly=np.zeros((10, 10)), burned_open=np.zeros((10, 10), bool))
    st = core.unit_stats(uid, 3, bld, L, ring_ids=np.zeros((10, 10), "int32"))
    cls, bpct, cpct, rpct, land = core.classify(st)
    assert st["burned_px"][1] == 15 and st["burned_px"][2] == 2
    assert cls[1] == 2 and cls[2] == 0 and cls[3] == 9
    assert np.isclose(bpct[1], 60.0) and cpct[3] == 0.0


def test_water_not_burned():
    before = scene()
    after = scene(nir=0.33)
    after[:, 60:80, 60:80] = scene(20, 20, nir=0.05, swir2=0.02, vis=0.06)  # pond: dark, NBR falls, but wet
    after[4, 60:80, 60:80] = 0.03
    bld = np.ones((200, 200), bool)
    L = core.burn_layers(before, after, bld)
    assert not L["burned"][60:80, 60:80].any()
