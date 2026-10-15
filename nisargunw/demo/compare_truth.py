"""Compare each demo run's los_displacement.tif with the invented truth.

Both are zeroed differently, so the median difference is removed first; what
is left is the error a user would see. Prints a Markdown table."""
import glob
import json
import os
import sys

import numpy as np
import rasterio
import rasterio.windows

here = os.path.dirname(os.path.abspath(__file__))
tsrc = rasterio.open(os.path.join(here, "data", "truth_los_displacement.tif"))
print("| Run | Corrections | Heights | Kept | Error after removing offset (RMS, mm) | Worst 1% (mm) |")
print("|---|---|---|---:|---:|---:|")
for d in sorted(glob.glob(os.path.join(here, "output", "*"))):
    f = glob.glob(os.path.join(d, "*_los_displacement.tif"))
    if not f:
        continue
    with rasterio.open(f[0]) as src:
        a = src.read(1)
        win = rasterio.windows.from_bounds(*src.bounds, transform=tsrc.transform).round_offsets().round_lengths()
    truth = tsrc.read(1, window=win)
    meta = json.load(open(glob.glob(os.path.join(d, "*_metadata.json"))[0]))
    m = np.isfinite(a) & np.isfinite(truth)
    e = (a - truth)[m]
    e -= np.median(e)
    h = meta.get("heights", {})
    hs = "DEM" if h.get("source") != "constant" else f"constant {h.get('value_m', 0):g} m"
    print(f"| {os.path.basename(d)} | {', '.join(meta['corrections']['applied']) or 'none'} | {hs} | "
          f"{meta['kept_fraction'] * 100:.0f}% | {np.sqrt(np.mean(e ** 2)) * 1000:.1f} | "
          f"{np.percentile(np.abs(e), 99) * 1000:.1f} |")
