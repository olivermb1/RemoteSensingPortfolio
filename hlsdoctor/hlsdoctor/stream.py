"""Open a remote HLS COG the way GDAL, rasterio and QGIS do, read one block,
and turn GDAL's error messages into plain words."""

import os
import time

from .env import GDAL_RECOMMENDED


def explain_gdal_error(msg):
    """(kind, plain words) for a GDAL / curl error message."""
    m = (msg or "").lower()
    if "401" in m:
        return "auth", "the server answered 401: the Earthdata login was missing or wrong"
    if "not recognized as" in m and "supported file format" in m:
        return "html", ("GDAL got a web page instead of a GeoTIFF, almost always the Earthdata login page: "
                        "GDAL didn't send your login (no ~/.netrc entry, GDAL_HTTP_NETRC=NO, or on Windows a missing _netrc)")
    if "403" in m:
        return "forbidden", ("the server answered 403: the login was accepted but access was refused. Usual causes: "
                             "an s3:// path used from outside AWS us-west-2, expired temporary S3 keys, or a token "
                             "sent along to S3")
    if "400" in m or "only one auth mechanism" in m:
        return "bearer-s3", ("the server answered 400, which here usually means a token header was passed on to the "
                             "signed S3 address after the redirect (S3 refuses two kinds of login at once). Use "
                             "~/.netrc with a cookie jar for GDAL instead of GDAL_HTTP_HEADERS")
    if "404" in m or "does not exist in the file system" in m:
        return "notfound", "the file was not found (wrong or outdated address)"
    if "resolve host" in m:
        return "dns", "the computer couldn't look up the server name (no internet, or DNS blocked)"
    if "ssl" in m or "certificate" in m:
        return "tls", ("a certificate check failed, usually a company proxy that re-signs HTTPS; set CURL_CA_BUNDLE "
                       "to your organisation's CA bundle")
    if "timed out" in m or "timeout" in m:
        return "timeout", "the connection timed out"
    return "other", msg or "unknown error"


def _backend(prefer=None):
    if prefer in (None, "gdal"):
        try:
            from osgeo import gdal  # noqa: F401
            return "gdal"
        except Exception:  # noqa: BLE001
            if prefer == "gdal":
                return None
    try:
        import rasterio  # noqa: F401
        return "rasterio"
    except Exception:  # noqa: BLE001
        return None


def open_and_read(path, config=None, backend=None):
    """Open path (a /vsicurl/ or /vsis3/ path, or a local file), read one block
    of band 1, and return a dict: ok, seconds, error, kind, explain, info."""
    config = dict(config or {})
    # GDAL caches remote reads, failures included, for the life of the process;
    # turn that off for this path so a second try is a real second try.
    if path.startswith("/vsi"):
        config.setdefault("CPL_VSIL_CURL_NON_CACHED", path)
    be = _backend(backend)
    if be is None:
        return {"ok": False, "kind": "nogdal", "error": "neither GDAL nor rasterio is installed",
                "explain": "install rasterio", "seconds": 0.0, "backend": None}
    t0 = time.time()
    try:
        info = _read_gdal(path, config) if be == "gdal" else _read_rasterio(path, config)
        return {"ok": True, "seconds": time.time() - t0, "info": info, "backend": be}
    except Exception as e:  # noqa: BLE001 - every failure is reported, not raised
        kind, words = explain_gdal_error(str(e))
        return {"ok": False, "seconds": time.time() - t0, "error": str(e), "kind": kind,
                "explain": words, "backend": be}


def _read_gdal(path, config):
    from osgeo import gdal

    old = {k: gdal.GetConfigOption(k) for k in config}
    for k, v in config.items():
        gdal.SetConfigOption(k, v)
    gdal.PushErrorHandler("CPLQuietErrorHandler")
    try:
        gdal.ErrorReset()
        ds = gdal.Open(path)
        if ds is None:
            raise RuntimeError(gdal.GetLastErrorMsg() or f"could not open {path}")
        b = ds.GetRasterBand(1)
        bx, by = b.GetBlockSize()
        data = b.ReadRaster(0, 0, min(bx, ds.RasterXSize), min(by, ds.RasterYSize))
        if data is None:
            raise RuntimeError(gdal.GetLastErrorMsg() or "read failed")
        return {"size": (ds.RasterXSize, ds.RasterYSize), "block": (bx, by),
                "overviews": b.GetOverviewCount(), "nodata": b.GetNoDataValue(),
                "scale": b.GetScale(), "offset": b.GetOffset()}
    finally:
        gdal.PopErrorHandler()
        for k, v in old.items():
            gdal.SetConfigOption(k, v)


def _read_rasterio(path, config):
    import rasterio
    from rasterio.windows import Window

    with rasterio.Env(**config), rasterio.open(path) as src:
        by, bx = src.block_shapes[0]
        src.read(1, window=Window(0, 0, min(bx, src.width), min(by, src.height)))
        return {"size": (src.width, src.height), "block": (bx, by),
                "overviews": len(src.overviews(1)), "nodata": src.nodata,
                "scale": src.scales[0], "offset": src.offsets[0]}


def recommended_config(token=None):
    cfg = dict(GDAL_RECOMMENDED)
    for k in ("GDAL_HTTP_COOKIEFILE", "GDAL_HTTP_COOKIEJAR"):
        cfg[k] = os.environ.get(k, cfg[k])
    if token:
        cfg["GDAL_HTTP_HEADERS"] = f"Authorization: Bearer {token}"
    return cfg
