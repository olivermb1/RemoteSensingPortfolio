"""Core tests on small synthetic rasters (rasterio backend). Run: python -m pytest tests/ -q"""

import datetime as dt
import os
import sys

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from timeprofile import catalog, geom, report, rio_io, smooth  # noqa: E402
from timeprofile.extract import extract  # noqa: E402
from timeprofile.indices import Formula, resolve  # noqa: E402
from timeprofile.sensors import HLS_BANDS, clear_mask  # noqa: E402

# A 20 x 20 grid of 30 m pixels in EPSG:32637 written HLS-style (northern zone, negative northings)
X0, Y0, RES = 300000.0, -70000.0, 30.0
CRS = "EPSG:32637"


def _ll(col, row):
    xs, ys = rasterio.warp.transform(CRS, "EPSG:4326", [X0 + (col + 0.5) * RES], [Y0 - (row + 0.5) * RES])
    return xs[0], ys[0]


def _write(path, arr, dtype, nodata=None, transform=None, crs=CRS, desc=None, tags=None):
    arr = np.atleast_3d(arr) if arr.ndim == 2 else arr
    if arr.ndim == 3 and arr.shape[2] < arr.shape[0] and desc is None:
        arr = arr.transpose(2, 0, 1)
    with rasterio.open(path, "w", driver="GTiff", width=arr.shape[2], height=arr.shape[1], count=arr.shape[0],
                       dtype=dtype, crs=crs, transform=transform or from_origin(X0, Y0, RES, RES),
                       nodata=nodata) as d:
        d.write(arr.astype(dtype))
        if desc:
            for i, n in enumerate(desc, 1):
                d.set_band_description(i, n)
        if tags:
            d.update_tags(**tags)


def make_hls(folder, day, red, nir, fmask, prod="S30", tile="37MCV"):
    doy = (day - dt.date(day.year, 1, 1)).days + 1
    gid = f"HLS.{prod}.T{tile}.{day.year}{doy:03d}T074619.v2.0"
    d = os.path.join(folder, gid)
    os.makedirs(d, exist_ok=True)
    vals = {"blue": 300, "green": 500, "red": red, "nir": nir, "swir1": 2000, "swir2": 1000}
    for name, val in vals.items():
        code = HLS_BANDS[prod][name]
        _write(os.path.join(d, f"{gid}.{code}.tif"), np.full((1, 20, 20), val), "int16", -9999)
    _write(os.path.join(d, f"{gid}.Fmask.tif"), fmask[None], "uint8", 255)


@pytest.fixture
def hls(tmp_path):
    clear = np.zeros((20, 20), "uint8")
    cloudy = clear.copy()
    cloudy[:, :12] = 1 << 1  # cloud bit over the left 12 columns
    make_hls(tmp_path, dt.date(2024, 3, 1), 500, 3500, clear)
    make_hls(tmp_path, dt.date(2024, 3, 6), 600, 3000, cloudy)
    make_hls(tmp_path, dt.date(2024, 3, 9), 700, 2800, clear, prod="L30")
    return str(tmp_path)


def test_scan_hls(hls):
    sc = catalog.scan(hls)
    assert [s.sensor for s in sc] == ["HLS.S30", "HLS.S30", "HLS.L30"]
    assert sc[0].bands["nir"][0].endswith("B8A.tif") and sc[2].bands["nir"][0].endswith("B05.tif")
    assert sc[0].mask[2] == "fmask" and sc[0].scale == 1e-4 and sc[0].tile == "37MCV"


