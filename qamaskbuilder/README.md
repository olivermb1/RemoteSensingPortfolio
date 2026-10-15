# QA Mask Builder

Pick a NASA product, choose the quality flags to drop, get a clean mask (1 usable, 0 masked, 255 no data) and a styled layer. One flag list, `qamask/flags.json`, drives all three versions:

- **Python** command line and library (`qamask/`)
- **QGIS plugin** with one Processing tool per product, set up to load on QGIS 4 (`qgis_plugin/`)
- **Earth Engine** script (`gee/qamask_gee.js`, generated from the same JSON)

It also fixes the **HLS southern-hemisphere CRS bug**. HLS v2.0 files south of the equator are labelled with a northern UTM zone (e.g. EPSG:32619) and use negative northings. LP DAAC confirmed the cause in January 2026 and has given no fix date ([forum thread](https://forum.earthdata.nasa.gov/viewtopic.php?p=24898)). I found that **OPERA DSWx-HLS tiles have the same bug**: the real T19JHN DSWx tile in `demo/data` is also EPSG:32619 with negative Y. The fix relabels the file as EPSG:327zz and adds 10,000,000 m to Y. No pixels are resampled. On the demo tile the corner latitudes and longitudes come out identical before and after the fix (checked with pyproj in the tests).

## Products

| Key | Layer | Confidence in the bit table |
|---|---|---|
| `hls_fmask` | HLS v2.0 Fmask (L30 and S30) | High. A test checks the table against the bit description stored inside a real Fmask file |
| `landsat_c2_qa_pixel` | Landsat 4-9 C2 QA_PIXEL | High. Checked against USGS reference values (21824 clear, 21952 water, 22280 cloud, 1 fill) |
| `landsat_c2_sr_qa_aerosol` | Landsat 8/9 SR_QA_AEROSOL | Medium-high, from LSDS-1619 |
| `modis_mod09_state_1km` | MOD09GA/MYD09GA state_1km | Medium-high, matches the Earth Engine band table |
| `modis_mod13_detailed_qa` | MOD13 DetailedQA (VI Quality) | Medium-high |
| `modis_mod13_summary_qa` | MOD13 SummaryQA (pixel reliability) | High |
| `modis_mod11_qc` | MOD11 QC_Day / QC_Night | Medium-high |
| `ecostress_lste_qc` | ECOSTRESS L2 LSTE QC | **Medium.** Written from the v001/v002 guides; check bits 4-5 against the current guide |
| `ecostress_cloud` | ECOSTRESS cloud layer (0 clear, 1 cloud) | Medium |
| `opera_dswx_hls_wtr` | OPERA DSWx-HLS WTR/BWTR classes | High. Values seen in a real tile match the spec |
| `opera_dswx_hls_conf` | OPERA DSWx-HLS CONF | Medium-high. Classes 10-14 in a real tile add up exactly to the WTR cloud count; the 20s (snow) were not seen |
| `opera_dist_alert_status` | OPERA DIST-ALERT VEG-DIST-STATUS | **Medium.** From the v1 spec, not checked against a real file |

`python -m qamask flags <key>` prints every field, flag and preset. Each product has presets such as `clear`, `clear_land` and `strict`. Class layers (DSWx, DIST) also take `--keep`: for example, keep only high-confidence water, or only confirmed disturbance.

## Quick start

```sh
pip install numpy rasterio            # or run inside QGIS's Python, which uses GDAL instead
python -m qamask build HLS.S30.T36MZE.2024015T074231.v2.0.Fmask.tif            # default preset, CRS fixed
python -m qamask build *_QA_PIXEL.TIF --drop clear,water --buffer 2 --out-dir masks/
python -m qamask build OPERA_*_B03_CONF.tif --drop observed --keep water_high,water_moderate
python -m qamask apply scene_SR_B5.TIF --mask masks/scene_QA_PIXEL_mask.tif --out b5_clean.tif
python -m qamask decode HLS...Fmask.tif          # one named band per field, for inspection
python -m qamask fix-crs HLS.*.tif --vrt         # just the CRS fix; a VRT copies no pixels
```

Each mask comes with a `.qml` (QGIS styles it red and green when you open it) and a `.json` report. The report holds the flags used, the usable share, the CRS decision and the share of pixels carrying each flag.

`--fix-crs auto` (the default) applies the fix to HLS and OPERA only. Landsat Collection 2 uses northern zones south of the equator on purpose, so it is left alone unless you pass `--fix-crs yes`.

**QGIS:** run `python qgis_plugin/make_plugin.py`, then use *Plugins › Install from ZIP* with `qgis_plugin/qa_mask_builder.zip`. The Processing Toolbox gains *QA Mask Builder* with 12 *Build mask* tools, *Apply mask to image*, *Decode QA layer* and *Fix HLS southern-hemisphere CRS*. They work in batch mode and the Model Builder.

**Earth Engine:** paste `gee/qamask_gee.js` into the Code Editor. It runs a demo: a clear HLS median around Lake Naivasha, Kenya, plus a Landsat 9 mask. As a module: `QAMask.apply(img, 'hls_fmask', {drop: ['clear'], buffer: 2})`. After editing the JSON, run `python -m qamask.gee_build` to regenerate the script.

## Demo

`sh demo/run_demo.sh` uses real files only:

- **Landsat 8 over Narok, Kenya, 4 Nov 2024.** This is a 45 km crop from the Digital Earth Africa bucket. The `clear` preset with a 1-pixel buffer keeps 69% of pixels. 12.5% are cloud, 11.3% shadow and 4.7% high-confidence cirrus. See `demo/output/kenya_landsat_mask.png`. NDVI over the kept pixels averages 0.67.
- **HLS L30 Fmask tile T19JHN (northern Argentina, 5 Oct 2024).** The `clear` preset keeps 82.8%, and the mask is written as EPSG:32719. It came from OPERA's public validation bucket. That was the only place I could reach a real southern-hemisphere HLS file, because LP DAAC is blocked from here and the bucket has no African tiles.
- **OPERA DSWx-HLS CONF, same tile.** A high-confidence water mask, also relabelled EPSG:32719.

## What was tested, and what wasn't

Tested here:
- 18 pytest tests on both raster backends (rasterio, and GDAL-only as inside QGIS): `python -m pytest tests/`
- All 15 plugin tools run headless in **QGIS 3.34**, including the style loading: `python3 tests/qgis_smoke.py OUT_DIR`
- The Earth Engine logic runs in Node on a stand-in for `ee.Image` and matches the Python masks pixel for pixel. That covers 10 cases on real HLS, Landsat and DSWx crops, and on random MODIS and ECOSTRESS values: `node gee/test_gee_mock.js`

Not tested:
- **QGIS 4.** Only 3.34 could be installed here. The plugin declares `qgisMaximumVersion=4.99` and `supportsQt6=True` and uses the newer enum names where they exist, but nobody has loaded it in QGIS 4 yet.
- **Real Earth Engine.** The dataset IDs, the HLS band names and the reflectance scale used in the demo's display range have not been run in the Code Editor.
- **MODIS, ECOSTRESS and DIST on real files.** Their bit tables are tested on synthetic values only.
- The `metadata.txt` email and homepage are placeholders. Replace them before submitting the plugin to plugins.qgis.org.

Harmless message: GDAL prints `MissingRequired: TIFF directory is missing required "ImageLength" field` when it opens the real HLS and DSWx files. It comes from the files themselves, and reading works normally.

## Layout

```
qamask/flags.json      the one flag list
qamask/core.py         bit decoding, masks, buffer (numpy only)
qamask/crsfix.py       HLS/OPERA southern-hemisphere CRS decision
qamask/io.py           rasterio or GDAL backend; ops.py, cli.py, style.py
qgis_plugin/           QGIS Processing plugin and make_plugin.py
gee/                   template.js -> qamask_gee.js, Node test + fixture
demo/                  real data, run_demo.sh, outputs
tests/                 pytest, QGIS smoke test, fixture builder
```
