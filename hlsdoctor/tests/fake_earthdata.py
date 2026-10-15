"""A local stand-in for NASA Earthdata Login, CMR, LP DAAC and S3, close
enough to the real redirect dance to test every failure the doctor explains.

Users: kodi/right works; noapp/right hasn't approved LP DAAC's application;
unconfirmed/right gets 403. Token "GOOD.TOKEN.X" (any 3-part string starting
GOOD) is accepted by the data host. Set FakeEarthdata.mode to "expired" to make
S3 refuse signed links as expired."""

import base64
import email.utils
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

TIF = os.path.join(os.path.dirname(__file__), "..", "demo", "files", "HLS.S30.T10TCT.2021345T191811.v2.0.B8A.tif")
GRANULE = "HLS.S30.T10TCT.2021345T191811.v2.0"


class FakeEarthdata:
    def __init__(self):
        self.mode = ""
        self.clock_skew = 0
        self.log = []
        self.servers = {}
        for role in ("urs", "data", "s3", "cmr"):
            # S3 gets its own address so that, as in real life, a netrc entry
            # for the login host doesn't match it
            ip = "127.0.0.2" if role == "s3" else "127.0.0.1"
            srv = ThreadingHTTPServer((ip, 0), self._handler(role))
            self.servers[role] = srv
            threading.Thread(target=srv.serve_forever, daemon=True).start()

    def url(self, role):
        ip, port = self.servers[role].server_address[:2]
        return f"http://{ip}:{port}"

    def close(self):
        for s in self.servers.values():
            s.shutdown()
            s.server_close()

    def patch(self, ep):
        """Point hlsdoctor.endpoints at this server."""
        ep.URS, ep.CMR, ep.DATA = self.url("urs"), self.url("cmr"), self.url("data")
        ep.S3CREDS = ep.DATA + "/s3credentials"
        ep.URS_HOST, ep.DATA_HOST = ep.host(ep.URS), ep.host(ep.DATA)

    def _handler(self, role):
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def send(self, code, body=b"", ctype="text/html", headers=()):
                if isinstance(body, str):
                    body = body.encode()
                self.send_response(code)
                self.send_header("Date", email.utils.formatdate(time.time() + fake.clock_skew, usegmt=True))
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                for k, v in headers:
                    self.send_header(k, v)
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)

            def basic(self):
                a = self.headers.get("Authorization", "")
                if not a.startswith("Basic "):
                    return None
                u, _, p = base64.b64decode(a[6:]).decode().partition(":")
                return u, p

            def do_HEAD(self):
                self.do_GET()

            def do_GET(self):
                u = urlparse(self.path)
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                fake.log.append((role, self.command, u.path, self.headers.get("Authorization", "")[:6]))
                try:
                    getattr(self, "get_" + role)(u, q)
                except Exception:  # pragma: no cover - show what broke in the fake itself
                    import traceback
                    traceback.print_exc()
                    raise

            # Earthdata Login
            def get_urs(self, u, q):
                if u.path == "/":
                    return self.send(200, "<html>Earthdata Login</html>")
                cred = self.basic()
                ok = cred and cred[1] == "right" and cred[0] in ("kodi", "noapp", "unconfirmed")
                if not ok:
                    return self.send(401, "<html>Unauthorized</html>",
                                     headers=[("WWW-Authenticate", 'Basic realm="Please enter your Earthdata Login credentials"')])
                if cred[0] == "unconfirmed":
                    return self.send(403, "<html>Please confirm your email</html>")
                if u.path == "/api/users/tokens":
                    return self.send(200, json.dumps([{"access_token": "x"}]), "application/json")
                if u.path == "/oauth/authorize":
                    if cred[0] == "noapp":
                        return self.send(200, "<html>Authorize application LP DAAC: approve access to your profile?</html>")
                    sep = "&" if "?" in q["redirect_uri"] else "?"
                    return self.send(302, headers=[("Location", f"{q['redirect_uri']}{sep}code=abc&state={quote(q.get('state', '/'))}")])
                self.send(404)

            # LP DAAC data host
            def authed(self):
                a = self.headers.get("Authorization", "")
                if a.startswith("Bearer "):
                    return a[7:].startswith("GOOD") and a.count(".") == 2, True
                return "lpsession=ok" in self.headers.get("Cookie", ""), False

            def get_data(self, u, q):
                if u.path == "/":
                    return self.send(403, "<html>Forbidden</html>")
                if u.path == "/login":
                    if q.get("code") != "abc":
                        return self.send(401)
                    return self.send(302, headers=[("Set-Cookie", "lpsession=ok; Path=/"), ("Location", q.get("state", "/"))])
                ok, bearer = self.authed()
                if bearer and not ok:
                    return self.send(401, '{"error":"invalid token"}', "application/json")
                if not ok:
                    redirect = fake.url("data") + "/login"
                    return self.send(302, headers=[("Location", f"{fake.url('urs')}/oauth/authorize?client_id=lp&response_type=code"
                                                                f"&redirect_uri={quote(redirect)}&state={quote(u.path)}")])
                if u.path == "/s3credentials":
                    exp = time.strftime("%Y-%m-%d %H:%M:%S+00:00", time.gmtime(time.time() + 3600))
                    return self.send(200, json.dumps({"accessKeyId": "AK", "secretAccessKey": "SK", "sessionToken": "ST",
                                                      "expiration": exp}), "application/json")
                if u.path.startswith("/lp-prod-protected/"):
                    return self.send(307, headers=[("Location", f"{fake.url('s3')}/signed{u.path}?X-Amz-Signature=sig")])
                self.send(404)

            # S3 behind the signed redirect
            def get_s3(self, u, q):
                if self.headers.get("Authorization"):
                    return self.send(400, '<?xml version="1.0"?><Error><Code>InvalidArgument</Code><Message>Only one auth '
                                          'mechanism allowed; only the X-Amz-Algorithm query parameter...</Message></Error>',
                                     "application/xml")
                if fake.mode == "expired":
                    return self.send(403, '<?xml version="1.0"?><Error><Code>AccessDenied</Code><Message>Request has expired'
                                          '</Message></Error>', "application/xml")
                with open(TIF, "rb") as f:
                    data = f.read()
                r = self.headers.get("Range")
                if r:
                    a, _, b = r.split("=")[1].partition("-")
                    a, b = int(a), min(int(b or len(data) - 1), len(data) - 1)
                    return self.send(206, data[a:b + 1], "image/tiff",
                                     [("Content-Range", f"bytes {a}-{b}/{len(data)}"), ("Accept-Ranges", "bytes")])
                self.send(200, data, "image/tiff", [("Accept-Ranges", "bytes")])

            # CMR
            def get_cmr(self, u, q):
                if u.path == "/search/health":
                    return self.send(200, "{}", "application/json")
                if u.path == "/search/collections.json":
                    if fake.mode == "nocollection":
                        return self.send(200, json.dumps({"feed": {"entry": []}}), "application/json")
                    cid = {"HLSL30": "C2021957657-LPCLOUD", "HLSS30": "C2021957295-LPCLOUD"}[q["short_name"]]
                    return self.send(200, json.dumps({"feed": {"entry": [{"id": cid}]}}), "application/json")
                if u.path == "/search/granules.json":
                    if fake.mode == "nogranules":
                        return self.send(200, json.dumps({"feed": {"entry": []}}), "application/json", [("CMR-Hits", "0")])
                    base = f"lp-prod-protected/HLSS30.020/{GRANULE}/{GRANULE}"
                    g = {"title": GRANULE, "links": [
                        {"rel": "http://esipfed.org/ns/fedsearch/1.1/data#", "href": f"{fake.url('data')}/{base}.B8A.tif"},
                        {"rel": "http://esipfed.org/ns/fedsearch/1.1/data#", "href": f"{fake.url('data')}/{base}.Fmask.tif"},
                        {"rel": "http://esipfed.org/ns/fedsearch/1.1/s3#", "href": f"s3://{base}.Fmask.tif"}]}
                    return self.send(200, json.dumps({"feed": {"entry": [g]}}), "application/json", [("CMR-Hits", "7")])
                self.send(404)

        return H
