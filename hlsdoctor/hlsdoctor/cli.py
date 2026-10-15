"""python -m hlsdoctor check | files | gotchas"""

import argparse
import sys

from . import auth, env, net
from . import endpoints as ep
from .files import check_paths
from .gotchas import show
from .report import FAIL, to_json, to_markdown, to_text


def run_check(bbox=ep.DEFAULT_BBOX, days=90, offline=False, token_file=None, stream_url=None,
              files=None, log=None):
    """Run every check in order and return the list of Results."""
    say = log or (lambda s: None)
    results = env.run_all()
    say("software checked")
    nres, creds, npath = auth.check_netrc()
    results += [nres, auth.check_env_creds()]
    token, src = auth.read_token(token_file)
    results.append(auth.check_token(token, source=src))
    if offline:
        say("offline: skipping network checks")
    else:
        reach = net.check_reach()
        results += reach
        say("servers checked")
        if all(r.status != FAIL for r in reach if r.id == "reach"):
            results.append(net.check_login(creds))
            cmr, sample = net.check_cmr(bbox, days)
            results += cmr
            say("CMR searched")
            url = sample.get("https")
            results.append(net.check_download(url, creds))
            if token and auth.decode_jwt(token):
                results.append(net.check_download(url, None, token))
            say("download tried")
            results += net.check_stream(stream_url or url, npath is not None, token)
            say("GDAL streaming tried")
            results.append(net.check_s3(creds, sample.get("s3"), net.aws_region()))
        elif stream_url:
            results += net.check_stream(stream_url, npath is not None, token)
    if files:
        results += check_paths(files)
    return results


def _emit(results, fmt, verbose):
    if fmt == "json":
        print(to_json(results))
    elif fmt == "markdown":
        print(to_markdown(results))
    else:
        print(to_text(results, verbose))


def main(argv=None):
    p = argparse.ArgumentParser(prog="hlsdoctor", description="Check this computer's setup for NASA HLS data.")
    sub = p.add_subparsers(dest="cmd")
    c = sub.add_parser("check", help="run every check (default)")
    c.add_argument("--bbox", type=float, nargs=4, metavar=("W", "S", "E", "N"), default=ep.DEFAULT_BBOX,
                   help="area for the test search, degrees (default: Nakuru, Kenya)")
    c.add_argument("--days", type=int, default=90, help="search this many days back (default 90)")
    c.add_argument("--offline", action="store_true", help="only checks that need no internet")
    c.add_argument("--token-file", help="file holding an Earthdata token (default: $EARTHDATA_TOKEN)")
    c.add_argument("--stream-url", help="test GDAL streaming on this https URL instead of the one CMR finds")
    c.add_argument("--files", nargs="+", help="also check these downloaded files or folders")
    f = sub.add_parser("files", help="check downloaded HLS files or folders")
    f.add_argument("paths", nargs="+")
    g = sub.add_parser("gotchas", help="list known problems and fixes")
    g.add_argument("ids", nargs="*")
    for s in (c, f):
        s.add_argument("--format", choices=["text", "json", "markdown"], default="text")
        s.add_argument("-v", "--verbose", action="store_true", help="also show skipped and informational lines")
    a = p.parse_args(argv)
    if a.cmd in (None, "check"):
        if a.cmd is None:
            a = c.parse_args([])
        log = (lambda s: print(f"... {s}", file=sys.stderr)) if a.format == "text" else None
        res = run_check(tuple(a.bbox), a.days, a.offline, a.token_file, a.stream_url, a.files, log)
    elif a.cmd == "files":
        res = check_paths(a.paths, a.verbose)
    else:
        print(show(a.ids))
        return 0
    _emit(res, a.format, a.verbose)
    return 1 if any(r.status == FAIL for r in res) else 0


if __name__ == "__main__":
    sys.exit(main())
