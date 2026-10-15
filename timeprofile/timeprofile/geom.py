"""Features (points and polygons in lon/lat), pixel selection, and MGRS tile names.
numpy only, so it runs inside QGIS without extra packages."""

import json
import math

import numpy as np


def feature(name, geom):
    """A feature dict from a GeoJSON geometry (lon/lat)."""
    t = geom["type"]
    c = geom["coordinates"]
    if t == "Point":
        return {"name": name, "kind": "point", "coords": (float(c[0]), float(c[1]))}
    if t == "Polygon":
        return {"name": name, "kind": "polygon", "coords": [c]}
    if t == "MultiPolygon":
        return {"name": name, "kind": "polygon", "coords": list(c)}
    if t == "MultiPoint" and len(c) == 1:
        return feature(name, {"type": "Point", "coordinates": c[0]})
    raise ValueError(f"{name}: {t} geometries are not supported (use points or polygons)")


def load_geojson(path, name_field=None):
    """Features from a GeoJSON file in lon/lat. Names come from name_field, a 'name'
    property, or the feature's position."""
    with open(path) as fh:
        gj = json.load(fh)
    feats = gj["features"] if gj.get("type") == "FeatureCollection" else [gj]
    out = []
    for i, f in enumerate(feats, 1):
        props = f.get("properties") or {}
        name = props.get(name_field) if name_field else (props.get("name") or props.get("Name"))
        out.append(feature(str(name if name not in (None, "") else f"feature {i}"), f["geometry"]))
    names = [f["name"] for f in out]
    if len(set(names)) < len(names):  # keep series apart
        seen = {}
        for f in out:
            seen[f["name"]] = seen.get(f["name"], 0) + 1
            if names.count(f["name"]) > 1:
                f["name"] = f"{f['name']} #{seen[f['name']]}"
    return out


def parse_point(text, i=1):
    """'lon,lat' or 'lon,lat,name' -> point feature."""
    parts = [p.strip() for p in text.split(",")]
    if len(parts) < 2:
        raise ValueError(f"point '{text}' should be lon,lat[,name]")
    name = ",".join(parts[2:]) or f"point {i}"
    return {"name": name, "kind": "point", "coords": (float(parts[0]), float(parts[1]))}


def lonlat_bounds(features, pad=0.0):
    xs, ys = [], []
    for f in features:
        if f["kind"] == "point":
            xs.append(f["coords"][0])
            ys.append(f["coords"][1])
        else:
            for poly in f["coords"]:
                for ring in poly:
                    xs += [p[0] for p in ring]
                    ys += [p[1] for p in ring]
    return min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad


def inside(px, py, rings):
    """Even-odd point-in-polygon for arrays of points; rings = outer ring + holes."""
    res = np.zeros(px.shape, bool)
    for ring in rings:
        r = np.asarray(ring, float)
        x1, y1 = r[:, 0], r[:, 1]
        x2, y2 = np.roll(x1, -1), np.roll(y1, -1)
        for a, b, c, d in zip(x1, y1, x2, y2):
            if b == d:
                continue
            cross = (b > py) != (d > py)
            xint = a + (py - b) * (c - a) / (d - b)
            res ^= cross & (px < xint)
    return res


