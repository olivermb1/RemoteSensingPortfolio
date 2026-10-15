"""Draw demo/output/kenya_landsat_mask.png: false colour, the QA mask, and NDVI before and after masking."""

import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from qamask import io  # noqa: E402

O = sys.argv[1] if len(sys.argv) > 1 else "demo/output"
D = "demo/data/LC08_L2SP_169060_20241104_20241113_02_T1"
red = io.read(D + "_SR_B4_crop.tif") * 2.75e-5 - 0.2
nir = io.read(D + "_SR_B5_crop.tif") * 2.75e-5 - 0.2
mask = io.read(os.path.join(O, "kenya_landsat_clear_mask.tif"))
ndvi = np.clip((nir - red) / np.clip(nir + red, 1e-6, None), -1, 1)
masked = np.where(mask == 1, ndvi, np.nan)

fig, ax = plt.subplots(1, 3, figsize=(15, 5.4), constrained_layout=True)
rgb = np.dstack([np.clip(nir / 0.45, 0, 1), np.clip(red / 0.2, 0, 1), np.clip(red / 0.2, 0, 1)])
ax[0].imshow(rgb)
ax[0].set_title("Landsat 8, 4 Nov 2024, Narok, Kenya\n(NIR, red, red)")
ax[1].imshow(np.where(mask == 255, np.nan, mask), cmap=matplotlib.colors.ListedColormap(["#d73027", "#1a9850"]), vmin=0, vmax=1)
ax[1].set_title(f"QA_PIXEL mask, preset 'clear' + 1 px buffer\nusable {np.mean(mask[mask != 255] == 1):.0%} (green)")
im = ax[2].imshow(masked, cmap="YlGn", vmin=0, vmax=0.9)
ax[2].set_title(f"NDVI after masking\nmean {np.nanmean(ndvi):.2f} unmasked, {np.nanmean(masked):.2f} masked")
fig.colorbar(im, ax=ax[2], shrink=0.8)
for a in ax:
    a.set_axis_off()
out = os.path.join(O, "kenya_landsat_mask.png")
fig.savefig(out, dpi=90)
print(out)
