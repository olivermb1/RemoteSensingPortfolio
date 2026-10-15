"""Login checks that need no network: ~/.netrc, environment variables and
Earthdata tokens. Passwords are never printed."""

import base64
import json
import netrc
import os
import stat
import time

from . import endpoints as ep
from .report import FAIL, INFO, PASS, SKIP, WARN, Result

MACHINE = ep.URS_HOST
PLACEHOLDERS = {"username", "password", "your_username", "your_password", "<username>",
                "<password>", "user", "pass", "changeme", "xxxx", "login", "earthdata_username",
                "earthdata_password", "your_earthdata_username", "your_earthdata_password"}
NEAR_MISSES = ("earthdata.nasa.gov", "urs.earthdata.nasa.gov/", "https://urs.earthdata.nasa.gov",
               "https://urs.earthdata.nasa.gov/", "urs.earthdata.nasa.gov.", "urs.eartdata.nasa.gov",
               "urs.earthdata.gov", "uat.urs.earthdata.nasa.gov")


def netrc_paths(home=None, environ=None, windows=None):
    """Candidate netrc files, in the order the common readers look at them."""
    environ = os.environ if environ is None else environ
    home = home or os.path.expanduser("~")
    windows = (os.name == "nt") if windows is None else windows
    out = []
    if environ.get("NETRC"):
        out.append(environ["NETRC"])
    out.append(os.path.join(home, ".netrc"))
    if windows:
        out.append(os.path.join(home, "_netrc"))
    return out


def parse_netrc(text):
    """Tolerant netrc reader: a list of {machine, login, password, line} so that
    we can report what a strict reader would choke on. 'default' entries are
    kept with machine=None."""
    toks, entries, cur = [], [], None
    for ln, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue
        for t in line.split():
            toks.append((t, ln))
    i = 0
    while i < len(toks):
        t, ln = toks[i]
        if t in ("machine", "default"):
            cur = {"machine": None, "login": None, "password": None, "line": ln}
            entries.append(cur)
            if t == "machine" and i + 1 < len(toks):
                cur["machine"] = toks[i + 1][0]
                i += 1
        elif t in ("login", "password", "account") and cur is not None and i + 1 < len(toks):
            if t != "account":
                cur[t] = toks[i + 1][0]
            i += 1
        elif t == "macdef":
            break  # macros run to a blank line; nobody uses them for Earthdata
        i += 1
    return entries


def check_netrc(home=None, environ=None, windows=None, posix=None):
    """Return (Result, creds or None, path or None)."""
    environ = os.environ if environ is None else environ
    windows = (os.name == "nt") if windows is None else windows
    posix = (os.name == "posix") if posix is None else posix
    paths = netrc_paths(home, environ, windows)
    found = [p for p in paths if os.path.isfile(p)]
    title = "Earthdata login in ~/.netrc"
    if not found:
        if environ.get("EARTHDATA_USERNAME") and environ.get("EARTHDATA_PASSWORD"):
            return Result("netrc", title, WARN,
                          f"No netrc file ({' or '.join(paths)}). EARTHDATA_USERNAME and EARTHDATA_PASSWORD are set, "
                          "so earthaccess can log in, but GDAL, QGIS and curl only read the netrc file.",
                          "Run: python -c \"import earthaccess; earthaccess.login(strategy='environment', persist=True)\" "
                          "which writes ~/.netrc for you.", "netrc-missing"), \
                (environ["EARTHDATA_USERNAME"], environ["EARTHDATA_PASSWORD"]), None
        return Result("netrc", title, FAIL, f"No netrc file found (looked for {' and '.join(paths)}).",
                      "Make a free account at https://urs.earthdata.nasa.gov, then run: "
                      "python -c \"import earthaccess; earthaccess.login(persist=True)\" "
                      "or create the file yourself with the line: "
                      f"machine {MACHINE} login YOUR_USERNAME password YOUR_PASSWORD", "netrc-missing"), None, None
    path = found[0]
    problems, warns = [], []
    with open(path, "rb") as f:
        raw = f.read()
    if raw.startswith(b"\xef\xbb\xbf"):
        warns.append("the file starts with a byte-order mark (saved by Notepad as 'UTF-8 with BOM'); "
                     "if the first line holds the Earthdata entry, curl and GDAL won't see the word 'machine'. Re-save it as plain UTF-8")
    if b"\r\n" in raw and not windows:
        warns.append("the file has Windows line endings; some readers then take the password as 'secret\\r'")
    text = raw.decode("utf-8", "replace").lstrip("﻿")
    entries = parse_netrc(text)
    ours = [e for e in entries if e["machine"] == MACHINE]
    if not ours:
        near = [e["machine"] for e in entries if e["machine"] and
                (e["machine"].lower().rstrip("/.") in [n.rstrip("/.") for n in NEAR_MISSES]
                 or "earthdata" in e["machine"].lower())]
        msg = f"{path} has no entry for machine {MACHINE}."
        if near:
            msg += f" It has '{near[0]}', which is not the same: the name must match exactly, with no https:// and no slash."
        return Result("netrc", title, FAIL, msg,
                      f"Add the line: machine {MACHINE} login YOUR_USERNAME password YOUR_PASSWORD",
                      "netrc-machine"), None, path
    if len(ours) > 1:
        warns.append(f"{MACHINE} appears {len(ours)} times (lines {', '.join(str(e['line']) for e in ours)}); "
                     "curl and GDAL use the first entry and Python's netrc module the last, so they may log in "
                     "with different passwords. Keep one")
    e = ours[0]
    if not e["login"] or not e["password"]:
        problems.append(f"the entry on line {e['line']} is missing its {'login' if not e['login'] else 'password'}")
    for k in ("login", "password"):
        v = (e[k] or "").strip("'\"").lower()
        if v in PLACEHOLDERS:
            problems.append(f"the {k} looks like a placeholder ('{e[k] if k == 'login' else '...'}'); put your real Earthdata {k}")
    pw = e["password"] or ""
    if any(c in pw for c in "#\"'\\"):
        warns.append("the password contains #, a quote or a backslash, which netrc readers treat differently "
                     "(older Python versions cut it at #). If login fails, change the Earthdata password to one without them")
    if posix is True:
        try:
            mode = stat.S_IMODE(os.stat(path).st_mode)
            if mode & 0o077:
                warns.append(f"the file permissions are {oct(mode)}, so other users on this computer can read your "
                             "NASA password, and Python's netrc.netrc() called with no arguments (used by some "
                             "older scripts) refuses the file. Run: chmod 600 " + path)
        except OSError:
            pass
    # What a strict reader (Python's netrc module, which requests uses) makes of it
    try:
        n = netrc.netrc(path) if path != os.path.join(os.path.expanduser("~"), ".netrc") else netrc.netrc()
        a = n.authenticators(MACHINE)
        if a and e["login"] and a[0] != e["login"]:
            warns.append(f"Python's netrc module reads login '{a[0]}', but curl/GDAL read '{e['login']}'")
    except netrc.NetrcParseError as ex:
        if "permissions" not in str(ex) and "too permissive" not in str(ex):
            problems.append(f"Python's netrc module can't read the file: {ex}")
    except (OSError, UnicodeDecodeError) as ex:
        problems.append(f"the file can't be read: {ex}")
    if windows and path.endswith(".netrc") and not os.path.isfile(os.path.join(os.path.dirname(path), "_netrc")):
        warns.append("on Windows, GDAL/QGIS builds with older curl look for _netrc instead of .netrc; "
                     "copy .netrc to _netrc in the same folder")
    creds = (e["login"], e["password"]) if e["login"] and e["password"] else None
    detail = f"{path}: entry for {MACHINE} with login '{e['login']}'."
    if problems:
        also = (" Also: " + "; ".join(warns) + ".") if warns else ""
        return Result("netrc", title, FAIL, detail + " Problems: " + "; ".join(problems) + "." + also,
                      "Fix the problems above; the file should hold one line: "
                      f"machine {MACHINE} login YOUR_USERNAME password YOUR_PASSWORD",
                      "netrc-machine"), creds, path
    if warns:
        return Result("netrc", title, WARN, detail + " But: " + "; ".join(warns) + ".",
                      "See the notes above.", "netrc-perms" if any("permissions" in w for w in warns) else "netrc-machine"), creds, path
    return Result("netrc", title, PASS, detail), creds, path


