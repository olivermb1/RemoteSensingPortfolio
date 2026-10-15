"""Product definitions loaded from flags.json."""

import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
FLAGS_JSON = os.path.join(_HERE, "flags.json")

_BITS = {"uint8": 8, "int16": 16, "uint16": 16, "int32": 32, "uint32": 32}


class Product:
    def __init__(self, key, d):
        self.key = key
        self.title = d["title"]
        self.layer = d["layer"]
        self.dtype = d["dtype"]
        self.fill = list(d.get("fill", []))
        self.fill_rule = d.get("fill_rule")
        self.hints = d.get("filename_hints", [])
        self.source = d.get("source", "")
        self.gee = d.get("gee", {})
        self.fields = {f["name"]: f for f in d["fields"]}
        self.flags = {f["name"]: f for f in d["flags"]}
        self.presets = d.get("presets", {})
        self.default_preset = d.get("default_preset")
        for f in self.flags.values():
            if f["field"] not in self.fields:
                raise ValueError(f"{key}: flag {f['name']} uses unknown field {f['field']}")
        for name, flags in self.presets.items():
            bad = [f for f in flags if f not in self.flags]
            if bad:
                raise ValueError(f"{key}: preset {name} names unknown flags {bad}")
        for f in self.fields.values():
            start, n = f["bits"]
            if start + n > _BITS[self.dtype]:
                raise ValueError(f"{key}: field {f['name']} runs past {self.dtype}")

    def resolve(self, names):
        """Expand a list of flag and preset names into flag names, in order."""
        out = []
        for n in names or []:
            n = n.strip()
            if not n:
                continue
            if n in self.presets:
                out.extend(self.presets[n])
            elif n in self.flags:
                out.append(n)
            else:
                raise KeyError(f"'{n}' is not a flag or preset of {self.key}. Flags: {', '.join(self.flags)}. "
                               f"Presets: {', '.join(self.presets)}")
        seen = set()
        return [x for x in out if not (x in seen or seen.add(x))]

    @property
    def is_hls_family(self):
        """HLS and OPERA HLS products share the southern-hemisphere CRS bug."""
        return self.key.startswith("hls_") or self.key.startswith("opera_")


def load(path=FLAGS_JSON):
    with open(path) as fh:
        d = json.load(fh)
    return {k: Product(k, v) for k, v in d["products"].items()}


PRODUCTS = load()


def get_product(key):
    if key not in PRODUCTS:
        raise KeyError(f"unknown product '{key}'. Known: {', '.join(PRODUCTS)}")
    return PRODUCTS[key]


def detect_product(filename):
    """Guess the product from a file name; the longest matching hint wins. None if no hint matches."""
    name = os.path.basename(filename)
    best, best_len = None, 0
    for p in PRODUCTS.values():
        for h in p.hints:
            if h in name and len(h) > best_len:
                best, best_len = p, len(h)
    return best
