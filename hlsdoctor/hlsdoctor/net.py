"""Checks that talk to NASA: can this machine reach Earthdata, log in, search
CMR for HLS, download a piece of a file, stream it with GDAL, and (inside AWS)
use direct S3 access."""

import email.utils
import json
import os
import time
import urllib.request
from http.cookiejar import CookieJar
from urllib.parse import urlencode

from . import endpoints as ep
from .http import fetch, is_tiff, looks_html, looks_s3_error
from .report import FAIL, INFO, PASS, SKIP, WARN, Result
from .stream import open_and_read, recommended_config

NET_WORDS = {
    "dns": ("couldn't look up the name {h}", "Check the internet connection; on a work network, ask IT whether *.earthdata.nasa.gov is blocked."),
    "proxy": ("the network's proxy refused to connect to {h}", "A firewall or proxy blocks NASA Earthdata here. Ask IT to allow *.earthdata.nasa.gov and *.earthdatacloud.nasa.gov, or try another network."),
    "tls": ("the certificate check failed for {h}", "A company proxy is probably re-signing HTTPS. Set SSL_CERT_FILE, REQUESTS_CA_BUNDLE and CURL_CA_BUNDLE to your organisation's CA bundle file."),
    "timeout": ("the connection to {h} timed out", "Try again; if it keeps timing out, the network is blocking or very slow."),
    "refused": ("{h} refused the connection", "Check for a VPN or firewall blocking HTTPS."),
    "network": ("couldn't connect to {h}", "Check the internet connection."),
    "redirect_loop": ("{h} kept redirecting", "Delete the cookie file (~/.hlsdoctor_cookies.txt or your GDAL_HTTP_COOKIEFILE) and try again."),
}


def net_result(id_, title, resp, gotcha="network"):
    h = ep.host(resp.url)
    what, fix = NET_WORDS.get(resp.error, NET_WORDS["network"])
    return Result(id_, title, FAIL, what.format(h=h).capitalize() + f" ({resp.error_text[:160]}).", fix, gotcha)


def check_reach(timeout=15):
    """One result per host, plus the clock check from the servers' Date header."""
    out, skew = [], None
    for name, url in (("Earthdata Login", ep.URS + "/"), ("CMR search", ep.CMR + "/search/health"),
                      ("LP DAAC data", ep.DATA + "/")):
        r = fetch(url, timeout=timeout, max_hops=1)
        title = f"Reach {name} ({ep.host(url)})"
        if r.error:
            out.append(net_result("reach", title, r))
            continue
        out.append(Result("reach", title, PASS, f"Answered (HTTP {r.status}) in {r.seconds:.1f} s."))
        if skew is None and r.headers.get("date"):
            try:
                skew = time.time() - email.utils.parsedate_to_datetime(r.headers["date"]).timestamp()
            except (TypeError, ValueError):
                pass
    if skew is not None:
        if abs(skew) > 300:
            out.append(Result("clock", "Computer clock", FAIL,
                              f"This computer's clock is {abs(skew) / 60:.0f} minutes {'ahead' if skew > 0 else 'behind'} of NASA's servers.",
                              "Turn on automatic time setting. Signed S3 download links and tokens are rejected "
                              "when the clock is more than a few minutes off.", "clock"))
        else:
            out.append(Result("clock", "Computer clock", PASS, f"Within {abs(skew):.0f} s of NASA's servers."))
    return out


def check_login(creds, timeout=20):
    """Ask Earthdata Login directly whether the username and password work."""
    title = "Earthdata username and password"
    if not creds:
        return Result("login", title, SKIP, "No login to test (see the netrc check).")
    r = fetch(ep.URS + "/api/users/tokens", creds=creds, timeout=timeout, max_hops=1)
    if r.error:
        return net_result("login", title, r)
    if r.status == 200:
        n = None
        try:
            n = len(json.loads(r.body))
        except (ValueError, TypeError):
            pass
        extra = f" You have {n} token(s); Earthdata allows two at a time." if n is not None else ""
        return Result("login", title, PASS, f"Earthdata Login accepted user '{creds[0]}'.{extra}")
    if r.status == 401:
        return Result("login", title, FAIL, f"Earthdata Login rejected user '{creds[0]}' (HTTP 401).",
                      "Check the username (not your email address) and password by logging in at "
                      "https://urs.earthdata.nasa.gov, then correct ~/.netrc. A new account must also confirm "
                      "its email first.", "login")
    if r.status == 403:
        return Result("login", title, FAIL, "Earthdata Login refused the account (HTTP 403).",
                      "Log in at https://urs.earthdata.nasa.gov in a browser: the account may need its email "
                      "confirmed or new terms accepted.", "login")
    return Result("login", title, SKIP, f"Could not test the login directly (HTTP {r.status}); the download "
                  "check below tests it anyway.")


