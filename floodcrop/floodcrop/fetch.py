"""Download inputs for an event: water layers, cropland, permanent water, zones.

    python -m floodcrop.fetch s1        --bbox W S E N --event-date 2024-05-01 --out data/
    python -m floodcrop.fetch dswx      --bbox W S E N --event-date 2024-05-01 --out data/ [--product hls|s1]
    python -m floodcrop.fetch cropland  --bbox W S E N --out data/ [--source worldcover|deafrica --region eastern]
    python -m floodcrop.fetch permanent --bbox W S E N --out data/          (DE Africa WOfS all-time frequency)
    python -m floodcrop.fetch zones     --bbox W S E N --country KE --level county --out data/   (Overture admin areas)
    python -m floodcrop.fetch fewsnet   --country KE --out data/             (FEWS NET livelihood zones)

Tested from the build sandbox: s1, cropland, permanent, zones (public AWS buckets).
NOT tested (hosts were blocked from the sandbox): dswx (needs a free NASA
Earthdata login and `pip install earthaccess`) and fewsnet.
"""
import argparse
import datetime as dt
import json
import math
import os
import re
import urllib.request

import numpy as np

CA = "/root/.ccr/ca-bundle.crt"  # sandbox proxy CA; ignored elsewhere
S1_BUCKET = "https://deafrica-sentinel-1.s3.af-south-1.amazonaws.com"
DEA_BUCKET = "https://deafrica-services.s3.af-south-1.amazonaws.com"
WC_BUCKET = "https://esa-worldcover.s3.eu-central-1.amazonaws.com"
OVERTURE_RELEASE = "2026-09-23.1"


