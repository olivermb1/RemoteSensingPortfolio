"""Write gee/qamask_gee.js from gee/template.js with flags.json embedded, so all three versions share one flag list.

Usage: python -m qamask.gee_build
"""

import json
import os

from .registry import FLAGS_JSON

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(ROOT, "gee", "template.js")
OUT = os.path.join(ROOT, "gee", "qamask_gee.js")
KEYS = ("title", "layer", "dtype", "fill", "fill_rule", "fields", "flags", "presets", "default_preset", "gee")


def main():
    with open(FLAGS_JSON) as fh:
        products = json.load(fh)["products"]
    slim = {k: {kk: v[kk] for kk in KEYS if kk in v} for k, v in products.items()}
    for p in slim.values():  # labels of field values aren't needed in the script
        p["fields"] = [{"name": f["name"], "bits": f["bits"]} for f in p["fields"]]
        p["flags"] = [{"name": f["name"], "field": f["field"], "in": f["in"]} for f in p["flags"]]
    with open(TEMPLATE) as fh:
        js = fh.read()
    js = js.replace("/*@@PRODUCTS@@*/{}", json.dumps(slim, separators=(",", ":")))
    with open(OUT, "w") as fh:
        fh.write(js)
    print(OUT)


if __name__ == "__main__":
    main()