def check_cmr(bbox=ep.DEFAULT_BBOX, days=90, timeout=30, end=None):
    """Find both HLS v2.0 collections in CMR, then recent granules over bbox.
    Returns (results, sample) where sample has an https and maybe an s3 URL."""
    out, sample = [], {}
    concept = {}
    for prod, short in ep.COLLECTIONS.items():
        url = ep.CMR + "/search/collections.json?" + urlencode(
            {"short_name": short, "version": ep.VERSION, "provider": ep.PROVIDER})
        r = fetch(url, timeout=timeout, max_body=2_000_000)
        title = f"CMR: collection {short} v{ep.VERSION}"
        if r.error:
            out.append(net_result("cmr", title, r))
            continue
        try:
            entries = json.loads(r.body)["feed"]["entry"]
        except (ValueError, KeyError, TypeError):
            entries = None
        if r.status != 200 or entries is None:
            out.append(Result("cmr", title, FAIL, f"CMR answered HTTP {r.status} with no usable list.",
                              "Try again later; check https://status.earthdata.nasa.gov.", "versions"))
            continue
        if not entries:
            out.append(Result("cmr", title, FAIL, f"CMR has no {short} version {ep.VERSION} under provider {ep.PROVIDER}.",
                              "NASA may have released a new HLS version; search CMR for the short name without a version.",
                              "versions"))
            continue
        concept[prod] = entries[0]["id"]
        out.append(Result("cmr", title, PASS, f"Found ({entries[0]['id']})."))
    if not concept:
        return out, sample
    end_t = end or time.time()
    temporal = (time.strftime("%Y-%m-%dT00:00:00Z", time.gmtime(end_t - days * 86400)) + "," +
                time.strftime("%Y-%m-%dT23:59:59Z", time.gmtime(end_t)))
    counts = {}
    for prod, cid in concept.items():
        url = ep.CMR + "/search/granules.json?" + urlencode(
            {"collection_concept_id": cid, "bounding_box": ",".join(str(x) for x in bbox),
             "temporal": temporal, "page_size": 20, "sort_key": "-start_date"})
        r = fetch(url, timeout=timeout, max_body=5_000_000)
        if r.error or r.status != 200:
            counts[prod] = None
            continue
        try:
            body = json.loads(r.body)
            counts[prod] = int(r.headers.get("cmr-hits", len(body["feed"]["entry"])))
            for g in body["feed"]["entry"]:
                for link in g.get("links", []):
                    href = link.get("href", "")
                    if href.endswith(".Fmask.tif"):
                        if href.startswith("https://") or href.startswith("http://"):
                            sample.setdefault("https", href)
                        elif href.startswith("s3://"):
                            sample.setdefault("s3", href)
                sample.setdefault("granule", g.get("title"))
        except (ValueError, KeyError, TypeError):
            counts[prod] = None
    title = f"CMR: HLS granules over {', '.join(f'{x:g}' for x in bbox)} in the last {days} days"
    if all(v is None for v in counts.values()):
        out.append(Result("granules", title, FAIL, "The granule search failed.", "Try again later.", "versions"))
    elif not any(counts.values()):
        out.append(Result("granules", title, WARN, "No granules found. The area may be outside HLS coverage or the box may be in the wrong order.",
                          "Give the box as west, south, east, north in degrees (--bbox W S E N).", "bbox"))
    else:
        out.append(Result("granules", title, PASS,
                          ", ".join(f"{ep.COLLECTIONS[k]}: {v}" for k, v in counts.items() if v is not None) + " granules.",
                          data={"counts": counts, **sample}))
    return out, sample


