"""Compare our Sentinel-2 clear-observation count with GeoMAD's own COUNT band."""
import json
import os

import numpy as np
import rasterio

D = os.path.join(os.path.dirname(os.path.abspath(__file__)))
with rasterio.open(os.path.join(D, "data", "geomad_2024H1.tif")) as s:
    gm = s.read(7).astype(float)
with rasterio.open(os.path.join(D, "output_geomad", "qa_layers.tif")) as s:
    ours = s.read(list(s.descriptions).index("NCLEAR") + 1).astype(float)
ok = (gm > 0) & (ours >= 0)
d = ours[ok] - gm[ok]
res = {
    "pixels": int(ok.sum()),
    "geomad_count_median": float(np.median(gm[ok])), "ours_median": float(np.median(ours[ok])),
    "difference_median": float(np.median(d)), "difference_p10_p90": [float(np.percentile(d, 10)), float(np.percentile(d, 90))],
    "correlation": float(np.corrcoef(gm[ok], ours[ok])[0, 1]),
}
json.dump(res, open(os.path.join(D, "output_geomad", "count_vs_geomad.json"), "w"), indent=1)
print(json.dumps(res, indent=1))
