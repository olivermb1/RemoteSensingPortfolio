"""A small Earthdata-aware HTTP client on the standard library only, so the
doctor runs in any Python, including the one inside QGIS.

It follows redirects by hand so every hop can be reported, sends the Earthdata
username and password only to the Earthdata Login host, sends a bearer token
only to the LP DAAC data host (never on to the signed S3 address), and keeps
cookies across hops the way a browser, curl or GDAL would."""

import base64
import os
import socket
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from http.cookiejar import CookieJar
from urllib.parse import urljoin

from . import endpoints as ep

UA = "hlsdoctor/0.1 (+https://github.com/olivermb1/RemoteSensingPortfolio)"


@dataclass
class Hop:
    url: str
    status: int
    sent_auth: str = ""   # "", "basic" or "bearer"


@dataclass
class Response:
    url: str
    status: int = 0
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    hops: list = field(default_factory=list)
    error: str = ""        # network error class when no HTTP answer came back
    error_text: str = ""
    seconds: float = 0.0

    @property
    def ok(self):
        return self.status in (200, 206)

    @property
    def content_type(self):
        return self.headers.get("content-type", "").lower()

    def text(self, n=2000):
        return self.body[:n].decode("utf-8", "replace")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def ca_file():
    """The CA bundle Python should trust, honouring the variables people set
    for requests, curl and GDAL behind company proxies."""
    for var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "GDAL_CURL_CA_BUNDLE"):
        p = os.environ.get(var)
        if p and os.path.isfile(p):
            return p
    return None


def _context():
    ctx = ssl.create_default_context()
    f = ca_file()
    if f:
        ctx.load_verify_locations(cafile=f)
    return ctx


def classify_error(exc):
    """(kind, text) for a failure that produced no HTTP status."""
    reason = getattr(exc, "reason", exc)
    text = str(reason)
    if isinstance(reason, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in text:
        return "tls", text
    if isinstance(reason, ssl.SSLError):
        return "tls", text
    if isinstance(reason, socket.gaierror) or "Name or service not known" in text or "nodename nor servname" in text:
        return "dns", text
    if "Tunnel connection failed" in text or "407" in text:
        return "proxy", text
    if isinstance(reason, (socket.timeout, TimeoutError)) or "timed out" in text:
        return "timeout", text
    if isinstance(reason, ConnectionRefusedError) or "refused" in text.lower():
        return "refused", text
    return "network", text


def fetch(url, creds=None, token=None, range_bytes=None, max_body=65536, timeout=20,
          jar=None, max_hops=10, method="GET"):
    """GET url, following redirects, and return a Response with every hop."""
    jar = jar if jar is not None else CookieJar()
    opener = urllib.request.build_opener(
        _NoRedirect(), urllib.request.HTTPCookieProcessor(jar),
        urllib.request.HTTPSHandler(context=_context()))
    hops, t0 = [], time.time()
    for _ in range(max_hops):
        req = urllib.request.Request(url, method=method, headers={"User-Agent": UA})
        if range_bytes:
            req.add_header("Range", f"bytes=0-{range_bytes - 1}")
        h, sent = ep.host(url), ""
        if creds and h == ep.URS_HOST:
            raw = f"{creds[0]}:{creds[1]}".encode()
            req.add_header("Authorization", "Basic " + base64.b64encode(raw).decode())
            sent = "basic"
        elif token and h == ep.DATA_HOST:
            req.add_header("Authorization", "Bearer " + token)
            sent = "bearer"
        try:
            resp = opener.open(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            resp = e
        except (urllib.error.URLError, OSError) as e:
            kind, text = classify_error(e)
            return Response(url, hops=hops, error=kind, error_text=text, seconds=time.time() - t0)
        status = resp.getcode() if hasattr(resp, "getcode") else resp.code
        headers = {k.lower(): v for k, v in resp.headers.items()}
        hops.append(Hop(url, status, sent))
        if status in (301, 302, 303, 307, 308) and "location" in headers:
            resp.close()
            url = urljoin(url, headers["location"])
            continue
        try:
            body = resp.read(max_body)
        except Exception:  # noqa: BLE001 - a cut-off body is still a useful answer
            body = b""
        resp.close()
        return Response(url, status, headers, body, hops, seconds=time.time() - t0)
    return Response(url, hops=hops, error="redirect_loop",
                    error_text=f"more than {max_hops} redirects", seconds=time.time() - t0)


TIFF_MAGIC = (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+")


def is_tiff(b):
    return b[:4] in TIFF_MAGIC


def looks_html(b):
    s = b[:512].lstrip().lower()
    return s.startswith(b"<!doctype html") or s.startswith(b"<html") or b"<html" in s[:200]


def looks_s3_error(b):
    s = b[:400]
    return s.lstrip().startswith(b"<?xml") and b"<Error>" in s
