# ECOSTRESS Geo Check

**Finds ECOSTRESS temperature scenes that are in the wrong place, and keeps them out of your analysis.** This is option 4 from the shortlist.

ECOSTRESS rides on the Space Station, whose own pointing is too rough for 70 m pixels. NASA fixes each scene by matching it to a basemap. When that matching fails (over water, cloud, or featureless land) the scene can be **2 to 7 km off**. NASA records how well it went in a per-scene flag, `GeolocationAccuracyQA` (best, good, suspect or poor), but the flag sits in a separate L1B GEO file, isn't carried into every higher-level product, and isn't in Earth Engine at all. So most users never see it, and a shifted scene quietly corrupts a time series, a field-site comparison or a city heat map.

This tool does three things per scene:

1. **Reads NASA's flag** wherever it can find it: L1B GEO `.h5` files, the granule's own metadata (GeoTIFF tags, a CMR `.json`/`.xml` sidecar), or a table of flags (NASA's summary file, or the `geo_flags.csv` that `fetch` writes).
2. **Measures the real offset** of each tiled LST scene, by lining up temperature edges (lake shores, coasts) with the scene's own `water` layer. This follows NASA JPL's geolocation tutorials, which shift LST against a water mask. It catches shifted scenes that have no flag, and confirms or questions the ones that do.
3. **Decides** keep, caution, check, drop, or (with `--fix`) shift back, and writes lists you can feed straight into the next step.

| Form | File | Status |
|---|---|---|
| Python package and command line | `ecogeocheck/` | Tested on synthetic data (16 tests) |
| QGIS Processing script | `qgis/ecogeocheck_processing.py` | **Run headless in QGIS 3.34** on the demo, both with h5py and with GDAL only. Not run in QGIS 4 or in the QGIS window |
| Google Earth Engine script | `gee/ecogeocheck_gee.js` | **Not run in Earth Engine.** Checked only against a fake `ee` in Node |

## How a scene is judged

| Situation | Decision |
|---|---|
| Flag is best or good (`--accept` to change), measured offset within tolerance or not measurable | **keep** |
| Flag is suspect or poor, or `OrbitCorrectionPerformed=False` | **drop** (`--rescue` keeps those that measure within tolerance) |
| Measured offset over the tolerance (default 140 m = 2 pixels), whatever the flag | **drop**, or **fixed** with `--fix` |
| No flag found, measured within tolerance | **keep** |
| No flag found and nothing to measure against | **check** (look at it yourself) |
| Otherwise kept, but in a dated problem window or `FieldOfViewObstruction=True` | **caution** |

Dated problems come from NASA's v002 product pages: the 15 May to 1 July 2025 noisy period (caution), ISS solar array obstruction (caution, and only reliable from 24 October 2024), plus notes for the 2018-19 storage anomalies, the 2019-2023 three-band period and the February 2020 band 4 striping.

**What the offset is measured against**, in order: a `--reference` raster you give (a water mask such as JRC Global Surface Water, or HLS NDVI); otherwise the scene's own `water` layer, if 0.5% to 90% of the clear view is water; otherwise the median of the scenes flagged *best* on the same tile. The match uses smoothed edge strength and a masked cross-correlation, so clouds are left out and it doesn't matter whether water is colder (day) or warmer (night) than land. A match counts only if it is strong and clearly better than the runner-up; otherwise the offset is reported as not measured, with the reason.

Using the scene's own water layer rests on an **inference**: L2 products look water up from a static map at each pixel's map position, so the water layer sits in the right place even when the temperatures are shifted. That is also why `--fix` moves every layer except `water` and `height`. If that turns out to be wrong for some product, pass `--reference` with an independent water mask.

## Outputs (one folder per run)

| File | Contents |
|---|---|
| `summary.md` | Table of scenes with flag, measured offset and decision, then the reasons for each |
| `scenes.csv` | One row per scene: orbit, scene, tile, time, decision, NASA flag and where it came from, orbit correction, obstruction, offset (m, east and north), match strength, reference used, reasons, files |
| `scenes.geojson` | Scene footprints with the same fields, to see in a GIS which parts of your area were dropped |
| `keep.txt`, `drop.txt` | File paths, one per line (`keep.txt` lists the shifted copies for fixed scenes) |
| `shifted/` | With `--fix`: copies of offset scenes with a corrected geotransform (no resampling) |
| `quicklook.png` | Offsets as a scatter (km east and north) and per scene, coloured by NASA flag |
| `run.json` | Everything above plus the options, for audit |

## Command line

```bash
pip install -r requirements.txt

python -m ecogeocheck check data/ --out check/                    # flags + measured offsets
python -m ecogeocheck check data/ --out check/ --summary flags.txt # add a table of flags
python -m ecogeocheck check data/ --out check/ --fix              # shift offset scenes back
python -m ecogeocheck check data/ --out check/ --reference jrc_occurrence.tif
python -m ecogeocheck check data/ --out check/ --no-measure       # NASA flags only, fast

# Options: --accept best,good  --tolerance 140  --max-shift 7700  --rescue  --no-stack  --io gdal
#          --summary-columns orbit=Orbit,scene=Scene,qa=GeoQA   (if the table's columns aren't detected)

python -m ecogeocheck fetch --bbox 36.0,-0.95,36.45,-0.12 --start 2025-01-01 --end 2025-08-31 --dest data/ --list
python -m ecogeocheck fetch --bbox 36.0,-0.95,36.45,-0.12 --start 2025-01-01 --end 2025-08-31 --dest data/
python -m ecogeocheck flags some_file.h5     # print the geolocation fields in a file
python -m ecogeocheck levels                 # what the flag levels and dated issues mean
```

Input files keep their NASA names; the orbit and scene numbers in them are how a tiled LST file is matched to its L1B GEO file and to a flag table, e.g. `ECOv002_L2T_LSTE_33138_005_37MBU_20240505T081052_0712_01_LST.tif` and `ECOv002_L1B_GEO_33138_005_20240505T081052_0712_01.h5`. Collection 1 names and AppEEARS outputs are recognised too; AppEEARS drops the orbit and scene, so those are matched to a flag table by time (within a minute) and are best given a `--reference`.

`fetch` searches NASA CMR for `ECO_L2T_LSTE.002` granules, downloads the LST, cloud and water layers, finds each scene's `ECO_L1B_GEO.002` granule, and writes the flags to `geo_flags.csv` (which `check` picks up from the folder). It takes the flag from CMR attributes if they hold it, otherwise it opens the L1B GEO file remotely with earthaccess and h5py, which reads only the metadata. It needs a free [NASA Earthdata](https://urs.earthdata.nasa.gov/) login in `~/.netrc` or `EARTHDATA_TOKEN`.

To try it on real data, run `demo/fetch_real_ecostress.sh` on your own computer. It checks January to August 2025 over the Kenyan Rift lakes, tile 37MAV.

## QGIS

Processing Toolbox > Scripts > Add Script to Toolbox… and pick `qgis/ecogeocheck_processing.py`. The script finds the package in the folder above itself, or through the `ECOGEOCHECK_PATH` environment variable. Inputs: a folder of ECOSTRESS files, an optional flag table, an optional reference raster, which NASA flags to keep, tolerance, search radius, and the measure, fix, rescue and add-to-map switches. When it finishes it adds the scene footprints (with decisions and reasons) and the kept LST layers to the map. It reads through GDAL, which QGIS ships; h5py is used if present, and otherwise L1B GEO files are read with GDAL's multidimensional HDF5 support.

## Google Earth Engine

`gee/ecogeocheck_gee.js` works on `NASA/ECOSTRESS/L2T_LSTE/V2`. For each image over your area it joins NASA's flag from a table you upload as an asset (set `FLAG_TABLE`; columns `orbit`, `scene`, `GeolocationAccuracyQA`, such as `geo_flags.csv` from `fetch`), measures the offset of LST edges against the image's own `water` band with `ee.Image.displacement`, decides keep / check / drop, maps mean LST of kept against all images, charts offsets over time and exports a per-image CSV. Untested points: the orbit and scene are read from `system:index` with a regular expression that assumes NASA's granule name is in the ID (the script prints the first image so you can check), and `displacement` hasn't been tried on 70 m edge images. `node gee/test_gee_mock.js` only checks that the script runs end to end against a fake `ee` and that the regular expression works on a v002 name.

One finding from writing it: Earth Engine's catalog page describes the v002 `QC` band with different bits (LST quality, sky condition, outlier, slope, snow, land/water) from the table in `../qamaskbuilder/` (which follows v001's layout). That doesn't affect this tool, but the QA Mask Builder's ECOSTRESS QC entry needs checking against the v002 guide.

