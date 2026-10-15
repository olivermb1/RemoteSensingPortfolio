"""Synthetic checks: python -m pytest tests  (or python tests/test_core.py)."""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from classspectra import core  # noqa: E402


def make_scene(seed=0):
    rng = np.random.default_rng(seed)
    labels = np.zeros((100, 100), int)
    labels[:, :50] = 1
    labels[:, 50:] = 2
    spec = {1: np.array([0.05, 0.08, 0.30]), 2: np.array([0.20, 0.22, 0.25])}
    img = np.zeros((3, 100, 100), "float32")
    for c, s in spec.items():
        m = labels == c
        img[:, m] = s[:, None] + rng.normal(0, 0.01, (3, m.sum()))
    return img, labels, spec


def test_medians_recovered():
    img, labels, spec = make_scene()
    res = core.class_signatures(img, labels, red_nir=(0, 2))
    for c, s in spec.items():
        assert np.allclose(res[c]["stats"]["median"], s, atol=0.005)
    assert res[1]["ndvi"]["median"] > 0.6


def test_label_noise_is_trimmed():
    img, labels, spec = make_scene()
    noisy = labels.copy()
    rng = np.random.default_rng(1)
    flip = (labels == 2) & (rng.random(labels.shape) < 0.10)  # 10% of class 2 really class 1
    noisy[flip] = 2
    img[:, flip] = spec[1][:, None]
    raw = core.class_signatures(img, noisy, erosion=0, outlier_z=0)
    clean = core.class_signatures(img, noisy, erosion=0, outlier_z=3.5)
    err_raw = np.abs(raw[2]["stats"]["mean"] - spec[2]).max()
    err_clean = np.abs(clean[2]["stats"]["median"] - spec[2]).max()
    assert err_clean < err_raw
    assert clean[2]["outlier_share"] > 0.05


def test_erosion_removes_edges_and_keeps_thin_classes():
    labels = np.ones((50, 50), int)
    labels[:, 25] = 3  # one-pixel-wide road
    img = np.random.default_rng(0).random((2, 50, 50)).astype("float32")
    keep = core.interior_mask(labels, 1)
    assert not keep[:, 24].any() and not keep[:, 26].any()
    res = core.class_signatures(img, labels, erosion=1, min_pixels=10, outlier_z=0)
    assert res[3]["stats"] is not None
    assert any("erosion skipped" in w for w in res[3]["warnings"])


def test_jm_bounds():
    img, labels, _ = make_scene()
    res = core.class_signatures(img, labels)
    cls, m = core.separability_matrix(res)
    assert m[0, 1] > 1.9 and m[0, 0] == 0
    same = core.jeffries_matusita(res[1]["samples"], res[1]["samples"])
    assert same < 0.01


if __name__ == "__main__":
    for name, f in list(globals().items()):
        if name.startswith("test_"):
            f()
            print("ok", name)