def decode_jwt(token):
    """Payload of a JWT without checking the signature, or None."""
    parts = token.strip().split(".")
    if len(parts) != 3:
        return None
    try:
        pad = "=" * (-len(parts[1]) % 4)
        return json.loads(base64.urlsafe_b64decode(parts[1] + pad))
    except (ValueError, json.JSONDecodeError):
        return None


def check_token(token, now=None, source="EARTHDATA_TOKEN"):
    title = "Earthdata token"
    if not token:
        return Result("token", title, SKIP, "No token given (set EARTHDATA_TOKEN or pass --token-file). "
                      "Tokens are optional; a netrc login is enough.")
    if token.lower().startswith("bearer "):
        return Result("token", title, FAIL, f"{source} starts with 'Bearer '.",
                      "Store only the token itself; the word Bearer is added by the program sending it.", "token")
    p = decode_jwt(token)
    if p is None:
        return Result("token", title, FAIL, f"{source} is not an Earthdata token (expected three dot-separated parts).",
                      "Generate one at https://urs.earthdata.nasa.gov/users/tokens and copy all of it.", "token")
    now = time.time() if now is None else now
    exp, uid = p.get("exp"), p.get("uid", "?")
    if exp is None:
        return Result("token", title, WARN, f"Token for user '{uid}' has no expiry date.", "", "token")
    days = (exp - now) / 86400
    when = time.strftime("%Y-%m-%d", time.gmtime(exp))
    if days < 0:
        return Result("token", title, FAIL, f"Token for user '{uid}' expired on {when}.",
                      "Generate a new one at https://urs.earthdata.nasa.gov/users/tokens "
                      "(tokens last 60 days and you can hold two at a time).", "token", {"expires": when})
    if days < 7:
        return Result("token", title, WARN, f"Token for user '{uid}' expires in {days:.1f} days ({when}).",
                      "Generate a new one at https://urs.earthdata.nasa.gov/users/tokens soon.", "token", {"expires": when})
    return Result("token", title, PASS, f"Token for user '{uid}', valid until {when} ({days:.0f} days).",
                  data={"expires": when, "uid": uid})


def read_token(token_file=None, environ=None):
    environ = os.environ if environ is None else environ
    if token_file:
        with open(os.path.expanduser(token_file)) as f:
            return f.read().strip(), token_file
    return environ.get("EARTHDATA_TOKEN", "").strip(), "EARTHDATA_TOKEN"


def check_env_creds(environ=None):
    environ = os.environ if environ is None else environ
    u, p = environ.get("EARTHDATA_USERNAME"), environ.get("EARTHDATA_PASSWORD")
    title = "EARTHDATA_USERNAME / EARTHDATA_PASSWORD"
    if u and p:
        return Result("envcreds", title, INFO, f"Set, for user '{u}'. earthaccess can use them "
                      "(login(strategy='environment')); GDAL and QGIS ignore them.")
    if u or p:
        return Result("envcreds", title, WARN, "Only one of the two is set.",
                      "Set both, or neither and rely on ~/.netrc.")
    return Result("envcreds", title, SKIP, "Not set (fine when ~/.netrc is set up).")

