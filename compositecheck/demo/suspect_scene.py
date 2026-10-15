"""Side-by-side true colour: the scene that dominates the closest-date composite vs the medoid composite."""
import os
import numpy as np
import rasterio
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

D = os.path.dirname(os.path.abspath(__file__))
SCENE = "S2B_36MZE_20240331_0_L2A"


def rgb(path, mask_path=None):
    with rasterio.open(path) as s:
        a = s.read([3, 2, 1]).astype(float) / 10000
        a[a < -0.5] = np.nan
    if mask_path:
        with rasterio.open(mask_path) as s:
            fm = s.read(1)
        cloud = (fm != 255) & ((fm & 0b1111) != 0)
        a[:, cloud] = np.nan
    return np.clip(np.moveaxis(a, 0, -1) / 0.18, 0, 1)


fig, ax = plt.subplots(1, 3, figsize=(13, 4.6))
panels = [(rgb(os.path.join(D, "data", "scenes", SCENE + ".tif")), f"{SCENE}\nas delivered"),
          (rgb(os.path.join(D, "data", "scenes", SCENE + ".tif"), os.path.join(D, "data", "scenes", SCENE + "_Fmask.tif")),
           "same scene, cloud mask applied\n(what the closest-date composite used)"),
          (rgb(os.path.join(D, "output_medoid", "composite.tif")), "medoid composite, Jan-Jun 2024")]
for a, (img, t) in zip(ax, panels):
    a.imshow(np.nan_to_num(img, nan=1.0))
    a.set_title(t, fontsize=9, loc="left")
    a.axis("off")
fig.savefig(os.path.join(D, "output_target", "suspect_scene.png"), dpi=100, bbox_inches="tight")
print("ok")
