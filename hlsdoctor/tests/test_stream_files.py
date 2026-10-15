import os
import subprocess
import sys

import pytest

from hlsdoctor import env, files, gotchas, stream
from hlsdoctor.report import FAIL, PASS, WARN

HERE = os.path.dirname(os.path.abspath(__file__))
DEMO = os.path.join(HERE, "..", "demo", "files")
GOOD = os.path.join(DEMO, "HLS.S30.T10TCT.2021345T191811.v2.0.B8A.tif")


def test_explain_gdal_errors():
    cases = {"HTTP response code: 401": "auth",
             "'/vsicurl/https://x/y.tif' not recognized as being in a supported file format.": "html",
             "HTTP response code: 403": "forbidden", "HTTP response code: 400 Only one auth mechanism": "bearer-s3",
             "HTTP response code: 404": "notfound", "Could not resolve host: urs": "dns",
             "SSL certificate problem: unable to get local issuer certificate": "tls"}
    for msg, kind in cases.items():
        assert stream.explain_gdal_error(msg)[0] == kind, msg


def test_local_read():
    r = stream.open_and_read(GOOD)
    assert r["ok"] and r["info"]["block"] == (128, 128) and r["info"]["scale"] == pytest.approx(0.0001)


def _read_in_subprocess(url, cfg):
    """GDAL (inside rasterio) may hold Python's GIL while it downloads, which
    would freeze the fake server's threads, so read from a separate process."""
    import json
    code = ("import json, sys; from hlsdoctor import stream; "
            "print(json.dumps(stream.open_and_read(sys.argv[1], json.loads(sys.argv[2])), default=str))")
    r = subprocess.run([sys.executable, "-c", code, url, json.dumps(cfg)], cwd=os.path.join(HERE, ".."),
                       capture_output=True, text=True, timeout=60)
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_gdal_streams_through_login_dance(fake, tmp_path):
    """GDAL itself, with the recommended settings and a netrc file, follows
    data -> URS (401 challenge, netrc login) -> cookie -> S3 and reads a block."""
    nrc = tmp_path / "netrc"
    nrc.write_text("machine 127.0.0.1 login kodi password right\n")
    url = "/vsicurl/" + fake.url("data") + "/lp-prod-protected/HLSS30.020/G/G.v2.0.B8A.tif"
    cfg = stream.recommended_config()
    cfg.update(GDAL_HTTP_NETRC_FILE=str(nrc), GDAL_HTTP_COOKIEFILE=str(tmp_path / "c"),
               GDAL_HTTP_COOKIEJAR=str(tmp_path / "c"), GDAL_HTTP_TIMEOUT="20")
    r = _read_in_subprocess(url, cfg)
    assert r["ok"], r
    assert any(role == "s3" for role, *_ in fake.log)
    nrc.write_text("machine 127.0.0.1 login kodi password wrong\n")
    (tmp_path / "c").unlink(missing_ok=True)
    r = _read_in_subprocess(url, cfg)
    assert not r["ok"] and r["kind"] == "auth", r


def test_gdal_env_check():
    assert env.check_gdal_env({}).status == WARN
    assert env.check_gdal_env({"GDAL_HTTP_NETRC": "NO"}).status == FAIL
    ok = {k: v for k, v in env.GDAL_RECOMMENDED.items()}
    assert env.check_gdal_env(ok).status == PASS
    assert env.check_tls_env({"SSL_CERT_FILE": "/nope.pem"}).status == FAIL


def test_demo_folder():
    if not os.path.isdir(DEMO):
        pytest.skip("run demo/make_demo_files.py first")
    res = files.check_paths([DEMO])
    by = {r.title: r for r in res}
    assert by["HLS.S30.T10TCT.2021345T191811.v2.0.B03.tif"].gotcha == "html-as-tif"
    assert by["HLS.L30.T19JHN.2024279T141847.v2.0.B05.tif"].status == FAIL
    assert by["HLS.S30.T10TCT.2021345T191811.v2.0.B02.tif"].status == FAIL  # cut off
    assert by["HLS.S30.T10TCT.2021345T191811.v2.0.B11.tif"].status == FAIL  # empty
    assert "southern" in by["HLS.L30.T19JHN.2024279T141847.v2.0.Fmask.tif"].detail
    assert "no-data" in by["HLS.S30.T10TCT.2021345T191811.v2.0.B04.tif"].detail
    assert "1.5" in by["HLS.S30.T10TCT.2021345T191811.v1.5.B8A.tif"].detail
    assert by["EPSG code on the CRS"].status == WARN
    assert by["Neighbouring MGRS tiles"].status == WARN
    assert "B8A" in by["Landsat (L30) and Sentinel-2 (S30) files together"].detail


def test_crsfix_copy_matches_qamaskbuilder():
    from hlsdoctor import _crsfix_copy
    cases = [(32619, -2700000, -2809800, "HLS.L30.T19JHN.x"), (32610, 5300040, 5190240, "T10TCT"),
             (32736, 9990000, 9880000, None), (32637, 10000, -5000, None), (None, 0, 0, None)]
    for c in cases:
        assert files.hls_crs_fix(*c) == _crsfix_copy.hls_crs_fix(*c)


def test_every_gotcha_referenced_exists():
    import re
    src = "".join(open(os.path.join(HERE, "..", "hlsdoctor", f)).read()
                  for f in ("auth.py", "env.py", "net.py", "files.py"))
    used = set(re.findall(r'"([a-z0-9]+(?:-[a-z0-9]+)+|network|login|eula|token|scale|nodata|fmask|tiles|versions|bbox|clock|tls)"', src))
    missing = {u for u in used if u not in gotchas.GOTCHAS and u in {
        g for g in re.findall(r'gotcha[^"]*"([^"]+)"', src)}}
    assert not missing


def test_cli_offline_and_files():
    run = lambda *a: subprocess.run([sys.executable, "-m", "hlsdoctor", *a], cwd=os.path.join(HERE, ".."),
                                    capture_output=True, text=True)
    r = run("gotchas", "southern-epsg")
    assert r.returncode == 0 and "327" in r.stdout
    r = run("check", "--offline", "--format", "json")
    assert '"checks"' in r.stdout
    r = run("files", GOOD)
    assert r.returncode == 0 and "nothing to fix" in r.stdout
