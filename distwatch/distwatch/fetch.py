"""Find and download DIST-ALERT granules from NASA CMR / LP DAAC.

Needs a free NASA Earthdata login, either in ~/.netrc
(machine urs.earthdata.nasa.gov login USER password PASS) or as a bearer
token in the EARTHDATA_TOKEN environment variable.

Untested against the live service: NASA CMR was not reachable where this was
written. The search uses CMR's public granules.json endpoint.
"""

import datetime as dt
import json
import os
import time

import requests

from . import products as P

CMR = "https://cmr.earthdata.nasa.gov/search/granules.json"


def session():
    """A requests session for LP DAAC downloads.

    With ~/.netrc, requests re-applies the netrc login at each redirect host
    (LP DAAC, then URS), which is what the Earthdata login flow needs. A bearer
    token is sent to LP DAAC; requests drops it at the redirect to the signed
    S3 URL, which would refuse it.
    """
    s = requests.Session()
    tok = os.environ.get("EARTHDATA_TOKEN")
    if tok:
        s.headers["Authorization"] = f"Bearer {tok}"
    return s


def bbox_of(areas_path, pad=0.0):
    with open(areas_path) as f:
        fc = json.load(f)
    xs, ys = [], []

    def walk(c):
        if isinstance(c[0], (int, float)):
            xs.append(c[0])
            ys.append(c[1])
        else:
            for x in c:
                walk(x)
    for feat in fc["features"]:
        walk(feat["geometry"]["coordinates"])
    return (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)


def search(bbox, start, end=None, collection=P.COLLECTION, page_size=500, log=print):
    """List granules over bbox (W, S, E, N) sensed between start and end."""
    end = end or dt.date.today().isoformat()
    params = {"short_name": collection, "bounding_box": ",".join(f"{v:.5f}" for v in bbox),
              "temporal": f"{start}T00:00:00Z,{end}T23:59:59Z", "page_size": page_size,
              "sort_key": "-start_date"}
    out, headers = [], {}
    while True:
        r = requests.get(CMR, params=params, headers=headers, timeout=60)
        r.raise_for_status()
        entries = r.json()["feed"]["entry"]
        for e in entries:
            links = [l["href"] for l in e.get("links", []) if l.get("href", "").endswith(".tif")
                     and l["href"].startswith("https")]
            out.append({"id": e.get("producer_granule_id") or e["title"], "time": e["time_start"], "links": links})
        nxt = r.headers.get("CMR-Search-After")
        if not nxt or len(entries) < page_size:
            break
        headers["CMR-Search-After"] = nxt
    log(f"CMR: {len(out)} granules")
    return out


def pick(granules, latest_only=True):
    """Newest granule per tile (DIST-ALERT is cumulative), or all of them."""
    best = {}
    for g in granules:
        p = next((P.parse_name(os.path.basename(u)) for u in g["links"] if P.parse_name(os.path.basename(u))), None)
        if not p:
            continue
        g = g | {"tile": p["tile"], "sensing": p["sensing"], "production": p["production"]}
        if not latest_only:
            best[g["id"]] = g
            continue
        cur = best.get(p["tile"])
        if cur is None or (g["sensing"], g["production"]) > (cur["sensing"], cur["production"]):
            best[p["tile"]] = g
    return list(best.values())


def download(granules, dest, layers=P.LAYERS, sess=None, retries=3, log=print):
    sess = sess or session()
    os.makedirs(dest, exist_ok=True)
    paths = []
    for g in granules:
        for url in g["links"]:
            p = P.parse_name(os.path.basename(url))
            if not p or p["layer"] not in layers:
                continue
            path = os.path.join(dest, os.path.basename(url))
            if os.path.exists(path) and os.path.getsize(path) > 0:
                paths.append(path)
                continue
            for attempt in range(retries):
                try:
                    with sess.get(url, stream=True, timeout=120) as r:
                        if r.status_code == 401:
                            raise SystemExit("Earthdata login refused. Check ~/.netrc or EARTHDATA_TOKEN.")
                        r.raise_for_status()
                        tmp = path + ".part"
                        with open(tmp, "wb") as f:
                            for chunk in r.iter_content(1 << 20):
                                f.write(chunk)
                        os.replace(tmp, path)
                    break
                except requests.RequestException as e:
                    if attempt == retries - 1:
                        raise
                    log(f"retrying {os.path.basename(url)}: {e}")
                    time.sleep(2 ** (attempt + 1))
            log(f"got {os.path.basename(path)}")
            paths.append(path)
    return paths