def explain_download(r, creds, token=None):
    """Turn a download Response into (status, detail, fix, gotcha)."""
    hops = " -> ".join(f"{ep.host(h.url)} {h.status}" for h in r.hops)
    if r.error:
        what, fix = NET_WORDS.get(r.error, NET_WORDS["network"])
        return FAIL, what.format(h=ep.host(r.url)).capitalize() + ".", fix, "network"
    urs = [h for h in r.hops if ep.host(h.url) == ep.URS_HOST]
    body = r.text(4000).lower()
    if urs and urs[-1].status == 401:
        if not creds:
            return (FAIL, f"Earthdata Login asked for a username and password and none was available. Path: {hops}.",
                    "Set up ~/.netrc (see the netrc check).", "netrc-missing")
        return (FAIL, f"Earthdata Login rejected the username and password. Path: {hops}.",
                "Check them by logging in at https://urs.earthdata.nasa.gov and correct ~/.netrc.", "login")
    if (creds and urs and r.status in (200, 403) and ep.host(r.url) == ep.URS_HOST
            and any(w in body for w in ("authorize", "approve", "eula", "agree"))):
        return (FAIL, f"Earthdata Login wants you to approve LP DAAC's application or accept its terms. Path: {hops}.",
                "Log in at https://urs.earthdata.nasa.gov, open Applications > Authorized Apps, and approve "
                "'LP DAAC Data Pool' / 'LPDAAC Cloud' (or open the file link once in a browser and click Agree).",
                "eula")
    if r.ok and is_tiff(r.body):
        how = "token" if token else "netrc login"
        return PASS, f"Got the start of a GeoTIFF ({len(r.body)} bytes, {r.seconds:.1f} s) with your {how}. Path: {hops}.", "", ""
    if r.ok and looks_html(r.body):
        return (FAIL, f"Got a web page instead of the file (probably the login page). Path: {hops}.",
                "Your program isn't sending the Earthdata login. Check ~/.netrc, and that cookies are kept between redirects.",
                "html-as-tif")
    if r.status == 400 and "only one auth mechanism" in body:
        return (FAIL, f"S3 refused the request because a token was passed on to it. Path: {hops}.",
                "Send the Authorization header only to data.lpdaac.earthdatacloud.nasa.gov, not after the redirect "
                "(requests does this right; curl -L -H does not).", "bearer-s3")
    if r.status == 401 and token and not urs:
        return FAIL, f"LP DAAC rejected the token (HTTP 401). Path: {hops}.", "Generate a new token at https://urs.earthdata.nasa.gov/users/tokens.", "token"
    if r.status == 403 and looks_s3_error(r.body):
        expired = "expired" in body or "request has expired" in body
        return (FAIL, f"S3 refused the signed link ({'expired' if expired else 'access denied'}). Path: {hops}.",
                "Check the computer clock; signed links last about an hour, so fetch the link again rather than reusing an old one.",
                "clock" if expired else "s3-region")
    if r.status == 404:
        return FAIL, f"File not found (HTTP 404). Path: {hops}.", "The granule address may be stale; search CMR again.", "versions"
    return WARN, f"Unexpected answer HTTP {r.status} ({r.content_type}). Path: {hops}.", "", ""


def check_download(url, creds, token=None, timeout=60):
    title = "Download part of a real HLS file over HTTPS" + (" with a token" if token else "")
    if not url:
        return Result("download", title, SKIP, "No file address to test (the CMR search found none).")
    r = fetch(url, creds=None if token else creds, token=token, range_bytes=16384, timeout=timeout,
              jar=CookieJar())
    st, detail, fix, g = explain_download(r, creds, token)
    return Result("download_token" if token else "download", title, st, detail, fix, g,
                  {"url": url, "hops": [(h.url.split("?")[0], h.status) for h in r.hops]})


