"""Rewrite flags.json in its house layout (one field, flag or preset per line) so diffs stay small.

Usage: python -m qamask.format_flags
"""

import json
from collections import OrderedDict

from .registry import FLAGS_JSON


def _j(v):
    return json.dumps(v, ensure_ascii=False)


def dumps(d):
    out = ["{", f'  "_about": {_j(d["_about"])},', '  "products": {']
    keys = list(d["products"])
    for i, k in enumerate(keys):
        p = d["products"][k]
        out.append(f'    "{k}": {{')
        items = list(p.items())
        for j, (kk, v) in enumerate(items):
            end = "," if j < len(items) - 1 else ""
            if kk in ("fields", "flags"):
                out.append(f'      "{kk}": [')
                out += [f"        {_j(x)}" + ("," if n < len(v) - 1 else "") for n, x in enumerate(v)]
                out.append("      ]" + end)
            elif kk == "presets":
                out.append('      "presets": {')
                pk = list(v)
                out += [f'        "{n}": {_j(v[n])}' + ("," if m < len(pk) - 1 else "") for m, n in enumerate(pk)]
                out.append("      }" + end)
            else:
                out.append(f'      "{kk}": {_j(v)}{end}')
        out.append("    }" + ("," if i < len(keys) - 1 else ""))
    out += ["  }", "}", ""]
    return "\n".join(out)


def main():
    with open(FLAGS_JSON) as fh:
        d = json.load(fh, object_pairs_hook=OrderedDict)
    text = dumps(d)
    assert json.loads(text) == d
    with open(FLAGS_JSON, "w") as fh:
        fh.write(text)
    print(FLAGS_JSON)


if __name__ == "__main__":
    main()
