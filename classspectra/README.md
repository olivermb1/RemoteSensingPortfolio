# ClassSpectra

Per-class spectral signatures from a multispectral image and a land cover map, built as a check on how far you can trust the map. This is option 7 from the shortlist ("Land Cover Signatures"). It has a new name because SCP already ships a tool called "Land Cover Signature Classification". ClassSpectra is a working name.

You give it an image (Sentinel-2 L2A or NASA HLS), a land cover map (ESA WorldCover, Impact Observatory/Esri LULC, Dynamic World or any integer map) and, optionally, a quality layer and an area. It returns, for each class:

- a spectral curve (median, with 10/25/75/90th percentiles, plus mean and std for comparison), as a chart and a CSV;
- pixel counts at each cleaning step, the outlier share, a spread index and median NDVI;
- Jeffries–Matusita separability between all class pairs;
- optionally, a **map-vs-map comparison**: the same pixels labelled by two maps, recoded to shared broad classes, showing per-class agreement and how far the signatures move.

## Why the cleaning matters

A classifier can tolerate noisy labels. A signature can't, because every mislabelled pixel goes straight into the statistics. So before computing anything, ClassSpectra:

1. **Aligns the map to the image grid.** It uses nearest neighbour when the map is the same resolution as the image or coarser. When the map is finer (10 m WorldCover on 30 m HLS) it takes the majority class and records a **purity** value per pixel.
2. **Masks bad pixels** using the quality layer: Sentinel-2 SCL values, or HLS Fmask bits.
3. **Erodes class borders** by N pixels, where mixed pixels and misregistration sit. If erosion would wipe out a rare or thin class (roads, rivers, wetland), it keeps that class and says so.
4. **Drops impure pixels** (purity below 0.75 by default) when the map is finer than the image.
5. **Trims spectral outliers** with a robust z-score against the class median (MAD-based, threshold 3.5).
6. **Reports medians and percentiles** rather than mean ± std.

## Quick start (standalone)

```sh
pip install -r requirements.txt
python -m classspectra IMAGE.tif LANDCOVER.tif --preset s2_l2a --legend worldcover \
    --mask SCL.tif --mask-invalid 0,1,3,8,9,10,11 --bbox 35.98 -0.42 36.18 -0.20 --out out/
# compare two maps over the same pixels
python -m classspectra IMAGE.tif worldcover.tif --compare io_lulc.tif --compare-legend io \
    --map-names WorldCover IO --out out/
```

For HLS, use `--preset hls_s30` or `--preset hls_l30` with a band stack in native band order, plus `--mask Fmask.tif --mask-bits 15` (rejects cirrus, cloud, adjacent and shadow).

**Sentinel-2 offset gotcha:** use `s2_l2a` when the 1000 DN offset has already been removed, as in the AWS sentinel-cogs COGs. That bucket's metadata still lists offset −0.1, but the pixel values say otherwise: forest blue is about 440 DN, which would be negative if the offset were still in. Use `s2_l2a_offset` for raw ESA L2A DN from baseline 04.00 onwards. The tool warns you if more than 2% of reflectances come out negative.

Outputs in `--out`: `signatures.csv` (long format: class × band × statistics), `class_summary.csv`, `signatures.png`, `separability.csv/png` and `run.json`. A comparison run adds `compare_summary.csv`, `compare_signatures.csv/png`.

## In QGIS

Go to Processing Toolbox › Scripts › *Add Script to Toolbox…* and pick `qgis/classspectra_processing.py`. It appears under **Map QA › Land cover class spectra (ClassSpectra)**. The script finds the `classspectra` package in the folder above it, or in `CLASSSPECTRA_PATH`. It uses only GDAL, numpy and matplotlib, which ship with QGIS. If matplotlib is missing it still writes the CSVs.

*Tested:* the script's GDAL code path was run outside QGIS with stubbed `qgis` modules (`tests/qgis_smoke.py`), and it matches the standalone results. It has **not yet been loaded inside a real QGIS 3.x/4.x install**, because none is available here. The map-comparison mode is CLI-only for now.

## In Google Earth Engine (JavaScript)

`gee/classspectra_gee.js` is the same tool for the Earth Engine Code Editor. Paste it into https://code.earthengine.google.com, edit `SETTINGS` at the top and press Run. Charts and tables appear in the Console, and a CSV export is queued in the Tasks tab. It needs no downloads:

