"""How much the Sentinel-1 demo result moves with the SAR thresholds.
Writes demo/sensitivity.csv (flooded cropland ha, whole area and top zones)."""
import csv
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from floodcrop import pipeline  # noqa: E402

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
OUT = tempfile.mkdtemp()  # rasters from these runs are throwaway
ZONES = ["Nyakach", "Nyando", "Karachuonyo"]
runs = [
    ("default: Otsu, drop 3 dB, loose -14", dict()),
    ("threshold -16 dB", dict(sar_threshold=-16.0)),
    ("threshold -18 dB", dict(sar_threshold=-18.0)),
    ("drop 2 dB", dict(drop_db=2.0)),
    ("drop 4 dB", dict(drop_db=4.0)),
    ("loose -12 dB", dict(loose_db=-12.0)),
    ("loose -13 dB", dict(loose_db=-13.0)),
    ("loose -15 dB", dict(loose_db=-15.0)),
    ("threshold only (no change test)", dict(sar_method="threshold")),
    ("smooth 3 px", dict(smooth=3)),
    ("smooth 9 px", dict(smooth=9)),
]
rows = []
for label, kw in runs:
    opts = dict(sar_method="change", drop_db=3.0, loose_db=-14.0, smooth=5)
    opts.update(kw)
    r = pipeline.run("sar", [f"{D}/s1/S1_VV_20240506.tif"], [f"{D}/s1/S1_VV_20240224.tif", f"{D}/s1/S1_VV_20240307.tif"],
                     f"{D}/deafrica_cropmask_2019.tif", "deafrica", f"{D}/zones_subcounties.geojson", None,
                     f"{D}/wofs_alltime_frequency.tif", 0.8, out_dir=OUT, **opts)
    z = {x["zone"]: x["flooded_crop_ha"] for x in r["rows"]}
    row = dict(setting=label, whole_area_ha=round(r["whole"]["flooded_crop_ha"]),
               **{f"{k}_ha": round(z.get(k, 0)) for k in ZONES})
    rows.append(row)
    print(row)
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "sensitivity.csv"), "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
