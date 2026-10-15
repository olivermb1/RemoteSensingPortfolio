"""Make a synthetic stand-in for OPERA DIST-ALERT-HLS over the Ghana cocoa belt.

Real DIST-ALERT needs an Earthdata login and NASA's servers, which were not
reachable where this tool was built. This script writes files with the real
product's names, layers, codes and day numbering, on a small UTM 30N grid
near Sefwi Wiawso, Western North Region (6.2 N, 2.5 W). Nothing in it is
real loss: patch shapes, dates and places are invented to exercise the tool.

It writes two overlapping 12 km tile subsets (named after MGRS tiles 30NWM and
30NXM) at three dates, a forest mask in lon/lat, and an areas GeoJSON.
"""

import datetime as dt
import json
import os
import sys

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.transform import from_origin

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from distwatch import products as P  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data")
RNG = np.random.default_rng(7)
CRS = "EPSG:32630"
X0, Y0 = 544000.0, 697000.0  # upper-left of the synthetic world
W, H = 733, 400              # 22 km x 12 km at 30 m
TILES = {"30NWM": 0, "30NXM": 333}  # column offset; each tile subset is 400 x 400, 67 px overlap
DATES = {  # three sensing dates per tile, a month apart
    "30NWM": ["20250108T103021", "20250207T103019", "20250309T103027"],
    "30NXM": ["20250109T102959", "20250208T103001", "20250310T103003"],
}

# Disturbance events: centre (row, col), radius px, first detection, confirmation, loss %, finished.
D = P.date_to_day
EVENTS = [
    # Already there before run 1 (cleared in 2023-24).
    dict(rc=(80, 120), r=9, first=D("2023-11-02"), conf=D("2023-11-20"), loss=88, fin=D("2024-02-01")),
    dict(rc=(300, 520), r=7, first=D("2024-06-15"), conf=D("2024-07-01"), loss=76, fin=None),
    dict(rc=(210, 250), r=5, first=D("2024-12-01"), conf=D("2024-12-20"), loss=64, fin=None),
    # Partial loss, under 50%: degradation that the default rules leave out.
    dict(rc=(150, 600), r=8, first=D("2024-10-10"), conf=D("2024-11-01"), loss=32, fin=None),
    # Provisional at run 1, confirmed only by run 2: detected before run 1 but reported at run 2.
    dict(rc=(120, 420), r=6, first=D("2024-12-28"), conf=D("2025-01-20"), loss=71, fin=None),
    # New between run 1 and run 2.
    dict(rc=(60, 300), r=8, first=D("2025-01-12"), conf=D("2025-01-30"), loss=91, fin=None),   # in the forest reserve
    dict(rc=(330, 160), r=5, first=D("2025-01-15"), conf=D("2025-02-01"), loss=58, fin=None),  # by cooperative A
    dict(rc=(250, 366), r=6, first=D("2025-01-18"), conf=D("2025-02-03"), loss=83, fin=None),  # in the tile overlap
    # New between run 2 and run 3, including growth of the reserve clearing.
    dict(rc=(66, 312), r=7, first=D("2025-02-14"), conf=D("2025-03-01"), loss=89, fin=None),
    dict(rc=(340, 640), r=6, first=D("2025-02-20"), conf=D("2025-03-05"), loss=67, fin=None),  # cooperative B
    # Only provisional by run 3: counted when confirmed later.
    dict(rc=(30, 680), r=5, first=D("2025-03-02"), conf=D("2025-04-01"), loss=80, fin=None),
]


def blob(rc, r):
    """An irregular patch: a disc with a noisy edge."""
    yy, xx = np.mgrid[:H, :W]
    d = np.hypot(yy - rc[0], (xx - rc[1]) * 1.15)
    ang = np.arctan2(yy - rc[0], xx - rc[1])
    edge = r * (1 + 0.25 * np.sin(3 * ang + r) + 0.15 * np.cos(5 * ang))
    return d <= edge


