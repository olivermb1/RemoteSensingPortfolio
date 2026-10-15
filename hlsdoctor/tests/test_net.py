"""Network checks against the local fake Earthdata (tests/fake_earthdata.py)."""

import base64
import json
import time

from hlsdoctor import net
from hlsdoctor.http import Hop, Response, fetch
from hlsdoctor.report import FAIL, INFO, PASS, SKIP, WARN

GOOD = ("kodi", "right")


def tok():
    p = base64.urlsafe_b64encode(json.dumps({"uid": "kodi", "exp": time.time() + 9e5}).encode()).decode().rstrip("=")
    return f"GOODhdr.{p}.sig"


def test_reach_and_clock(fake):
    res = net.check_reach()
    assert [r.status for r in res] == [PASS, PASS, PASS, PASS]
    fake.clock_skew = 3600
    res = net.check_reach()
    assert res[-1].id == "clock" and res[-1].status == FAIL and "behind" in res[-1].detail


def test_unreachable(monkeypatch):
    from hlsdoctor import endpoints as ep
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setattr(ep, "URS", "http://127.0.0.1:9")
    monkeypatch.setattr(ep, "CMR", "http://127.0.0.1:9")
    monkeypatch.setattr(ep, "DATA", "http://127.0.0.1:9")
    res = net.check_reach(timeout=3)
    assert all(r.status == FAIL for r in res) and "refused" in res[0].detail.lower()


def test_login(fake):
    assert net.check_login(GOOD).status == PASS
    assert net.check_login(("kodi", "wrong")).status == FAIL
    assert net.check_login(("unconfirmed", "right")).status == FAIL
    assert net.check_login(None).status == SKIP


def test_cmr(fake):
    res, sample = net.check_cmr()
    assert [r.status for r in res] == [PASS, PASS, PASS]
    assert sample["https"].endswith(".Fmask.tif") and sample["s3"].startswith("s3://")
    assert "HLSL30: 7" in res[-1].detail
    fake.mode = "nogranules"
    res, sample = net.check_cmr()
    assert res[-1].status == WARN and not sample.get("https")
    fake.mode = "nocollection"
    res, _ = net.check_cmr()
    assert res[0].status == FAIL and "version" in res[0].detail


def sample_url(fake):
    return net.check_cmr()[1]["https"]


def test_download_good_follows_login_dance(fake):
    r = net.check_download(sample_url(fake), GOOD)
    assert r.status == PASS, r.detail
    hosts = [h for h, _ in r.data["hops"]]
    assert len(hosts) == 5  # data -> URS -> data/login -> data -> s3


def test_download_bad_password(fake):
    r = net.check_download(sample_url(fake), ("kodi", "wrong"))
    assert r.status == FAIL and r.gotcha == "login"


def test_download_no_login(fake):
    r = net.check_download(sample_url(fake), None)
    assert r.status == FAIL and r.gotcha == "netrc-missing"


def test_download_app_not_approved(fake):
    r = net.check_download(sample_url(fake), ("noapp", "right"))
    assert r.status == FAIL and r.gotcha == "eula"


def test_download_expired_link(fake):
    url = sample_url(fake)
    fake.mode = "expired"
    r = net.check_download(url, GOOD)
    assert r.status == FAIL and r.gotcha == "clock"


def test_token_goes_to_data_host_only(fake):
    url = sample_url(fake)
    r = net.check_download(url, None, tok())
    assert r.status == PASS, r.detail
    s3_auth = [a for role, _, _, a in fake.log if role == "s3"]
    assert s3_auth and all(a == "" for a in s3_auth)
    bad = net.check_download(url, None, "BADhdr.x.sig")
    assert bad.status == FAIL and bad.gotcha == "token"


def test_bearer_forwarded_to_s3_is_explained(fake):
    # What curl -L -H "Authorization: Bearer ..." does: send the header to S3 as well
    import urllib.request
    s3 = fake.url("s3") + "/signed/x.tif?X-Amz-Signature=sig"
    try:
        urllib.request.urlopen(urllib.request.Request(s3, headers={"Authorization": "Bearer x"}))
    except urllib.error.HTTPError as e:
        body = e.read()
    resp = Response(s3, 400, {"content-type": "application/xml"}, body, [Hop(s3, 400)])
    st, detail, fix, g = net.explain_download(resp, None, "x")
    assert st == FAIL and g == "bearer-s3"


def test_s3_outside_and_inside_region(fake):
    assert net.check_s3(GOOD, region=None).status == INFO
    assert net.check_s3(GOOD, region="eu-west-1").status == WARN
    r = net.check_s3(GOOD, region="us-west-2")
    assert r.status == PASS and "temporary S3 keys" in r.detail
    assert net.check_s3(("kodi", "wrong"), region="us-west-2").status == FAIL


def test_fetch_never_sends_basic_beyond_urs(fake):
    fake.log.clear()
    fetch(sample_url(fake), creds=GOOD, range_bytes=100)
    for role, _, _, a in fake.log:
        if a.startswith("Basic"):
            assert role == "urs"