def pixels(feat, gt, width, height, to_crs, buffer=0):
    """Pixels of a raster grid that a feature selects.

    Points: the pixel under the point, plus `buffer` pixels around it.
    Polygons: pixels whose centres fall inside; a polygon smaller than one pixel
    gets the pixel under its first vertex's ring centroid.
    Returns (rows, cols, how) with how in {'point', 'inside', 'centroid'}, or None if outside.
    """
    x0, dx, _, y0, _, dy = gt
    if feat["kind"] == "point":
        xs, ys = to_crs([feat["coords"][0]], [feat["coords"][1]])
        c, r = int(math.floor((xs[0] - x0) / dx)), int(math.floor((ys[0] - y0) / dy))
        rr, cc = np.mgrid[r - buffer:r + buffer + 1, c - buffer:c + buffer + 1]
        rr, cc = rr.ravel(), cc.ravel()
        ok = (rr >= 0) & (rr < height) & (cc >= 0) & (cc < width)
        if not (0 <= r < height and 0 <= c < width):
            return None
        return rr[ok], cc[ok], "point"
    polys = []
    for poly in feat["coords"]:
        rings = []
        for ring in poly:
            lon, lat = zip(*[(p[0], p[1]) for p in ring])
            xs, ys = to_crs(lon, lat)
            rings.append(np.column_stack([xs, ys]))
        polys.append(rings)
    allpts = np.vstack([r for p in polys for r in p])
    c0 = max(int(math.floor((allpts[:, 0].min() - x0) / dx)), 0)
    c1 = min(int(math.floor((allpts[:, 0].max() - x0) / dx)), width - 1)
    ya, yb = (allpts[:, 1].max(), allpts[:, 1].min()) if dy < 0 else (allpts[:, 1].min(), allpts[:, 1].max())
    r0 = max(int(math.floor((ya - y0) / dy)), 0)
    r1 = min(int(math.floor((yb - y0) / dy)), height - 1)
    if c0 > c1 or r0 > r1:
        return None
    rr, cc = np.mgrid[r0:r1 + 1, c0:c1 + 1]
    px, py = x0 + (cc + 0.5) * dx, y0 + (rr + 0.5) * dy
    sel = np.zeros(px.shape, bool)
    for rings in polys:
        sel |= inside(px, py, rings)
    if sel.any():
        return rr[sel], cc[sel], "inside"
    outer = polys[0][0]
    cx, cy = outer[:-1, 0].mean() if len(outer) > 1 else outer[0, 0], outer[:-1, 1].mean() if len(outer) > 1 else outer[0, 1]
    c, r = int(math.floor((cx - x0) / dx)), int(math.floor((cy - y0) / dy))
    if 0 <= r < height and 0 <= c < width:
        return np.array([r]), np.array([c]), "centroid"
    return None


# --- MGRS 100 km tile names (for finding Sentinel-2 / HLS tiles) ---------------------

_BANDS = "CDEFGHJKLMNPQRSTUVWX"
_COLS = ("ABCDEFGH", "JKLMNPQR", "STUVWXYZ")
_ROWS = "ABCDEFGHJKLMNPQRSTUV"


def utm(lon, lat, zone=None):
    """(zone, easting, northing) on WGS 84, northing with a 10,000 km false northing south of the equator."""
    zone = zone or int((lon + 180) // 6) + 1
    a, f = 6378137.0, 1 / 298.257223563
    k0, e2 = 0.9996, f * (2 - f)
    ep2 = e2 / (1 - e2)
    phi, lam = math.radians(lat), math.radians(lon - (zone * 6 - 183))
    n = a / math.sqrt(1 - e2 * math.sin(phi) ** 2)
    t, c = math.tan(phi) ** 2, ep2 * math.cos(phi) ** 2
    A = math.cos(phi) * lam
    m = a * ((1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256) * phi
             - (3 * e2 / 8 + 3 * e2 ** 2 / 32 + 45 * e2 ** 3 / 1024) * math.sin(2 * phi)
             + (15 * e2 ** 2 / 256 + 45 * e2 ** 3 / 1024) * math.sin(4 * phi)
             - (35 * e2 ** 3 / 3072) * math.sin(6 * phi))
    x = k0 * n * (A + (1 - t + c) * A ** 3 / 6 + (5 - 18 * t + t * t + 72 * c - 58 * ep2) * A ** 5 / 120) + 500000
    y = k0 * (m + n * math.tan(phi) * (A * A / 2 + (5 - t + 9 * c + 4 * c * c) * A ** 4 / 24
                                       + (61 - 58 * t + t * t + 600 * c - 330 * ep2) * A ** 6 / 720))
    if lat < 0:
        y += 10_000_000
    return zone, x, y


def mgrs_tile(lon, lat):
    """MGRS 100 km square, e.g. '37MCV' (no Norway/Svalbard exceptions; fine for Africa)."""
    zone, e, n = utm(lon, lat)
    band = _BANDS[min(max(int((lat + 80) // 8), 0), len(_BANDS) - 1)]
    col = _COLS[(zone - 1) % 3][int(e // 100000) - 1]
    row = _ROWS[(int(n // 100000) + (5 if zone % 2 == 0 else 0)) % 20]
    return f"{zone:02d}{band}{col}{row}"


def mgrs_tiles(bbox, step=0.05):
    """Tiles whose canonical 100 km square contains part of bbox (W, S, E, N)."""
    w, s, e, n = bbox
    nx, ny = max(int((e - w) / step), 1), max(int((n - s) / step), 1)
    return sorted({mgrs_tile(w + (e - w) * i / nx, s + (n - s) * j / ny)
                   for i in range(nx + 1) for j in range(ny + 1)})
