"""Checks of the software on this machine: Python packages, GDAL, the GDAL
settings that streaming HLS needs, and proxy / certificate settings."""

import importlib
import os
import sys

from .report import FAIL, INFO, PASS, SKIP, WARN, Result

# The GDAL settings that make /vsicurl/ reads of LP DAAC files work and stay
# fast. Cookies matter most: without a cookie jar every range request goes
# through the Earthdata Login redirect again.
COOKIE = os.path.join(os.path.expanduser("~"), ".hlsdoctor_cookies.txt")
GDAL_RECOMMENDED = {
    "GDAL_HTTP_NETRC": "YES",
    "GDAL_HTTP_COOKIEFILE": COOKIE,
    "GDAL_HTTP_COOKIEJAR": COOKIE,
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": "TIF",
    "GDAL_HTTP_MAX_RETRY": "4",
    "GDAL_HTTP_RETRY_DELAY": "2",
}


def _version(mod):
    try:
        m = importlib.import_module(mod)
    except Exception:  # noqa: BLE001 - any import failure means "not usable"
        return None
    return getattr(m, "__version__", "installed")


def gdal_versions():
    """{'osgeo': 'x.y.z' or None, 'rasterio': 'x.y.z' or None} (rasterio's own GDAL)."""
    out = {"osgeo": None, "rasterio": None}
    try:
        from osgeo import gdal
        out["osgeo"] = gdal.__version__
    except Exception:  # noqa: BLE001
        pass
    try:
        import rasterio
        out["rasterio"] = rasterio.__gdal_version__
    except Exception:  # noqa: BLE001
        pass
    return out


def _vt(v):
    try:
        return tuple(int(x) for x in v.split(".")[:2])
    except (AttributeError, ValueError):
        return (0, 0)


def check_python():
    v = sys.version_info
    if v < (3, 9):
        return Result("python", "Python version", WARN, f"Python {v.major}.{v.minor}.",
                      "earthaccess needs Python 3.9 or newer; install a current Python or use conda.")
    return Result("python", "Python version", PASS, f"Python {v.major}.{v.minor}.{v.micro} ({sys.executable}).")


def check_packages():
    found = {m: _version(m) for m in ("earthaccess", "rasterio", "pyproj", "requests", "numpy")}
    g = gdal_versions()
    have = ", ".join(f"{k} {v}" for k, v in found.items() if v)
    missing = [k for k, v in found.items() if not v]
    if g["osgeo"]:
        have += f", GDAL Python bindings {g['osgeo']}"
    detail = f"Found: {have or 'none of them'}."
    if missing:
        detail += f" Not installed: {', '.join(missing)}."
    if not found["rasterio"] and not g["osgeo"]:
        return Result("packages", "Python packages", WARN, detail + " Without rasterio or GDAL you can search and "
                      "download whole files but not stream parts of them.",
                      "pip install earthaccess rasterio  (or: conda install -c conda-forge earthaccess rasterio)",
                      data=found)
    if not found["earthaccess"]:
        return Result("packages", "Python packages", INFO, detail + " earthaccess is optional for this doctor, "
                      "but it is the easiest way to search and log in.",
                      "pip install earthaccess", data=found)
    return Result("packages", "Python packages", PASS, detail, data=found)


def check_gdal():
    g = gdal_versions()
    if not g["osgeo"] and not g["rasterio"]:
        return Result("gdal", "GDAL for streaming", SKIP, "No GDAL found (neither rasterio nor osgeo).")
    notes, status = [], PASS
    for name, v in g.items():
        if v and _vt(v) < (3, 6):
            status = WARN
            notes.append(f"{name} uses GDAL {v}; GDAL 3.6 or newer is needed to send a token with GDAL_HTTP_HEADERS, "
                         "and older builds retry less well")
    if g["osgeo"] and g["rasterio"] and g["osgeo"] != g["rasterio"]:
        status = WARN if status == PASS else status
        notes.append(f"two GDALs are installed: the osgeo bindings ({g['osgeo']}) and rasterio's own copy "
                     f"({g['rasterio']}). Settings made with gdal.SetConfigOption() don't reach rasterio and the "
                     "other way round; set them as environment variables or inside rasterio.Env(...)")
    detail = "; ".join(f"{k}: GDAL {v}" for k, v in g.items() if v) + "."
    if notes:
        detail += " " + "; ".join(notes) + "."
    return Result("gdal", "GDAL for streaming", status, detail,
                  "pip install -U rasterio  (wheels bundle a current GDAL)" if status == WARN else "",
                  "two-gdals" if len([v for v in g.values() if v]) == 2 else "", data=g)


