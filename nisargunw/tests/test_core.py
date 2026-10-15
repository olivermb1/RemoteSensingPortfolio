import glob
import os
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from nisargunw import core, product as P  # noqa: E402

DEMO = glob.glob(os.path.join(ROOT, "demo", "data", "NISAR_L2_*GUNW*.h5"))


def test_grid_uses_pixel_centres():
    # isce3 writes xCoordinates as start + 0.5*dx + i*dx
    g = core.Grid.from_coords(np.array([40.0, 120.0, 200.0]), np.array([960.0, 880.0]), 32637)
    assert g.geotransform() == (0.0, 80.0, 0.0, 1000.0, 0.0, -80.0)
    assert g.bounds() == (0.0, 840.0, 240.0, 1000.0)
    assert g.geotransform((1, 2, 1, 3))[0] == 80.0 and g.geotransform((1, 2, 1, 3))[3] == 920.0


def test_window_for_bounds():
    g = core.Grid.from_coords(40.0 + 80 * np.arange(10), 760.0 - 80 * np.arange(10), 32637)
    assert g.window_for_bounds(100, 500, 300, 700) == (1, 4, 1, 4)
    assert g.window_for_bounds(-500, -500, -100, -100) is None
    assert g.window_for_bounds(-1e9, -1e9, 1e9, 1e9) == (0, 10, 0, 10)


def test_interp_cube_is_exact_for_linear_fields():
    cx = np.arange(0, 10001, 2000.0)
    cy = np.arange(10000, -1, -2000.0)
    ch = np.array([-500.0, 0, 500, 1000, 2000])
    H, Y, X = np.meshgrid(ch, cy, cx, indexing="ij")
    cube = 2 * X + 3 * Y + 0.5 * H
    xs = np.linspace(100, 9900, 37)
    ys = np.linspace(9900, 100, 23)
    hs = np.random.default_rng(0).uniform(-400, 1900, (23, 37))
    out = core.interp_cube(cube, cx, cy, ch, xs, ys, hs, block_rows=5)
    expect = 2 * xs[None, :] + 3 * ys[:, None] + 0.5 * hs
    assert np.allclose(out, expect, atol=1e-2)


def test_decode_mask():
    m = np.array([11, 111, 10, 1, 0, 255, 11 + (5 << 8)], np.uint32)
    valid, water = P.decode_mask(m, fill=255)
    assert valid.tolist() == [True, True, False, False, False, False, True]
    assert water.tolist() == [False, True, False, False, False, False, False]


def test_phase_to_los():
    lam = P.wavelength(1.2575e9)
    assert abs(lam - 0.2384) < 1e-3
    # one fringe = half a wavelength; positive phase = range increase = away from satellite
    assert np.isclose(core.phase_to_los(2 * np.pi, lam), -lam / 2)


def test_reference_modes():
    v = np.array([[1.0, 2, 3], [10, 11, 12]], np.float32)
    keep = np.ones_like(v, bool)
    cc = np.array([[1, 1, 1], [2, 2, 2]])
    out, info = core.reference(v, keep, cc, "largest")
    assert info["component"] in (1, 2)
    out, info = core.reference(v, keep, cc, "point", (1, 1), win=0)
    assert out[1, 1] == 0 and info["component"] == 2
    with pytest.raises(ValueError):
        core.reference(v, np.zeros_like(keep), cc, "median")


@pytest.mark.skipif(not DEMO, reason="run demo/make_demo_data.py first")
def test_demo_matches_truth(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    from nisargunw import convert, rio_io
    meta = convert.convert(DEMO[0], str(tmp_path), rio_io, dem=os.path.join(ROOT, "demo", "data", "dem_fentale.tif"),
                           layers="los_displacement,keep_mask", quicklook=False, log=lambda *_: None)
    assert meta["corrections"]["applied"] == list(P.CORRECTIONS)
    a = rasterio.open(tmp_path / meta["outputs"]["los_displacement"]["file"]).read(1)
    t = rasterio.open(os.path.join(ROOT, "demo", "data", "truth_los_displacement.tif")).read(1)
    m = np.isfinite(a) & np.isfinite(t)
    e = (a - t)[m]
    e -= np.median(e)
    assert np.sqrt(np.mean(e ** 2)) < 0.005          # under 5 mm RMS
    assert 0.8 < meta["kept_fraction"] < 0.95       # water, wedge, cc 0 and component 2 dropped
    assert meta["water_pixels"] > 0


@pytest.mark.skipif(not DEMO, reason="run demo/make_demo_data.py first")
def test_gdal_reader_matches_h5py():
    pytest.importorskip("osgeo.gdal")
    from nisargunw.readers import GdalReader, H5pyReader
    a, b = H5pyReader(DEMO[0]), GdalReader(DEMO[0])
    for key in ("unwrapped_phase", "connected_components", "mask"):
        gfun, in_pol, name = P.LAYERS[key][:3]
        p = f"{gfun('A')}/HH/{name}" if in_pol else f"{gfun('A')}/{name}"
        assert np.array_equal(a.read(p, (5, 50, 7, 60)), b.read(p, (5, 50, 7, 60)), equal_nan=True)
        assert a.attr(p, "units") == b.attr(p, "units")
    assert a.value(f"{P.IDENT}/granuleId") == b.value(f"{P.IDENT}/granuleId")


def test_isce3_fixture_if_given():
    """Set ISCE3_GUNW=/path/to/isce3/tests/data/solid_earth_tides/GUNW.h5 (a real-layout
    GUNW from JPL's isce3 repo; it holds metadata and the radar grid cube only)."""
    path = os.environ.get("ISCE3_GUNW")
    if not path:
        pytest.skip("ISCE3_GUNW not set")
    from nisargunw import convert
    info = convert.inspect(path)
    assert info["identification"]["productType"] == "GUNW"
    assert info["radar_grid_cube"]["incidence_angle"][0] >= 2
