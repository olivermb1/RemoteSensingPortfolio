import json
import os
import sys

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from distwatch import catalog, core, products as P  # noqa: E402

DEMO = os.path.join(os.path.dirname(HERE), "demo", "data")


def test_codes_and_levels():
    st = np.array([0, 1, 2, 3, 4, 5, 6, 7, 8, 255])
    an = np.full(10, 80)
    dd = np.full(10, 100)
    assert core.qualifying(st, an, dd, level="confirmed").tolist() == [0, 0, 0, 1, 0, 0, 1, 1, 1, 0]
    assert core.qualifying(st, an, dd, level="provisional").sum() == 6
    assert core.qualifying(st, an, dd, level="first").sum() == 8


def test_min_loss_since_and_forest():
    st = np.array([6, 6, 6, 6])
    an = np.array([49, 50, 90, 255])
    dd = np.array([10, 10, 10, 10])
    assert core.qualifying(st, an, dd).tolist() == [0, 1, 1, 0]
    assert core.qualifying(st, an, dd, min_loss=0).tolist() == [1, 1, 1, 1]
    assert not core.qualifying(st, an, dd, since=10).any()
    assert core.qualifying(st, an, dd, since="2020-12-31").sum() == 2
    assert core.qualifying(st, an, dd, forest=np.array([1, 0, 1, 1])).tolist() == [0, 0, 1, 0]


def test_dates():
    assert P.day_to_date(1).isoformat() == "2021-01-01"
    assert P.date_to_day("2025-01-01") == 1462


def test_diff():
    q = np.array([1, 1, 0, 0], bool)
    rep = np.array([0, 2, 1, 0], "uint16")
    new, old, gone = core.diff(q, rep)
    assert new.tolist() == [1, 0, 0, 0] and old.tolist() == [0, 1, 0, 0] and gone.tolist() == [0, 0, 1, 0]


def test_label_connectivity_and_size():
    m = np.zeros((5, 5), bool)
    m[0, 0] = m[1, 1] = True       # diagonal pair
    m[3, 3:5] = m[4, 3] = True     # three pixels
    assert core.label(m, 8)[1] == 2
    assert core.label(m, 4)[1] == 3
    lab, n = core.drop_small(core.label(m)[0], 3)
    assert n == 1 and (lab > 0).sum() == 3


def test_patch_stats():
    lab = np.array([[1, 1, 0], [0, 0, 2]], "int32")
    an = np.array([[60, 80, 0], [0, 0, 55]])
    dd = np.array([[1500, 1510, -1], [-1, -1, 1520]])
    s = core.patch_stats(lab, 2, an, dd)
    assert s[0]["pixels"] == 2 and s[0]["area_ha"] == 0.18 and s[0]["mean_loss_pct"] == 70.0
    assert s[0]["first_detected"] == P.day_to_date(1500).isoformat()
    assert s[1]["max_loss_pct"] == 55


def test_owner_mask_splits_overlap():
    lon = np.array([0.1, 0.49, 0.51, 0.9])
    lat = np.zeros(4)
    assert core.owner_mask(lon, lat, (0, 0), [(1, 0)]).tolist() == [1, 1, 0, 0]


def test_parse_name():
    d = P.parse_name("OPERA_L3_DIST-ALERT-HLS_T30NWM_20250110T103021Z_20250112T051234Z_S2A_30_v1_VEG-DIST-STATUS.tif")
    assert d["tile"] == "30NWM" and d["layer"] == "VEG-DIST-STATUS" and d["sensing"].day == 10
    assert P.parse_name("random.tif") is None


@pytest.mark.skipif(not os.path.isdir(os.path.join(DEMO, "granules")), reason="run demo/make_demo_data.py first")
def test_demo_end_to_end(tmp_path):
    pytest.importorskip("rasterio")
    from distwatch import watch
    g, _ = catalog.latest_per_tile(os.path.join(DEMO, "granules"), "2025-01-15")
    assert sorted(g) == ["30NWM", "30NXM"] and g["30NWM"]["sensing"].month == 1
    state = str(tmp_path / "state")
    run = lambda d, **kw: watch.run(os.path.join(DEMO, "granules"), os.path.join(DEMO, "areas.geojson"), state,  # noqa: E731
                                    str(tmp_path / d), as_of=d, log=lambda *_: None, **kw)
    r1, rows1, _ = run("2025-01-15")
    r2, rows2, _ = run("2025-02-15")
    by = {r["area"]: r for r in rows2}
    # Four new patches; the one in the tile overlap is counted once.
    assert r2["new_patches"] == 4
    assert by["Overlap village lands"]["new_patches"] == 1
    assert by["Whole supply shed"]["new_loss_ha"] == pytest.approx(r2["new_loss_ha"])
    # Provisional at run 1, confirmed by run 2: reported at run 2.
    assert by["Forest reserve (synthetic)"]["new_patches"] == 2
    assert by["Farm outside the tiles"]["covered"] is False
    # Nothing new when the same granules are read again; a dry run leaves the state alone.
    r2b, _, tiles = run("2025-02-16", dry_run=True)
    assert r2b["new_patches"] == 0 and all(t["unchanged_since_last_run"] for t in tiles)
    with open(os.path.join(state, "state.json")) as f:
        assert len(json.load(f)["runs"]) == 2
    r3, rows3, _ = run("2025-03-15")
    by3 = {r["area"]: r for r in rows3}
    assert by3["Cooperative B farms"]["new_loss_ha"] > 0
    assert by3["Forest reserve (synthetic)"]["total_loss_ha"] > by["Forest reserve (synthetic)"]["total_loss_ha"]
    with open(tmp_path / "2025-03-15" / "new_loss.geojson") as f:
        assert all(ft["properties"]["run"] == 3 for ft in json.load(f)["features"])