def check_gdal_env(environ=None):
    """The GDAL settings currently in the environment versus what HLS needs."""
    environ = os.environ if environ is None else environ
    title = "GDAL settings for streaming HLS"
    bad, missing = [], []
    if environ.get("GDAL_HTTP_NETRC", "YES").upper() in ("NO", "FALSE", "OFF", "0"):
        bad.append("GDAL_HTTP_NETRC is NO, so GDAL won't send your Earthdata login")
    if environ.get("GDAL_HTTP_UNSAFESSL", "").upper() in ("YES", "TRUE", "ON", "1"):
        bad.append("GDAL_HTTP_UNSAFESSL is YES, which turns off certificate checks; fix the CA bundle instead")
    if environ.get("AWS_NO_SIGN_REQUEST", "").upper() in ("YES", "TRUE"):
        bad.append("AWS_NO_SIGN_REQUEST is YES; LP DAAC s3:// paths need signed requests, so /vsis3/ reads of HLS will fail")
    for k in ("GDAL_HTTP_COOKIEFILE", "GDAL_HTTP_COOKIEJAR", "GDAL_DISABLE_READDIR_ON_OPEN"):
        if not environ.get(k):
            missing.append(k)
    lines = [f"{k}={v}" for k, v in GDAL_RECOMMENDED.items()]
    fix = ("Set these before starting Python or QGIS (in QGIS: Settings > Options > System > Environment):\n"
           + "\n".join(lines)
           + "\nIn Python with rasterio you can instead wrap reads in rasterio.Env(**hlsdoctor.env.GDAL_RECOMMENDED).")
    if bad:
        return Result("gdalenv", title, FAIL, "; ".join(bad) + ".", fix, "gdal-cookies")
    if missing:
        return Result("gdalenv", title, WARN,
                      f"Not set: {', '.join(missing)}. Without a cookie jar every piece GDAL reads goes through the "
                      "Earthdata Login redirect again (slow, and heavy use gets throttled); without "
                      "GDAL_DISABLE_READDIR_ON_OPEN, GDAL first tries to list the folder, which LP DAAC does not serve, so every open costs extra failed requests.",
                      fix, "gdal-cookies")
    return Result("gdalenv", title, PASS, "Cookie jar, netrc and directory-listing settings are in place.")


def check_tls_env(environ=None):
    environ = os.environ if environ is None else environ
    title = "Proxy and certificate settings"
    notes, bad = [], []
    for var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "GDAL_CURL_CA_BUNDLE"):
        p = environ.get(var)
        if p:
            if os.path.isfile(p):
                notes.append(f"{var}={p}")
            else:
                bad.append(f"{var} points to {p}, which does not exist")
    g, c = environ.get("GDAL_CURL_CA_BUNDLE"), environ.get("CURL_CA_BUNDLE")
    warn = []
    if g and c and os.path.abspath(g) != os.path.abspath(c):
        warn.append(f"GDAL_CURL_CA_BUNDLE ({g}) and CURL_CA_BUNDLE ({c}) differ; GDAL uses GDAL_CURL_CA_BUNDLE, "
                    "so GDAL and curl may trust different certificates")
    proxy = environ.get("HTTPS_PROXY") or environ.get("https_proxy")
    if proxy:
        notes.append("HTTPS_PROXY is set (traffic goes through a proxy)")
    if bad:
        return Result("tls", title, FAIL, "; ".join(bad) + ". Every HTTPS download will fail with a certificate error.",
                      "Point the variable at your organisation's CA bundle file, or unset it.", "tls")
    if warn:
        return Result("tls", title, WARN, "; ".join(warn + notes) + ".",
                      "Point both at the same CA bundle (your organisation's, if you are behind a company proxy).", "tls")
    if notes:
        return Result("tls", title, INFO, "; ".join(notes) + ".")
    return Result("tls", title, SKIP, "No proxy or custom certificate settings.")


def run_all(environ=None):
    return [check_python(), check_packages(), check_gdal(), check_gdal_env(environ), check_tls_env(environ)]
