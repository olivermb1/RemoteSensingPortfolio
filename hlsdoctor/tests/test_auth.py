import base64
import json
import os
import time

from hlsdoctor import auth
from hlsdoctor.report import FAIL, PASS, SKIP, WARN


def write(tmp_path, text, mode=0o600, name=".netrc", raw=None):
    p = tmp_path / name
    p.write_bytes(raw if raw is not None else text.encode())
    os.chmod(p, mode)
    return p


def run(tmp_path, env=None, windows=False):
    return auth.check_netrc(home=str(tmp_path), environ=env or {}, windows=windows, posix=True)


def test_missing(tmp_path):
    r, creds, path = run(tmp_path)
    assert r.status == FAIL and creds is None and "No netrc" in r.detail


def test_missing_but_env_creds(tmp_path):
    r, creds, _ = run(tmp_path, {"EARTHDATA_USERNAME": "kodi", "EARTHDATA_PASSWORD": "right"})
    assert r.status == WARN and creds == ("kodi", "right")


def test_good(tmp_path):
    write(tmp_path, "machine urs.earthdata.nasa.gov login kodi password right\n")
    r, creds, _ = run(tmp_path)
    assert r.status == PASS and creds == ("kodi", "right")
    assert "right" not in r.detail  # never print the password


def test_multiline_and_other_machines(tmp_path):
    write(tmp_path, "machine github.com login a password b\n\nmachine urs.earthdata.nasa.gov\n  login kodi\n  password right\n")
    r, creds, _ = run(tmp_path)
    assert r.status == PASS and creds == ("kodi", "right")


def test_wrong_machine_name(tmp_path):
    write(tmp_path, "machine https://urs.earthdata.nasa.gov login kodi password right\n")
    r, _, _ = run(tmp_path)
    assert r.status == FAIL and "not the same" in r.detail


def test_placeholder(tmp_path):
    write(tmp_path, "machine urs.earthdata.nasa.gov login <username> password <password>\n")
    r, _, _ = run(tmp_path)
    assert r.status == FAIL and "placeholder" in r.detail


def test_missing_password(tmp_path):
    write(tmp_path, "machine urs.earthdata.nasa.gov login kodi\n")
    r, creds, _ = run(tmp_path)
    assert r.status == FAIL and creds is None and "password" in r.detail


def test_permissions(tmp_path):
    write(tmp_path, "machine urs.earthdata.nasa.gov login kodi password right\n", mode=0o644)
    r, creds, _ = run(tmp_path)
    assert r.status == WARN and "chmod 600" in r.detail and creds


def test_duplicates_and_crlf(tmp_path):
    raw = b"machine urs.earthdata.nasa.gov login kodi password right\r\n" \
          b"machine urs.earthdata.nasa.gov login other password x\r\n"
    write(tmp_path, "", raw=raw)
    r, creds, _ = run(tmp_path)
    assert r.status == WARN
    for w in ("Windows line endings", "appears 2 times", "Python's netrc module reads login 'other'"):
        assert w in r.detail
    assert creds == ("kodi", "right")  # curl/GDAL use the first


def test_bom(tmp_path):
    write(tmp_path, "", raw=b"\xef\xbb\xbfmachine urs.earthdata.nasa.gov login kodi password right\n")
    r, _, _ = run(tmp_path)
    assert r.status == FAIL and "byte-order mark" in r.detail and "can't read" in r.detail


def test_hash_in_password(tmp_path):
    write(tmp_path, "machine urs.earthdata.nasa.gov login kodi password ab#cd\n")
    r, _, _ = run(tmp_path)
    assert r.status == WARN and "#" in r.detail


def test_windows_underscore(tmp_path):
    write(tmp_path, "machine urs.earthdata.nasa.gov login kodi password right\n")
    r, _, _ = run(tmp_path, windows=True)
    assert r.status == WARN and "_netrc" in r.detail


def test_netrc_env_var(tmp_path):
    p = write(tmp_path, "machine urs.earthdata.nasa.gov login kodi password right\n", name="custom")
    r, creds, path = run(tmp_path, {"NETRC": str(p)})
    assert r.status == PASS and path == str(p)


def jwt(payload):
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{enc({'alg': 'RS256'})}.{enc(payload)}.sig"


def test_tokens():
    now = time.time()
    assert auth.check_token("").status == SKIP
    assert auth.check_token("not-a-token").status == FAIL
    assert auth.check_token("Bearer " + jwt({"exp": now + 1e6})).status == FAIL
    assert auth.check_token(jwt({"uid": "kodi", "exp": now - 10})).status == FAIL
    assert auth.check_token(jwt({"uid": "kodi", "exp": now + 3 * 86400})).status == WARN
    r = auth.check_token(jwt({"uid": "kodi", "exp": now + 50 * 86400}))
    assert r.status == PASS and "kodi" in r.detail
