# Time Profile

**Click a spot on the map (or select fields), get a cloud-masked chart of NDVI or any index through time.** This is option 2 from the shortlist: time-series charts for QGIS 4. The Temporal Profile Tool plugin, which most people used for this, was abandoned in September 2023 and does not run on QGIS 4 (Qt6).

It reads a folder of scenes you already have, or fetches them for you:

- **NASA HLS v2.0**, with Landsat (L30) and Sentinel-2 (S30) mixed. It masks with Fmask.
- **Sentinel-2 L2A** in the AWS / Element 84 folder layout. It masks with SCL.
- **Landsat Collection 2 Level-2**, masked with QA_PIXEL.
- **Any GeoTIFF with a date in its name**, for example `ndvi_2024-03-01.tif`, `S2A_37MCV_20240303_0_L2A.tif` or `MOD13Q1.A2024129.tif`. Bands are named from their descriptions. A `_Fmask`, `_SCL`, `_QA_PIXEL` or `_mask` file beside it is used as its mask.

Only the pixels under each point or polygon are read, so a two-year chart from 100 scenes takes a few seconds.

| Form | Where | Status |
|---|---|---|
| Python package and command line | `timeprofile/` | **Tested** on real Sentinel-2 data (Mwea, Kenya) and on synthetic HLS, Landsat-style and plain GeoTIFFs (`tests/test_core.py`, 12 tests) |
| QGIS plugin: a chart panel plus a Processing tool | `qgis_plugin/time_profile.zip` | **Not run in QGIS.** The chart and the panel were run under real Qt6 (PyQt6) with stand-in QGIS classes, which covers scanning, clicking, changing the index and view, and saving. The Processing tool and the GDAL reader have not run at all. |
| Google Earth Engine script | `gee/timeprofile_gee.js` | **Not run in Earth Engine.** Only a Node mock run checks that it executes end to end. |

## What you get

For each place, index and date you get one row in `series.csv`. Each row has the mean, median, standard deviation and p10/p90 over the clear pixels, the counts of pixels, valid pixels and clear pixels, and a status. The status is `clear`, or `masked` when too few pixels were clear. Rows are also flagged when they are a likely missed cloud (`spike`).

- **`chart.png`** has one panel per index and one colour per place. Dots are observations, with a circle for Sentinel-2 and a triangle for Landsat. Hollow dots are flagged spikes. The line is a smooth curve (a Whittaker smoother, about one month wide) that **breaks wherever there are no clear observations for 60+ days**, so it never makes up a season under the clouds.
- **`seasons_<INDEX>.png`** has one small chart per place, with each year (or season) as its own line, for comparing years. Seasons can start in any month (`--season-start 10` for Oct to Sep).
- **`seasons.csv`** has one row per place and season, with the number of clear observations, the mean, and the peak and low (value and date, from the smooth curve).
- **`run.json`** records the settings, notes on skipped scenes and dropped duplicates, and the counts.

Spike rule: a single date that differs from both neighbours by more than 0.1 in the same direction, while the neighbours agree with each other. A real harvest, fire or flood carries on into the next date and is not flagged. Flagged dots stay in the CSV and on the chart. They are only left out of the smooth curve.

Where MGRS tiles overlap, the same day can be seen twice. Only the copy with the most clear pixels is kept.

Indices: NDVI, EVI, EVI2, SAVI, NDWI, MNDWI, NDMI, NBR, NDRE and BSI. You can also give any band (`red`, `nir`, `swir1` …) or your own formula, such as `MSI=swir1/nir`. Formulas are parsed and checked, never passed to plain `eval`.

## Command line

```bash
pip install -r requirements.txt

# Free Sentinel-2 for any small area, no login (AWS Open Data). One multi-band file per scene.
python -m timeprofile fetch-s2 --bbox 37.32 -0.675 37.36 -0.635 --start 2023-01-01 --end 2024-12-31 --out scenes/ --res 20

# NASA HLS (Landsat + Sentinel-2) for the same area; needs an Earthdata login in ~/.netrc
python -m timeprofile fetch-hls --bbox 37.32 -0.675 37.36 -0.635 --start 2023-01-01 --end 2024-12-31 --out hls/

python -m timeprofile scan --scenes scenes/ --list
python -m timeprofile extract --scenes scenes/ --features fields.geojson --index NDVI,NDMI --out out/
python -m timeprofile extract --scenes hls/ --point 37.3367,-0.6693,"my field" --buffer 1 --out out2/
python -m timeprofile chart out/series.csv --seasons --season-start 10    # redraw from the CSV
python -m timeprofile indices
```

Other options are `--start/--end`, `--sensors HLS.S30,S2` and `--tiles 37MCV`. `--min-clear 50` sets the % of a polygon that must be clear. `--also-mask water` (or `aerosol_moderate` or `cirrus`) adds flags to the HLS and Landsat masks, and `--no-mask` turns masking off. `--smooth 0` turns the curve off, and `--spike 0` turns the spike flags off. For plain GeoTIFFs you can set `--band-names blue,green,red,nir` and `--scale 0.0001 --offset 0`. Features are GeoJSON points or polygons in lon/lat, named by a `name` property or by `--name-field`.

## QGIS (3.28 and up, including QGIS 4)