def _env():
    import rasterio
    kw = dict(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif")
    if os.path.exists(CA) and not os.environ.get("CURL_CA_BUNDLE"):
        kw["CURL_CA_BUNDLE"] = CA
    return rasterio.Env(**kw)


def _get(url):
    import ssl
    ctx = ssl.create_default_context(cafile=CA) if os.path.exists(CA) else None
    with urllib.request.urlopen(url, context=ctx, timeout=60) as r:
        return r.read()


def s3_list(bucket_url, prefix, delimiter="/"):
    """Public S3 bucket listing over HTTPS -> (sub-prefixes, keys)."""
    prefixes, keys, token = [], [], None
    while True:
        q = f"{bucket_url}/?list-type=2&prefix={prefix}&delimiter={delimiter}"
        if token:
            q += "&continuation-token=" + urllib.request.quote(token, safe="")
        xml = _get(q).decode()
        prefixes += re.findall(r"<Prefix>([^<]+)</Prefix>", xml)[1:] if "<CommonPrefixes>" in xml else []
        keys += re.findall(r"<Key>([^<]+)</Key>", xml)
        m = re.search(r"<NextContinuationToken>([^<]+)</NextContinuationToken>", xml)
        if not m:
            return [p for p in prefixes if p != prefix], keys
        token = m.group(1)


def clip_mosaic(urls, out, bbox, dst_crs=None):
    """Window-read COGs over bbox (lon/lat) and mosaic them; optional reprojection."""
    import rasterio
    from rasterio.merge import merge
    from rasterio.warp import transform_bounds
    srcs = [rasterio.open("/vsicurl/" + u) for u in urls]
    b = transform_bounds("EPSG:4326", srcs[0].crs, *bbox, densify_pts=21)
    arr, tr = merge(srcs, bounds=b)
    prof = srcs[0].profile.copy()
    prof.update(driver="GTiff", height=arr.shape[1], width=arr.shape[2], transform=tr, compress="deflate",
                tiled=True, blockxsize=256, blockysize=256)
    for s in srcs:
        s.close()
    with rasterio.open(out, "w", **prof) as dst:
        dst.write(arr)
    print("wrote", out, arr.shape[1:])
    return out


def _date(s):
    return dt.date.fromisoformat(s)


# ------------------------------------------------------------- Sentinel-1

def s1_tiles(bbox):
    """DE Africa s1_rtc 1x1 degree tile names (lower-left corner) covering bbox."""
    w, s, e, n = bbox
    out = []
    for lat in range(math.floor(s), math.ceil(n)):
        for lon in range(math.floor(w), math.ceil(e)):
            out.append(f"{'N' if lat >= 0 else 'S'}{abs(lat):02d}{'E' if lon >= 0 else 'W'}{abs(lon):03d}")
    return out


def s1_scenes(tile, start, end):
    """[(date, product_id, metadata dict)] for one tile between two dates."""
    out = []
    d = start.replace(day=1)
    months = []
    while d <= end:
        months.append(d)
        d = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    for m in months:
        days, _ = s3_list(S1_BUCKET, f"s1_rtc/{tile}/{m.year}/{m.month:02d}/")
        for dp in days:
            day = _date(f"{m.year}-{m.month:02d}-{dp.rstrip('/').split('/')[-1]}")
            if not (start <= day <= end):
                continue
            pids, _ = s3_list(S1_BUCKET, dp)
            for pp in pids:
                pid = pp.rstrip("/").split("/")[-1]
                meta = json.loads(_get(f"{S1_BUCKET}/{pp}s1_rtc_{pid}_{tile}_{day:%Y_%m_%d}_metadata.json"))
                out.append((day, pid, meta))
    return out


def _tile_pids(tiles, day, pid):
    """The product id of the same pass in each tile (usually identical);
    tiles the pass does not reach are skipped."""
    out = []
    for t in tiles:
        pids = [x.rstrip("/").split("/")[-1] for x in s3_list(S1_BUCKET, f"s1_rtc/{t}/{day:%Y/%m/%d}/")[0]]
        if pid in pids:
            out.append((t, pid))
        elif pids:
            out.append((t, pids[0]))
    return out


def fetch_s1(bbox, event_date, out, days_after=12, baseline_start=None, baseline_end=None, max_baseline=3,
             bands=("VV",)):
    """Event scene = first pass on/after the event date (within days_after);
    baseline = up to max_baseline earlier passes on the SAME relative orbit in
    the baseline window (default: 90 to 20 days before the event)."""
    ev = _date(event_date)
    bs = _date(baseline_start) if baseline_start else ev - dt.timedelta(days=90)
    be = _date(baseline_end) if baseline_end else ev - dt.timedelta(days=20)
    tiles = s1_tiles(bbox)
    ref = tiles[0]
    events = s1_scenes(ref, ev, ev + dt.timedelta(days=days_after))
    if not events:
        raise SystemExit(f"no Sentinel-1 pass over {ref} between {ev} and +{days_after} days")
    day, pid, meta = events[0]
    orbit = meta["properties"].get("sat:relative_orbit")
    base = [x for x in s1_scenes(ref, bs, be) if x[2]["properties"].get("sat:relative_orbit") == orbit]
    base = base[-max_baseline:]
    os.makedirs(os.path.join(out, "s1"), exist_ok=True)
    written = {"event": [], "baseline": []}
    with _env():
        for role, scenes in (("event", [(day, pid, meta)]), ("baseline", base)):
            for d, p, _ in scenes:
                for band in bands:
                    urls = [f"{S1_BUCKET}/s1_rtc/{t}/{d:%Y/%m/%d}/{q}/s1_rtc_{q}_{t}_{d:%Y_%m_%d}_{band}.tif"
                            for t, q in _tile_pids(tiles, d, p)]
                    written[role].append(clip_mosaic(urls, os.path.join(out, "s1", f"S1_{band}_{d:%Y%m%d}.tif"), bbox))
    print(f"relative orbit {orbit}; event {day}; baseline {[str(b[0]) for b in base]}")
    return written


# --------------------------------------------------------------- OPERA DSWx

DSWX_SHORT_NAMES = {"hls": "OPERA_L3_DSWX-HLS_V1", "s1": "OPERA_L3_DSWX-S1_V1"}


def fetch_dswx(bbox, event_date, out, product="hls", days_after=10, baseline_start=None, baseline_end=None):
    """Search and download OPERA DSWx WTR layers with earthaccess, then mosaic
    each date onto one UTM grid at 30 m. UNTESTED: CMR/PO.DAAC were blocked
    from the build sandbox. Needs `pip install earthaccess` and an Earthdata
    login (~/.netrc or EARTHDATA_USERNAME/PASSWORD)."""
    import earthaccess
    import rasterio
    from rasterio.vrt import WarpedVRT
    from rasterio.warp import transform_bounds
    from rasterio.transform import from_origin
    earthaccess.login()
    ev = _date(event_date)
    windows = {"event": (ev, ev + dt.timedelta(days=days_after)),
               "baseline": (_date(baseline_start) if baseline_start else ev - dt.timedelta(days=60),
                            _date(baseline_end) if baseline_end else ev - dt.timedelta(days=15))}
    lon0 = (bbox[0] + bbox[2]) / 2
    lat0 = (bbox[1] + bbox[3]) / 2
    epsg = (32600 if lat0 >= 0 else 32700) + int((lon0 + 180) // 6) + 1
    x0, y0, x1, y1 = transform_bounds("EPSG:4326", f"EPSG:{epsg}", *bbox, densify_pts=21)
    tr = from_origin(math.floor(x0 / 30) * 30, math.ceil(y1 / 30) * 30, 30, 30)
    W, H = int(math.ceil((x1 - tr.c) / 30)), int(math.ceil((tr.f - y0) / 30))
    os.makedirs(os.path.join(out, "dswx"), exist_ok=True)
    written = {"event": [], "baseline": []}
    for role, (a, b) in windows.items():
        res = earthaccess.search_data(short_name=DSWX_SHORT_NAMES[product], bounding_box=tuple(bbox),
                                      temporal=(a.isoformat(), b.isoformat()))
        by_date = {}
        for g in res:
            for link in g.data_links():
                if link.endswith("_B01_WTR.tif"):
                    d = re.search(r"_(\d{8})T\d{6}Z_", link).group(1)
                    by_date.setdefault(d, []).append(link)
        for d, links in sorted(by_date.items()):
            files = earthaccess.download(links, local_path=os.path.join(out, "dswx", "granules"))
            mosaic = np.full((H, W), 255, np.uint8)
            for f in files:
                with rasterio.open(f) as src, WarpedVRT(src, crs=f"EPSG:{epsg}", transform=tr, width=W, height=H,
                                                        nodata=255, resampling=0) as v:
                    a_ = v.read(1)
                    take = (mosaic == 255) | ((mosaic >= 250) & (a_ < 250))
                    mosaic[take] = a_[take]
            p = os.path.join(out, "dswx", f"DSWx_{product.upper()}_WTR_{d}.tif")
            with rasterio.open(p, "w", driver="GTiff", width=W, height=H, count=1, dtype="uint8", nodata=255,
                               crs=f"EPSG:{epsg}", transform=tr, compress="deflate") as dst:
                dst.write(mosaic, 1)
            written[role].append(p)
            print("wrote", p, f"({len(files)} granules)")
    return written


# ------------------------------------------------------- cropland, water

def worldcover_tiles(bbox, year=2021):
    w, s, e, n = bbox
    v = "v200" if year == 2021 else "v100"
    out = []
    for lat in range(math.floor(s / 3) * 3, math.ceil(n / 3) * 3, 3):
        for lon in range(math.floor(w / 3) * 3, math.ceil(e / 3) * 3, 3):
            t = f"{'N' if lat >= 0 else 'S'}{abs(lat):02d}{'E' if lon >= 0 else 'W'}{abs(lon):03d}"
            out.append(f"{WC_BUCKET}/{v}/{year}/map/ESA_WorldCover_10m_{year}_{v}_{t}_Map.tif")
    return out


def dea_tiles(bbox):
    """Digital Earth Africa 96 km tiles (EPSG:6933) covering bbox, as 'x215y076'."""
    from pyproj import Transformer
    t = Transformer.from_crs(4326, 6933, always_xy=True)
    xs, ys = t.transform([bbox[0], bbox[2], bbox[0], bbox[2]], [bbox[1], bbox[1], bbox[3], bbox[3]])
    ix = range(int((min(xs) + 17376000) // 96000), int((max(xs) + 17376000) // 96000) + 1)
    iy = range(int((min(ys) + 7392000) // 96000), int((max(ys) + 7392000) // 96000) + 1)
    return [f"x{x:03d}y{y:03d}" for x in ix for y in iy]


def fetch_cropland(bbox, out, source="worldcover", region="eastern"):
    os.makedirs(out, exist_ok=True)
    with _env():
        if source == "worldcover":
            return clip_mosaic(worldcover_tiles(bbox), os.path.join(out, "worldcover_2021_v200.tif"), bbox)
        urls = [f"{DEA_BUCKET}/crop_mask/{region}/{t[:4]}/{t[4:]}/2019--P1Y/crop_mask_{t}_2019--P1Y_filtered.tif"
                for t in dea_tiles(bbox)]
        return clip_mosaic(urls, os.path.join(out, "deafrica_cropmask_2019.tif"), bbox)


def fetch_permanent(bbox, out, period="1984--P41Y"):
    os.makedirs(out, exist_ok=True)
    urls = [f"{DEA_BUCKET}/wofs_ls_summary_alltime/1-0-0/{t[:4]}/{t[4:]}/{period}/wofs_ls_summary_alltime_{t}_{period}_frequency.tif"
            for t in dea_tiles(bbox)]
    with _env():
        return clip_mosaic(urls, os.path.join(out, "wofs_alltime_frequency.tif"), bbox)


# -------------------------------------------------------------- zones

def fetch_zones(bbox, out, country, level="county"):
    """Admin areas from Overture Maps (division_area). For Kenya, 'region' =
    the 47 counties and 'county' = sub-counties; other countries map their
    levels differently, so check the names."""
    import pyarrow.compute as pc
    import pyarrow.dataset as ds
    import pyarrow.fs as pfs
    from shapely import wkb
    from shapely.geometry import box, mapping
    kw = dict(anonymous=True, region="us-west-2")
    if os.environ.get("HTTPS_PROXY"):
        kw["proxy_options"] = os.environ["HTTPS_PROXY"]
        if os.path.exists(CA):
            kw["tls_ca_file_path"] = CA
    d = ds.dataset(f"overturemaps-us-west-2/release/{OVERTURE_RELEASE}/theme=divisions/type=division_area/",
                   filesystem=pfs.S3FileSystem(**kw), format="parquet")
    w, s, e, n = bbox
    f = ((pc.field("country") == country) & (pc.field("subtype") == level)
         & (pc.field("bbox", "xmin") < e) & (pc.field("bbox", "xmax") > w)
         & (pc.field("bbox", "ymin") < n) & (pc.field("bbox", "ymax") > s))
    aoi = box(*bbox)
    feats = []
    for r in d.to_table(columns=["id", "names", "subtype", "region", "geometry"], filter=f).to_pylist():
        g = wkb.loads(r["geometry"])
        if g.intersects(aoi):
            feats.append({"type": "Feature", "geometry": mapping(g),
                          "properties": {"name": r["names"]["primary"], "overture_id": r["id"], "subtype": level,
                                         "region": r["region"]}})
    os.makedirs(out, exist_ok=True)
    p = os.path.join(out, f"zones_{country}_{level}.geojson")
    with open(p, "w") as fh:
        json.dump({"type": "FeatureCollection", "features": feats}, fh)
    print("wrote", p, len(feats), "zones")
    return p


def fetch_fewsnet(out, country, url=None):
    """FEWS NET livelihood zones as GeoJSON from the FEWS NET Data Warehouse.
    UNTESTED (fdw.fews.net was blocked from the sandbox); the endpoint and
    parameters follow the public FDW API docs and may need adjusting. If it
    fails, download the livelihood-zone shapefile for the country from
    https://fews.net/data/geographic-boundaries and pass it with --zones
    (shapefiles need fiona)."""
    url = url or f"https://fdw.fews.net/api/feature/?format=geojson&unit_type=livelihood_zone&country_code={country}"
    data = json.loads(_get(url))
    os.makedirs(out, exist_ok=True)
    p = os.path.join(out, f"fewsnet_lhz_{country}.geojson")
    with open(p, "w") as fh:
        json.dump(data, fh)
    print("wrote", p, len(data.get("features", [])), "zones")
    return p


def main(argv=None):
    ap = argparse.ArgumentParser(prog="floodcrop.fetch")
    ap.add_argument("what", choices=["s1", "dswx", "cropland", "permanent", "zones", "fewsnet"])
    ap.add_argument("--bbox", nargs=4, type=float, metavar=("W", "S", "E", "N"))
    ap.add_argument("--event-date")
    ap.add_argument("--days-after", type=int, default=12)
    ap.add_argument("--baseline-start")
    ap.add_argument("--baseline-end")
    ap.add_argument("--product", default="hls", choices=["hls", "s1"])
    ap.add_argument("--source", default="worldcover", choices=["worldcover", "deafrica"])
    ap.add_argument("--region", default="eastern", help="DE Africa crop mask region: eastern, western, northern, "
                    "southern, central, sahel, south_eastern, indian_ocean")
    ap.add_argument("--country", help="ISO 3166-1 alpha-2, e.g. KE")
    ap.add_argument("--level", default="county", help="Overture subtype: region, county, localadmin")
    ap.add_argument("--url", help="fewsnet: override the API URL")
    ap.add_argument("--out", default="data")
    a = ap.parse_args(argv)
    if a.what == "s1":
        fetch_s1(a.bbox, a.event_date, a.out, a.days_after, a.baseline_start, a.baseline_end)
    elif a.what == "dswx":
        fetch_dswx(a.bbox, a.event_date, a.out, a.product, a.days_after, a.baseline_start, a.baseline_end)
    elif a.what == "cropland":
        fetch_cropland(a.bbox, a.out, a.source, a.region)
    elif a.what == "permanent":
        fetch_permanent(a.bbox, a.out)
    elif a.what == "zones":
        fetch_zones(a.bbox, a.out, a.country, a.level)
    else:
        fetch_fewsnet(a.out, a.country, a.url)


if __name__ == "__main__":
    main()