## Demo (synthetic data, real landscape)

NASA's servers (CMR, LP DAAC) can't be reached from the sandbox where this was built, so the demo is synthetic. `demo/make_demo_data.py` builds 12 ECOSTRESS-style tiled scenes (January to August 2025) over Lake Nakuru, Lake Elmenteita and the north of Lake Naivasha in Kenya. The landscape is real: ESA WorldCover 2021, read from its public AWS bucket and cached in `demo/data/worldcover_rift_30m.tif`. The temperatures, clouds, flags and shifts are invented. Names, layers and the 70 m UTM grid follow collection 2; the L1B GEO `.h5` files hold only the metadata group. Flags are stored in all three ways the tool reads them (8 L1B GEO files, 1 CMR-style sidecar, 1 row in a made-up summary table) and 2 scenes have none. `demo/data/truth.json` lists the shift applied to each scene.

`demo/run_demo.sh` writes four runs to `demo/output/`:

| Run | Result |
|---|---|
| `default/` | 4 keep, 4 caution, 4 drop. The suspect and poor scenes measure 2.7 km and 5.2 km off (applied: 2.7 km and 5.2 km). An unflagged scene measures 1.26 km off (applied 1.29 km) and is dropped; another unflagged one measures 19 m and is kept (with caution, as it falls in the 2025 noisy period). The August scene is 85% cloud but still measures, and gets caution for a solar array obstruction. A night-time suspect scene measures only 71 m off and is dropped anyway, since NASA's flag wins unless you pass `--rescue`. |
| `fix/` | The three offset scenes are shifted back instead of dropped. |
| `fix_recheck/` | Re-checking those shifted copies gives 16 to 28 m, inside one pixel. |
| `flags_only/` | `--no-measure`: decisions from the flags alone. Both unflagged scenes come out as "check", so the shifted one isn't caught this way. |