def test_point_and_polygon(hls):
    sc = catalog.scan(hls)
    lon, lat = _ll(15, 5)
    c = [_ll(c - 0.5, r - 0.5) for c, r in ((2, 2), (8, 2), (8, 8), (2, 8), (2, 2))]  # pixel edges; under the cloud
    feats = [{"name": "pt", "kind": "point", "coords": (lon, lat)},
             {"name": "poly", "kind": "polygon", "coords": [[c]]}]
    rows, notes = extract(sc, feats, ["NDVI"], rio_io)
    by = {(r["feature"], r["date"]): r for r in rows}
    assert by[("pt", "2024-03-01")]["value"] == pytest.approx((3500 - 500) / 4000)
    assert by[("pt", "2024-03-06")]["status"] == "clear"   # point is right of the cloud
    assert by[("poly", "2024-03-06")]["status"] == "masked"
    assert by[("poly", "2024-03-01")]["n_pixels"] == 36    # 6 x 6 pixel centres inside
    assert by[("pt", "2024-03-09")]["sensor"] == "HLS.L30"


def test_point_buffer_and_outside(hls):
    sc = catalog.scan(hls)
    lon, lat = _ll(12, 5)  # right at the cloud edge: 3x3 has 1 cloudy column of 3
    rows, _ = extract(sc, [{"name": "p", "kind": "point", "coords": (lon, lat)}], ["NDVI"], rio_io, buffer=1)
    r = [x for x in rows if x["date"] == "2024-03-06"][0]
    assert r["n_pixels"] == 9 and r["n_clear"] == 6 and r["status"] == "clear"
    rows, _ = extract(sc, [{"name": "far", "kind": "point", "coords": (10.0, 10.0)}], ["NDVI"], rio_io)
    assert rows == []


def test_overlap_dedupe(tmp_path):
    clear = np.zeros((20, 20), "uint8")
    half = clear.copy()
    half[:10] = 1 << 3  # shadow over the top half
    make_hls(tmp_path, dt.date(2024, 3, 1), 500, 3500, half, tile="37MCV")
    make_hls(tmp_path, dt.date(2024, 3, 1), 500, 3600, clear, tile="37MCU")  # same grid, other tile name
    c = [_ll(c, r) for c, r in ((1, 1), (18, 1), (18, 18), (1, 18), (1, 1))]
    rows, notes = extract(catalog.scan(str(tmp_path)), [{"name": "a", "kind": "polygon", "coords": [[c]]}],
                          ["NDVI"], rio_io)
    assert len(rows) == 1 and rows[0]["tile"] == "37MCU"
    assert any("duplicate" in n for n in notes)


def test_generic_multiband_with_scl_and_mixed_resolution(tmp_path):
    # 10 m red/nir + 20 m SCL companion; generic naming with a date
    t10 = from_origin(X0, Y0, 10, 10)
    _write(str(tmp_path / "site_2024-05-02.tif"), np.stack([np.full((40, 40), 400), np.full((40, 40), 3000)]),
           "uint16", 0, t10, desc=["red", "nir"], tags={"TP_SCALE": "0.0001"})
    scl = np.full((20, 20), 4, "uint8")
    scl[:, :10] = 9  # high-prob cloud over the left half
    _write(str(tmp_path / "site_2024-05-02_SCL.tif"), scl[None], "uint8", 0, from_origin(X0, Y0, 20, 20))
    sc = catalog.scan(str(tmp_path), rio_io.info)
    assert len(sc) == 1 and sc[0].mask[2] == "scl" and sc[0].date == dt.date(2024, 5, 2)
    xs, ys = rasterio.warp.transform(CRS, "EPSG:4326", [X0 + 105, X0 + 305], [Y0 - 105, Y0 - 105])
    feats = [{"name": "cloud", "kind": "point", "coords": (xs[0], ys[0])},
             {"name": "sun", "kind": "point", "coords": (xs[1], ys[1])}]
    rows, _ = extract(sc, feats, ["NDVI", "red"], rio_io)
    st = {(r["feature"], r["index"]): r for r in rows}
    assert st[("cloud", "NDVI")]["status"] == "masked"
    assert st[("sun", "red")]["value"] == pytest.approx(0.04)


