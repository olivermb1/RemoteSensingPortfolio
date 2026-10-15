"""Check results and how they are printed."""

import json
from dataclasses import asdict, dataclass, field

PASS, WARN, FAIL, SKIP, INFO = "pass", "warn", "fail", "skip", "info"
MARK = {PASS: "OK  ", WARN: "WARN", FAIL: "FAIL", SKIP: "skip", INFO: "info"}
ORDER = {FAIL: 0, WARN: 1, PASS: 2, INFO: 3, SKIP: 4}


@dataclass
class Result:
    id: str              # short key, e.g. "netrc"
    title: str           # what was checked, in a few words
    status: str          # pass / warn / fail / skip / info
    detail: str = ""     # what was found
    fix: str = ""        # what to do about it, empty when nothing to do
    gotcha: str = ""     # id in gotchas.GOTCHAS for the longer story
    data: dict = field(default_factory=dict)


def summary(results):
    n = {s: sum(r.status == s for r in results) for s in (PASS, WARN, FAIL, SKIP, INFO)}
    if n[FAIL] and all(r.id == "file" for r in results if r.status == FAIL):
        head = f"{n[FAIL]} file(s) are broken and need downloading again."
    elif n[FAIL]:
        head = f"{n[FAIL]} problem(s) stop HLS access on this machine. Fix the FAIL lines first, top to bottom."
    elif n[WARN]:
        head = "HLS access should work, with warnings worth fixing."
    else:
        head = "Everything checked works."
    return head, n


def to_text(results, verbose=False, width=88):
    import textwrap

    def wrap(s, indent):
        out = []
        for para in s.split("\n"):
            out += textwrap.wrap(para, width - len(indent)) or [""]
        return "\n".join(indent + line for line in out)

    lines = []
    for r in results:
        if r.status in (SKIP, INFO) and not verbose and not r.detail:
            continue
        lines.append(f"[{MARK[r.status]}] {r.title}")
        if r.detail:
            lines.append(wrap(r.detail, "       "))
        if r.fix and r.status in (FAIL, WARN):
            lines.append(wrap("Fix: " + r.fix, "       "))
        if r.gotcha and r.status in (FAIL, WARN):
            lines.append(f"       More: python -m hlsdoctor gotchas {r.gotcha}")
    head, n = summary(results)
    lines += ["", head, "  " + ", ".join(f"{v} {k}" for k, v in n.items() if v)]
    return "\n".join(lines)


def to_json(results):
    head, n = summary(results)
    return json.dumps({"summary": head, "counts": n, "checks": [asdict(r) for r in results]}, indent=2)


def to_markdown(results):
    head, _ = summary(results)
    rows = ["| | Check | Found | Fix |", "|---|---|---|---|"]
    for r in results:
        cell = lambda s: s.replace("|", "\\|").replace("\n", "<br>")
        rows.append(f"| {MARK[r.status].strip()} | {cell(r.title)} | {cell(r.detail)} | "
                    f"{cell(r.fix) if r.status in (FAIL, WARN) else ''} |")
    return f"**{head}**\n\n" + "\n".join(rows) + "\n"