Across the 12 scenes the measured offsets are within 75 m of the applied shifts (`tests/test_ecogeocheck.py` checks this). There is a small bias of about 20 m when matching against the water layer, which disappears when matching against other scenes; it is well inside the tolerance.

## What is tested and what isn't

Tested:
- 16 pytest tests: name parsing (v001, v002, AppEEARS), flag reading from HDF5, tags, CMR JSON and four table layouts, the dated issues, offset recovery with scattered cloud, refusing featureless images, the geotransform correction, every decision rule, and the demo end to end. `pytest tests -q`
- The QGIS script headless in QGIS 3.34 on the demo, with and without h5py: `/usr/bin/python3.12 tests/qgis_smoke.py` (and `NO_H5PY=1`).
- The Earth Engine script in a Node mock (see above).

Not tested:
- **Any real ECOSTRESS file.** The L1B GEO metadata layout (group `L1GEOMetadata`, fields stored as scalar strings or attributes; both are read), whether tiled GeoTIFFs carry the flag in their tags, and the real L2T `water` layer are all assumptions from NASA's documentation.
- **NASA's summary file.** Its layout wasn't seen, so the table reader guesses the columns and prints what it detected. Override with `--summary-columns` if it guesses wrong.
- **`fetch`** against live CMR and LP DAAC, including reading the flag remotely with earthaccess.
- **How well the offset measurement does on real scenes.** The synthetic scenes are cleaner than real ones: real day and night temperatures differ more, and real misregistration can include rotation, which a single shift can't fix. The match thresholds (peak correlation 0.2, 1.25 times the runner-up) were set on synthetic data.
- QGIS 4, the QGIS window (layer loading was checked only through the Processing context), and real Earth Engine.

## Sources

- NASA Earthdata: [ECO_L1B_GEO v002](https://www.earthdata.nasa.gov/data/catalog/lpcloud-eco-l1b-geo-002) (flag names and levels, the 50 m and 7 km figures, OrbitCorrectionPerformed, known issues) and [ECO_L2T_LSTE v002](https://www.earthdata.nasa.gov/data/catalog/lpcloud-eco-l2t-lste-002) (flag not yet in all higher-level products, summary file, FieldOfViewObstruction, noisy period).
- LP DAAC forum: [ECOSTRESS georectification errors](https://forum.earthdata.nasa.gov/viewtopic.php?p=24716) (best under 50 m, suspect 2 to 4 km).
- NASA JPL ECOSTRESS geolocation tutorials: [Python batch guide](https://ecostress.jpl.nasa.gov/downloads/tutorials/ECOSTRESS_Geolocation_Python_Batch_User_Guide_v02.pdf) (shifting LST against a water mask).
- Earth Engine: [NASA/ECOSTRESS/L2T_LSTE/V2](https://developers.google.com/earth-engine/datasets/catalog/NASA_ECOSTRESS_L2T_LSTE_V2).
- Padfield (2012), Masked object registration in the Fourier domain, IEEE TIP.
- ESA WorldCover 2021 v200 (demo landscape).