def world(day):
    """Status, max anomaly, first-detection day, anomalous-obs count on the full grid at a day number."""
    st = np.zeros((H, W), "uint8")
    an = np.zeros((H, W), "uint8")
    dd = np.full((H, W), -1, "int16")
    cf = np.zeros((H, W), "int16")
    for k, e in enumerate(EVENTS):
        er = np.random.default_rng(100 + k)  # same per-pixel dates and loss at every date and in both tiles
        m = blob(e["rc"], e["r"])
        jitter = er.integers(0, 10, (H, W))
        first = e["first"] + jitter
        m &= first <= day
        if not m.any():
            continue
        hi = e["loss"] >= 50
        if e["fin"] and day >= e["fin"]:
            code = 8 if hi else 7
        elif day >= e["conf"]:
            code = 6 if hi else 3
        elif day >= e["first"] + 8:
            code = 5 if hi else 2
        else:
            code = 4 if hi else 1
        st[m] = code
        an[m] = np.clip(e["loss"] + er.normal(0, 6, (H, W)), 1, 100).astype("uint8")[m]
        dd[m] = first[m]
        cf[m] = np.clip((day - first[m]) // 6 + 1, 1, 40)
    # Speckle: one-pixel first detections that come and go, and a few one-pixel confirmed alerts.
    sp = (RNG.random((H, W)) < 0.002) & (st == 0)
    st[sp], an[sp], dd[sp], cf[sp] = 4, RNG.integers(50, 80, sp.sum()), day - 3, 1
    sp2 = (RNG.random((H, W)) < 0.0003) & (st == 0)
    st[sp2], an[sp2], dd[sp2], cf[sp2] = 6, 60, day - 20, 3
    return st, an, dd, cf


def write(path, arr, transform, nodata):
    with rasterio.open(path, "w", driver="GTiff", width=arr.shape[1], height=arr.shape[0], count=1,
                       dtype=arr.dtype, crs=CRS, transform=transform, nodata=nodata, compress="deflate") as ds:
        ds.write(arr, 1)


def main():
    os.makedirs(os.path.join(OUT, "granules"), exist_ok=True)
    for i in range(3):
        for tile, c0 in TILES.items():
            sensing = DATES[tile][i]
            day = D(dt.date.fromisoformat(sensing[:4] + "-" + sensing[4:6] + "-" + sensing[6:8]))
            st, an, dd, cf = (a[:, c0:c0 + 400].copy() for a in world(day))
            if tile == "30NXM":
                st[:40, 360:] = P.STATUS_NODATA  # a corner outside the swath
            prod = (dt.datetime.strptime(sensing, "%Y%m%dT%H%M%S") + dt.timedelta(days=2)).strftime("%Y%m%dT%H%M%S")
            gid = f"OPERA_L3_DIST-ALERT-HLS_T{tile}_{sensing}Z_{prod}Z_S2A_30_v1"
            tr = from_origin(X0 + c0 * 30, Y0, 30, 30)
            layers = {"VEG-DIST-STATUS": (st, 255), "VEG-ANOM-MAX": (an, 255), "VEG-DIST-DATE": (dd, -1),
                      "VEG-DIST-CONF": (cf, -1),
                      "VEG-LAST-DATE": (np.full(st.shape, day, "int16"), -1)}
            for name, (arr, nd) in layers.items():
                write(os.path.join(OUT, "granules", f"{gid}_{name}.tif"), arr, tr, nd)
    print("granules written")

    # Forest mask in lon/lat (non-zero = forest at end-2020), like JRC GFC2020 would be.
    to_ll = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True)
    to_utm = Transformer.from_crs("EPSG:4326", CRS, always_xy=True)
    lon0, lat1 = to_ll.transform(X0 - 300, Y0 + 300)
    lon1, lat0 = to_ll.transform(X0 + W * 30 + 300, Y0 - H * 30 - 300)
    res = 0.00027
    nx, ny = int((lon1 - lon0) / res), int((lat1 - lat0) / res)
    lons = lon0 + (np.arange(nx) + 0.5) * res
    lats = lat1 - (np.arange(ny) + 0.5) * res
    LON, LAT = np.meshgrid(lons, lats)
    X, Y = to_utm.transform(LON, LAT)
    col, row = (X - X0) / 30, (Y0 - Y) / 30
    forest = ((row < 160) & (col > 180) & (col < 560)).astype("uint8")             # forest reserve block
    forest |= (np.hypot(row - 250, col - 366) < 30).astype("uint8")                # forest remnant in the overlap
    forest |= (np.hypot(row - 300, col - 520) < 25).astype("uint8")
    forest |= (np.hypot(row - 340, col - 640) < 20).astype("uint8")
    with rasterio.open(os.path.join(OUT, "forest_2020_mask.tif"), "w", driver="GTiff", width=nx, height=ny,
                       count=1, dtype="uint8", crs="EPSG:4326", transform=from_origin(lon0, lat1, res, res),
                       nodata=0, compress="deflate") as ds:
        ds.write(forest, 1)

    def box(r0, r1, c0, c1):
        pts = [(c0, r0), (c1, r0), (c1, r1), (c0, r1), (c0, r0)]
        return [[list(map(lambda v: round(v, 6), to_ll.transform(X0 + c * 30, Y0 - r * 30))) for c, r in pts]]

    areas = [
        ("Forest reserve (synthetic)", box(0, 160, 180, 560)),
        ("Cooperative A farms", box(280, 380, 100, 230)),
        ("Cooperative B farms", box(300, 395, 580, 720)),
        ("Overlap village lands", box(220, 290, 330, 410)),
        ("Whole supply shed", box(5, 395, 5, 728)),
        ("Farm outside the tiles", box(-400, -380, 100, 120)),
    ]
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"name": n}, "geometry": {"type": "Polygon", "coordinates": g}}
        for n, g in areas]}
    with open(os.path.join(OUT, "areas.geojson"), "w") as f:
        json.dump(fc, f, indent=1)
    print("forest mask and areas written")


if __name__ == "__main__":
    main()
