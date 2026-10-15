"""Offline tests for compositecheck.fetch (no network, no Earthdata login)."""

import os

import numpy as np
import rasterio
from rasterio.transform import from_origin

from compositecheck import catalog, fetch


class FakeGranule:
    def __init__(self, urls):
        self.urls = urls

    def data_links(self, access="external"):
        return self.urls


def test_granule_files_keeps_needed_bands():
    base = "https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected/HLSS30.020/"
    gid = "HLS.S30.T36MZE.2024092T075619.v2.0"
    urls = [f"{base}{gid}/{gid}.{b}.tif" for b in ["B01", "B02", "B03", "B04", "B05", "B8A", "B11", "B12", "Fmask", "SZA"]]
    files = fetch.granule_files(FakeGranule(urls + [f"{base}{gid}/{gid}.jpg"]))
    assert list(files) == [gid]
    assert set(files[gid]) == {"_tile", "B02", "B03", "B04", "B8A", "B11", "B12", "Fmask"}
    assert files[gid]["_tile"] == "T36MZE"


def test_clip_one_cuts_window_and_keeps_name(tmp_path):
    # a 300 x 300 30 m tile in UTM 36S around Nakuru, like an HLS band
    src = tmp_path / "HLS.L30.T36MZE.2024005T074623.v2.0.B04.tif"
    tr = from_origin(820000, 9980000, 30, 30)
    with rasterio.open(src, "w", driver="GTiff", width=300, height=300, count=1, dtype="int16",
                       crs="EPSG:32736", transform=tr, nodata=-9999) as d:
        d.write(np.arange(90000, dtype="int16").reshape(300, 300) % 3000, 1)
    out = tmp_path / "out"
    out.mkdir()
    dest = out / src.name
    from rasterio.warp import transform_bounds
    # bbox covering the middle third of the tile
    bbox = transform_bounds("EPSG:32736", "EPSG:4326", 823000, 9974000, 826000, 9977000)
    assert fetch.clip_one(str(src), bbox, str(dest)) == "ok"
    with rasterio.open(dest) as r:
        assert 95 <= r.width <= 105 and 95 <= r.height <= 105
        assert r.crs.to_epsg() == 32736
    assert fetch.clip_one(str(src), bbox, str(dest)) == "skip"
    far = (10.0, 10.0, 10.1, 10.1)
    assert fetch.clip_one(str(src), far, str(out / "x.tif")) == "outside"
    # the clipped file is still picked up by the HLS folder reader once the granule is complete
    assert catalog.HLS_RE.search(dest.name)