def check_stream(url, has_netrc, token=None):
    """Read one block with GDAL, first as the environment stands, then with the
    recommended settings, and say which settings make the difference."""
    title = "Stream with GDAL (/vsicurl/)"
    if not url:
        return [Result("stream", title, SKIP, "No file address to test.")]
    path = "/vsicurl/" + url
    first = open_and_read(path)
    if first.get("kind") == "nogdal":
        return [Result("stream", title, SKIP, "Neither GDAL nor rasterio is installed.", "pip install rasterio")]
    if first["ok"]:
        i = first["info"]
        return [Result("stream", title, PASS,
                       f"Read a {i['block'][0]}x{i['block'][1]} block in {first['seconds']:.1f} s with your current "
                       f"settings ({first['backend']}).", data=i)]
    second = open_and_read(path, recommended_config(token))
    if second["ok"]:
        return [Result("stream", title, WARN,
                       f"Failed with your current settings ({first['explain']}), but worked in "
                       f"{second['seconds']:.1f} s with the recommended GDAL settings.",
                       "Use the settings listed under 'GDAL settings for streaming HLS'.", "gdal-cookies")]
    fix = "Fix the login checks above first." if not has_netrc and not token else ""
    return [Result("stream", title, FAIL, f"Failed even with the recommended settings: {second['explain']}.",
                   fix, "gdal-cookies", {"error": second.get("error", "")[:300]})]


def aws_region(timeout=1.0):
    """The AWS region this machine runs in, or None outside AWS."""
    try:
        tok = urllib.request.urlopen(urllib.request.Request(
            "http://169.254.169.254/latest/api/token", method="PUT",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"}), timeout=timeout).read().decode()
        return urllib.request.urlopen(urllib.request.Request(
            "http://169.254.169.254/latest/meta-data/placement/region",
            headers={"X-aws-ec2-metadata-token": tok}), timeout=timeout).read().decode()
    except Exception:  # noqa: BLE001 - not on EC2, or metadata blocked
        pass
    # Lambda, SageMaker and ECS set AWS_EXECUTION_ENV and AWS_REGION but may hide the metadata service
    if os.environ.get("AWS_EXECUTION_ENV"):
        return os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    return None


def check_s3(creds, sample_s3=None, region=None, timeout=30):
    title = "Direct S3 access (s3:// links)"
    if region is None:
        return Result("s3", title, INFO,
                      f"This machine is not in AWS {ep.REGION}, so use the https:// links. s3:// links "
                      "(earthaccess access='direct', /vsis3/) only work from inside AWS us-west-2 and give "
                      "'Access Denied' anywhere else.", gotcha="s3-region")
    if region != ep.REGION:
        return Result("s3", title, WARN, f"This machine is in AWS {region}, not {ep.REGION}. s3:// links won't work; "
                      "https:// links will, but data crosses regions (slower, and egress may be charged).",
                      f"Run in {ep.REGION} for direct access.", "s3-region")
    if not creds:
        return Result("s3", title, SKIP, f"In {ep.REGION}, but no login to fetch temporary S3 keys with.")
    r = fetch(ep.S3CREDS, creds=creds, timeout=timeout, jar=CookieJar())
    if r.error:
        return net_result("s3", title, r, "s3-region")
    try:
        c = json.loads(r.body)
        exp = c.get("expiration", "?")
        assert c.get("accessKeyId")
    except (ValueError, AssertionError, AttributeError):
        st, detail, fix, g = explain_download(r, creds)
        return Result("s3", title, FAIL, "Couldn't get temporary S3 keys. " + detail, fix, g or "s3-region")
    res = Result("s3", title, PASS, f"In {ep.REGION}; got temporary S3 keys (valid until {exp}; they last one hour, "
                 "so long jobs must fetch new ones).", gotcha="s3-region")
    if sample_s3:
        cfg = {"AWS_ACCESS_KEY_ID": c["accessKeyId"], "AWS_SECRET_ACCESS_KEY": c["secretAccessKey"],
               "AWS_SESSION_TOKEN": c["sessionToken"], "AWS_REGION": ep.REGION, "AWS_NO_SIGN_REQUEST": "NO",
               "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR"}
        s = open_and_read("/vsis3/" + sample_s3[len("s3://"):], cfg)
        if s["ok"]:
            res.detail += f" Read a block over /vsis3/ in {s['seconds']:.1f} s."
        elif s.get("kind") != "nogdal":
            res.status, res.detail = WARN, res.detail + f" But reading over /vsis3/ failed: {s['explain']}."
    return res