Build the zip with `python qgis_plugin/make_plugin.py` (it is not kept in git), then install `qgis_plugin/time_profile.zip` through Plugins > Manage and Install Plugins > Install from ZIP. The plugin needs nothing beyond what QGIS ships: it reads through QGIS's own GDAL and draws the chart itself, without matplotlib.

- **The Time Profile panel** (toolbar button, or Raster > Time Profile). Pick the scenes folder and press **Click on map**, then click. Each click adds a coloured marker and a matching series, so you can compare places. **Selected features** charts the selected points or polygons of the active layer. You can change the index (or type a formula), turn the cloud mask on or off, set a point buffer, or switch to **Season by season** for one place. Hover a dot for its date, sensor, value and clear-pixel count. **Save CSV** and **Save PNG** export what is shown. Reading runs in the background.
- **Processing > Time Profile > Time series for features** does the same for a whole layer and writes the CSVs and charts listed above. The chart images need matplotlib, which the standard QGIS installers include.

`tests/qgis_smoke.py` is a script to run in the QGIS Python console. It runs the Processing tool on the demo data, then opens the panel on the demo folder.

## Google Earth Engine

Paste `gee/timeprofile_gee.js` into the Code Editor. Click the map or draw polygons to get a chart from **HLS L30 and S30 together** (Fmask-masked) or from Sentinel-2 L2A (`COPERNICUS/S2_SR_HARMONIZED`, SCL-masked). Polygons follow the same min-clear rule. It has a season-by-season view and an **Export CSV** button that sends the observations to Drive. GEE has no smooth curve or spike flags. If you need them, export the CSV and run `python -m timeprofile chart`. The script scales HLS only when GEE stores it as integers, a check it makes at run time because this was not confirmed against the catalogue.

## Demo: Mwea irrigation scheme, Kenya (real data)

`demo/run_demo.sh` runs the demo. The data is Sentinel-2 L2A at 20 m for a 4.5 × 4.4 km box at the north edge of the Mwea rice scheme in Kirinyaga, from January 2023 to December 2024. It comes from the free AWS bucket via `demo/make_demo_data.py`, about 50 MB, into `demo/data/s2_mwea/`. Those scenes are not in git; `run_demo.sh` downloads them on first run. Of 148 scenes, 100 had at least 5% clear sky over the box. `demo/mwea_features.geojson` holds four places I picked from a clear January 2024 image:

- two paddy blocks (16 and 36 pixels),
- one single pixel in the west block,
- a village with farm plots (225 pixels).

Results are in `demo/output/` and come from 800 observations, 516 of them clear:

- **Paddies swing between NDVI ~0.1 and ~0.85, two or more times a year.** For example, the north block peaked on 21 April 2024 at 0.85 and fell to 0.12 in early February 2024. MNDWI rises to around 0 or above just before green-up. That is the flooding of the paddies, so a water index sees it where NDVI only sees a dip.
- **The village stays between 0.25 and 0.55 all year.**
- **The long rains (April to June) and June to September leave 60 to 90 day gaps in some years.** The curve breaks there instead of guessing (for example, July to September 2023).

Two things about the source data turned up here and are handled in the code:

- **The AWS Sentinel-2 files need no −0.1 offset**, even though their metadata lists one. When Element 84 says `boa_offset_applied: true`, it has already removed it. Dark pixels sit near DN 370, which is impossible with the offset still in.
- **One Sentinel-2C scene (8 December 2024) says the offset is still in, but it isn't.** `fetch-s2` checks the pixels: clear land never has blue DN under 1000 when the offset is in, so it overrides the metadata. With that fixed, S2C agrees with S2A on the same day to within 0.003 NDVI. Separately, `extract` leaves out pixels with impossible reflectance (below −0.05 or above 2) and says so, so a wrong scale or offset shows up as a note and not as NDVI 1.4.

`demo/fetch_real_hls.sh` runs the same area from NASA HLS on your own computer. NASA's servers are blocked from the sandbox this was built in. It writes `demo/output_hls/` so you can compare it with the Sentinel-2 run.

## What is untested, plainly

- **Nothing has been run in QGIS.** The Qt6 chart widget and the panel's logic ran under PyQt6 with stand-in QGIS classes (`tests/test_chart_qt6.py`, `tests/test_dock_stubbed.py`). Untested in real QGIS are the map-tool click and its CRS transform, the markers and rubber bands, `QgsTask` threading, the Processing tool and `gdal_io.py`, because no GDAL Python bindings were available. QGIS 4 enum names are handled with a fallback, but that is unverified.
- **Not run in Earth Engine.** HLS band names and the Fmask bits follow the HLS v2 user guide. The `ui.Chart.feature.groups` date axis and the per-image `reduceRegions` cost on long periods are unchecked.
- **`fetch-hls` has not run**, because NASA is blocked here. It is adapted from Composite Check's fetcher, which also has not run.
- **The HLS and Landsat readers were tested only on synthetic files** that follow the official names and bit layouts, not on real downloads.
- **The demo features were chosen by eye.** I did not field-check that the paddy blocks are rice.

## Limits

- **`seasons.csv` gives one peak per season.** Paddies with two crops a year need a mid-year `--season-start` or a look at the chart.
- **Sentinel-2 and Landsat are not harmonised against each other here.** HLS does that, which is a reason to prefer HLS when mixing sensors.
- **The panel shows one index at a time.** The command line and the Processing tool take several.
- **Polygons smaller than one pixel fall back to the single pixel under the polygon's centre** (the `selection` column says `centroid`).
