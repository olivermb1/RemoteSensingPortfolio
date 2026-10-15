"""UTM and MGRS tile names, copied from tools/timeprofile (no extra dependency)."""

import math


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