- **Images:** Sentinel-2 L2A harmonized, masked with Cloud Score+ (`cs >= 0.6`), or NASA HLS S30/L30 v002 masked with Fmask. It makes a median composite over the date range.
- **Maps:** WorldCover 2021 or 2020, Dynamic World (mode of `label` over the dates) or Impact Observatory/Esri annual LULC from the community catalog. Set `compareMap` to run the map-vs-map comparison.
- **Cleaning:** the same steps as the Python version. It erodes borders with a focal min/max, skips erosion for thin classes, keeps the majority class plus a purity filter on 30 m HLS, and trims outliers with a MAD z-score. All of it runs as grouped reducers, about 8 passes per map. JM separability is computed in the browser from per-class covariances.

*Tested:* the pure-JS maths (JM, spectral angle, assembling the results) matches the Python core in Node (`node gee/test_gee_helpers.js`). The whole script also runs end to end against a stand-in `ee` (`node gee/test_gee_mock.js`), for all three sensors and all three maps. That proves the script's own logic, not Earth Engine's response. It has **not been run in the real Code Editor yet**, because this sandbox has no Earth Engine account. The first real run may surface an API detail to fix. If it times out, shrink `bbox` or set `compareMap: null`. The default is a Jan–Feb 2024 composite rather than the single scene used below, so its numbers will differ a little from the Python demo.

## Demo: Nakuru, Kenya

Run `demo/run_demo.sh` to reproduce it. The two Sentinel-2 rasters (`nakuru_s2_20240215.tif`, 41 MB, and `nakuru_s2_30m.tif`, 9 MB) are not in git; `demo/make_demo_data.py`, which `run_demo.sh` calls first, downloads them again. The area is 22 × 24 km around Lake Nakuru, with the town, farmland, forest and the lake. The image is Sentinel-2 L2A from 15 Feb 2024 (scene S2A_36MZE_20240215, 1.6% cloud). The maps are ESA WorldCover 2021 (v200) and 2020 (v100). All the data is free with no login.

| Output | What it shows |
|---|---|
| `demo/output_10m/signatures.png` | Cleaned signatures, 8 classes |
| `demo/output_10m/separability.png` | Grassland vs Cropland JM 0.53, Tree vs Shrub 0.64: weakly separable in the dry season |
| `demo/output_10m/compare_signatures.png` | WorldCover 2021 vs 2020 on the same pixels |
| `demo/output_30m/` | Same scene on a 30 m HLS-like grid, using majority + purity |
| `demo/output_10m_raw/` | No cleaning, as a baseline |

What it found:

- **The cleaning catches what the cloud mask missed.** SCL flagged only about 2% of the area, but cloud is visible over the lake. The outlier filter removed 23% of "water" pixels and cut the water spread index from 1.36 to 0.44.
- **The cleaning changes the answer.** Built-up median NDVI is 0.24 raw and 0.20 cleaned. Tree cover NDVI is 0.54 raw and 0.58 cleaned.
- **The two map versions disagree a lot.** Only 54% of WorldCover 2021 built-up and 62% of its cropland and trees match the 2020 version. Wetland matches 8%. WorldCover 2020 calls 3.3× as much land shrub.
- **The disagreement shows up in the spectra.** Pixels that 2021 calls built-up have a median NDVI of 0.20. Pixels both maps agree are built-up have 0.15. So the extra 2021 built-up area is greener, which suggests vegetated peri-urban land. This is the Kerner-style "your map choice changes your signal" result, at small scale. Swapping in IO's map would be the stronger test, but its server was unreachable from this sandbox.

## Layout

```
classspectra/core.py      numpy maths: erosion, outliers, stats, JM, map agreement
classspectra/io.py        rasterio reading and alignment (standalone only)
classspectra/report.py    CSV/JSON/charts
classspectra/legends.py   WorldCover, IO, Dynamic World legends + broad cross-walk
classspectra/sensors.py   band presets (S2 L2A, HLS S30/L30)
classspectra/cli.py       command line
qgis/                     Processing script (GDAL based)
gee/                      Earth Engine Code Editor script + Node tests
tests/                    synthetic unit tests, QGIS smoke test
demo/                     data download, runner, outputs
```

## Not done yet

- Temporal mode: NDVI profiles per class across a time series. This is the strongest Africa angle, because seasons there are short and bimodal.
- Dynamic World probability thresholds, as an agreement-style filter.
- Per-tile (local) signatures for large areas.
- Map comparison in the QGIS script, and packaging as a proper QGIS plugin.
- Validating "spread / outlier share" as a map-error index against reference points, such as Kerner 2024's.
