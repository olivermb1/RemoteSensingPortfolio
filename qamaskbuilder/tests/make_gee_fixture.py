"""Write gee/fixture.json: small QA arrays from the demo files plus the Python core's masks, for gee/test_gee_mock.js."""

import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from qamask import core, io  # noqa: E402
from qamask.registry import get_product  # noqa: E402

D = os.path.join(ROOT, "demo", "data")
rng = np.random.default_rng(0)


def crop(path, r0, c0, n=60):
    return io.read(os.path.join(D, path))[r0:r0 + n, c0:c0 + n]


CASES = [
    ("hls_fmask", crop("HLS.L30.T19JHN.2024279T141847.v2.0.Fmask.tif", 1800, 1800), [{}, {"drop": ["strict", "water"], "buffer": 2}]),
    ("landsat_c2_qa_pixel", crop("LC08_L2SP_169060_20241104_20241113_02_T1_QA_PIXEL_crop.tif", 700, 700),
     [{}, {"drop": ["cloud_conf_medium", "shadow"], "buffer": 1}]),
    ("opera_dswx_hls_conf", crop("OPERA_L3_DSWx-HLS_T19JHN_20241005T141847Z_L8_30_v1.0_B03_CONF.tif", 2000, 1500),
     [{}, {"drop": ["observed"], "keep": ["water_high", "water_moderate"]}]),
    ("modis_mod09_state_1km", rng.integers(0, 65536, (30, 30)), [{}, {"drop": ["clear_land"]}]),
    ("modis_mod13_summary_qa", rng.integers(-1, 4, (30, 30)).astype(np.int16), [{}]),
    ("ecostress_lste_qc", rng.integers(0, 65536, (30, 30)), [{}]),
]

out = []
for key, qa, opts in CASES:
    p = get_product(key)
    for o in opts:
        m = core.build_mask(qa, p, o.get("drop"), o.get("keep"), o.get("buffer", 0))
        out.append({"product": key, "options": o, "qa": qa.astype(int).tolist(), "mask": m.astype(int).tolist()})
with open(os.path.join(ROOT, "gee", "fixture.json"), "w") as fh:
    json.dump(out, fh)
print(len(out), "cases")