def test_impossible_reflectance_is_dropped(tmp_path):
    _write(str(tmp_path / "x_20240101.tif"), np.stack([np.full((5, 5), 400), np.full((5, 5), 3000)]),
           "uint16", 0, desc=["red", "nir"], tags={"TP_SCALE": "0.0001", "TP_OFFSET": "-0.1"})  # wrong offset
    sc = catalog.scan(str(tmp_path), rio_io.info)
    lon, lat = _ll(2, 2)
    rows, notes = extract(sc, [{"name": "p", "kind": "point", "coords": (lon, lat)}], ["NDVI"], rio_io)
    assert rows == [] and any("impossible reflectance" in n for n in notes)


def test_masks():
    fm = np.array([0, 2, 4, 8, 16, 32, 192, 128, 255])
    assert clear_mask(fm, "fmask").tolist() == [True, False, False, False, False, True, False, True, False]
    assert clear_mask(fm, "fmask", ["water"]).tolist()[5] is False
    scl = np.arange(12)
    assert np.flatnonzero(clear_mask(scl, "scl")).tolist() == [2, 4, 5, 6, 7]
    qa = np.array([21824, 22280, 23888, 1])  # clear, cloud, cloud+shadow-ish, fill
    assert clear_mask(qa, "qa_pixel").tolist() == [True, False, False, False]


def test_formulas():
    f = resolve("MSI=swir1/nir")
    assert f.bands == ["nir", "swir1"] and f({"nir": np.array([2.0]), "swir1": np.array([1.0])})[0] == 0.5
    assert resolve("ndvi").name == "NDVI"
    for bad in ("__import__('os')", "nir.real", "[1,2]", "open('x')"):
        with pytest.raises(ValueError):
            Formula("x", bad)


def test_dates_and_mgrs():
    assert catalog.parse_date("S2A_37MCV_20240303_0_L2A") == dt.date(2024, 3, 3)
    assert catalog.parse_date("ndvi_2023-11-05") == dt.date(2023, 11, 5)
    assert catalog.parse_date("MOD13Q1.A2024129") == dt.date(2024, 5, 8)
    assert geom.mgrs_tile(37.35, -0.70) == "37MCV" and geom.mgrs_tile(35.27, 0.5) == "36NYF"


def test_smoothing_and_spikes():
    d0 = dt.date(2024, 1, 1)
    ds = [d0 + dt.timedelta(k) for k in range(0, 200, 5)]
    v = [0.5 + 0.3 * np.sin(k / 30) for k in range(0, 200, 5)]
    v[10] -= 0.4
    assert smooth.flag_spikes(ds, v) == [10]
    gap = ds[:15] + [d + dt.timedelta(100) for d in ds[15:]]
    assert len(smooth.whittaker(gap, v, 1000, max_gap=60)) == 2
    seas = smooth.seasons(ds, v, start_month=10)
    assert seas[0]["season"] == "2023-24"


def test_outputs(hls, tmp_path):
    sc = catalog.scan(hls)
    lon, lat = _ll(15, 5)
    rows, notes = extract(sc, [{"name": "pt", "kind": "point", "coords": (lon, lat)}], ["NDVI", "NDMI"], rio_io)
    paths = report.outputs(str(tmp_path / "out"), rows, notes, {})
    back = report.read_csv(paths["series"])
    assert len(back) == 6 and os.path.exists(paths["chart"])


def test_missing_band_skips_only_that_index(tmp_path):
    make_hls(tmp_path, dt.date(2024, 3, 1), 500, 3500, np.zeros((20, 20), "uint8"))
    for p in tmp_path.rglob("*.B11.tif"):
        p.unlink()
    lon, lat = _ll(5, 5)
    rows, notes = extract(catalog.scan(str(tmp_path)), [{"name": "p", "kind": "point", "coords": (lon, lat)}],
                          ["NDVI", "NDMI"], rio_io)
    assert [r["index"] for r in rows] == ["NDVI"] and "no swir1 band, so no NDMI" in notes[0]
