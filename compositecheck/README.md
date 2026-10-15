# Composite Check

Quality layers and a one-page report for a pixel-based composite built from Landsat, Sentinel-2 or NASA HLS scenes. This is option 8 from the shortlist. It comes in three forms that share one design:

- a **Python package and command line** (`compositecheck/`);
- a **QGIS Processing script** (`qgis/compositecheck_processing.py`) that runs the same code using only what QGIS ships with;
- a **Google Earth Engine script** in JavaScript (`gee/composite_check.js`) that runs on NASA HLS in the GEE catalog.

It answers one question: **can I trust this composite, pixel by pixel?** It does that with four groups of checks.

| Check | What it reports | Where it comes from |
|---|---|---|
| Observations | Clear observations per pixel, and the longest stretch with no clear view | Francini et al. 2023, criterion 1; FORCE INF "NUM" |
| Dates | Date of each pixel's source observation, days from the target date, and the spread of those dates | Francini criteria 4 and 5; FORCE INF "DOY/DOYD" |
| **Scene dominance** (new) | Which scene each pixel came from, each scene's share of the composite, an "effective number of scenes" (inverse Herfindahl index), and a flag when one scene supplies over 50% | No published equivalent found |
| **Outlier screen** (new) | Per scene: the share of its "clear" pixels that are robust outliers against their own time series in the visible bands, and its median blue z-score. Flags scenes with likely missed cloud or haze, and composite pixels whose source is an outlier | No published equivalent found |
| **Landsat vs Sentinel-2** (new) | Near-same-day Landsat/Sentinel-2 pairs compared over shared clear pixels, against the HLS v2.0 envelope (under 4.2% for red, NIR, SWIR1, SWIR2; Ju et al. 2025). Also gain and offset, a Landsat-only vs Sentinel-2-only composite comparison, and the sensor of each composite pixel | Ju et al. 2025, RSE 324:114723 |

It **operationalises and extends** criteria 1, 4 and 5 of Francini et al. 2023 (ISPRS J. 202:1–12), which released no code. It does not implement that paper. Criteria 2 (residual noise) and 3 (radiometric distance to a reference) need multi-year stacks or clear reference scenes, so they are not included. Scene dominance and the outlier screen are new diagnostics, and nobody has validated them yet. The demo below is a first check: the screen's top-flagged scene really is hazy.

## Quick start

```sh
pip install -r requirements.txt          # numpy, rasterio, matplotlib
# a folder of HLS v2.0 granules (B02..., Fmask) as downloaded from LP DAAC / earthaccess
python -m compositecheck path/to/hls_folder --start 2024-01-01 --end 2024-06-30 --target 2024-03-31 \
    --bbox 36.00 -0.40 36.12 -0.28 --out out/
# or a manifest CSV: path,fmask,date,sensor,scene_id  (one 6-band file per scene: blue,green,red,nir,swir1,swir2)
python -m compositecheck scenes.csv --start ... --end ... --method target --dilate 1 --out out/
# assess an existing composite (e.g. a DE Africa GeoMAD) against the scenes it was built from
python -m compositecheck scenes.csv --start ... --end ... --sensors S --composite geomad.tif --composite-bands 1,2,3,4,5,6 --out out/
```

Composite methods: `medoid` (the clear observation closest to the per-band median; the default), `median` (per-band median; the source scene is then a proxy, the spectrally closest observation), and `target` (the clear observation closest to the target date, a minimal best-available-pixel rule). An existing composite always uses the proxy. That is how median-type products such as GeoMAD get a "source scene" at all.

**Outputs** in `--out`:

| File | Content |
|---|---|
| `qa_layers.tif` | One band per layer: NCLEAR, MAX_GAP, SRC_SCENE, SRC_DOY, DOYD, SRC_SENSOR, LANDSAT_SHARE, SRC_SCENE_SHARE, SRC_OUTLIER, LS_REL_DIFF, AEROSOL_HIGH_SHARE. Descriptions are in `report.json`. |
| `composite.tif` | The composite it built (not written when assessing an existing one) |
| `scenes.csv` | Per scene: date, sensor, data and clear share, share of the composite, outlier share, median blue z, suspect flag |
| `pairs.csv` | Per Landsat/Sentinel-2 pair: days apart, shared clear pixels, clean flag, per-band difference, bias, gain, offset |
| `report.json` | Every number, plus plain-language findings |
| `report.png` | The one-page report |

The cloud mask uses HLS Fmask bits. The default rejects bits 0–3 (cirrus, cloud, adjacent, shadow). Add `--fmask-bits 0,1,2,3,4` to drop snow. `--dilate 1` grows the mask one pixel.

## Real HLS, by area

`compositecheck.fetch` searches NASA's catalog with `earthaccess`, keeps one MGRS tile, and reads only your area from each band of each granule, so a small area costs megabytes, not gigabytes. It needs a free [NASA Earthdata login](https://urs.earthdata.nasa.gov); the first run asks for it and saves it to `~/.netrc`.

```sh
pip install earthaccess
python -m compositecheck.fetch --bbox 36.00 -0.40 36.12 -0.28 --start 2024-01-01 --end 2024-06-30 --out hls/
python -m compositecheck hls/ --bbox 36.00 -0.40 36.12 -0.28 --start 2024-01-01 --end 2024-06-30 --out out/
```

`demo/run_real_hls.sh` does this for the Nakuru demo and runs the medoid and closest-date checks. It has only been tested offline (`tests/test_fetch.py`), because NASA's servers are blocked from the build sandbox.

## In QGIS

Go to Processing Toolbox › Scripts › *Add Script to Toolbox…* and pick `qgis/compositecheck_processing.py`. It appears under **Map QA › Composite quality check (Composite Check)**, next to ClassSpectra. It finds the `compositecheck` package in the folder above the script, or in `COMPOSITECHECK_PATH`. It reads and writes with GDAL and numpy, both of which ship with QGIS. If matplotlib is present it also draws the chart. The QA layers and composite load into the map when it finishes. Both the QGIS 3.34+ and QGIS 4 parameter enums are handled.

## In Google Earth Engine

Paste `gee/composite_check.js` into the Code Editor. Set the area, dates, target and method at the top, then run. It reads `NASA/HLS/HLSL30/v002` and `NASA/HLS/HLSS30/v002`. It prints a summary, the scene table and the pair table, and draws the contribution chart and map layers. Export tasks for the QA layers, the composite and both tables appear in the Tasks tab. It mirrors the Python logic with one difference: it reports the source date as days since the period start, not DOY.

## Demo: Nakuru, Kenya, January–June 2024

The demo area is 13 × 13 km around Nakuru town, its farmland and the north shore of Lake Nakuru. The period is the first half of 2024, which matches DE Africa's semiannual GeoMAD. Run `demo/run_demo.sh` to reproduce it. The 95 scenes and the GeoMAD tile (about 120 MB) are not in git; `run_demo.sh` downloads them with `demo/make_demo_data.py` on first run. All the data is free and needs no login:

- **72 Sentinel-2 L2A scenes**, tile 36MZE, from the AWS `sentinel-cogs` bucket;
- **23 Landsat 8/9 Collection 2 L2 scenes**, path/row 169/060, from DE Africa's `deafrica-landsat` bucket;
- the **DE Africa Sentinel-2 GeoMAD** for H1 2024, tile x217y076.

NASA's HLS servers were blocked from the build sandbox. So `demo/make_demo_data.py` builds an **HLS-like** stack instead. It puts both sensors on one 30 m UTM grid, bandpass-adjusts Sentinel-2 to Landsat with the HLS v2.0 coefficients, and recodes the cloud masks to Fmask bits. It does *not* reproduce the HLS atmospheric correction or BRDF normalisation. That gap matters for the sensor check, as the results show.

| Run | Output |
|---|---|
| Medoid of all 95 scenes | `demo/output_medoid/` |
| Closest clear date to 31 March | `demo/output_target/` (also `suspect_scene.png`) |
| GeoMAD assessed against its Sentinel-2 scenes | `demo/output_geomad/` (also `count_vs_geomad.json`) |

What it found:

- **A date-based composite was dominated by a hazy scene that the cloud mask missed.** With the closest-date rule, one scene (Sentinel-2B, 31 March) supplied **78%** of the composite, so it behaved like 1.6 scenes. The outlier screen flagged that scene independently: 29% of its "clear" pixels were outliers and its median blue z was 2.2. Then **24%** of composite pixels were outliers against their own time series. `suspect_scene.png` shows why: the SCL mask passed thin cloud and haze over the lake and left cloud shadows in. This is the "one bad scene skews the composite" case the tool was built for.
- **The medoid composite of the same scenes is healthy.** It draws on 78 scenes and behaves like 15.7 equal scenes; the largest supplies 17%. Its median is 44 clear observations per pixel, and the median longest gap is 13 days.
- **The clear-observation count matches DE Africa's own.** Over GeoMAD's tile, our Sentinel-2 count and GeoMAD's COUNT band have the same median (27 vs 28), a median difference of 0 and a correlation of 0.997. That is independent evidence the count layer is right.
- **Mixing non-HLS Landsat and Sentinel-2 is far outside the HLS envelope.** There were 6 clean same-day or next-day pairs (at least 50% shared clear area). None fell inside 4.2%. The median differences were red 12.9%, NIR 5.0%, SWIR1 7.4% and SWIR2 10.9%. A fit on the best pair (1 March 2024) gives Sentinel-2 ≈ 0.95 × Landsat + 0.010 in red. That shape points to an additive offset, which fits the two different atmospheric corrections (ESA Sen2Cor vs USGS LaSRC). This is inferred, not tested. Half of the medoid composite's pixels came from Landsat, so that offset turns into a patchwork. The fix is real HLS, or not mixing sensors.
- **The outlier screen has false positives worth knowing about.** It flags scenes that are mostly cloud: their few "clear" pixels sit on cloud edges. That is arguably the right call. But it would also flag a real, sudden change, such as a flood or a harvest. This is one more reason the dominance and outlier metrics need validation before anyone cites them.

## Tests and what wasn't tested

- `tests/test_core.py`: 9 synthetic tests covering mask bits, counts and gaps, date selection, dominance, the outlier screen catching injected haze, the medoid avoiding it, the pair envelope, an end-to-end run, and the HLS file-name parser. All pass.
- `tests/qgis_smoke.py`: runs the QGIS script outside QGIS with stubbed `qgis` modules, under a Python that has GDAL 3.8 bindings but no rasterio or matplotlib, which is roughly what QGIS 3.34 has. Its QA layers and composite are **identical** to the command line's. It has **not been loaded inside a real QGIS 3.x or 4.x install**.
- `tests/gee_dryrun.js`: runs the Earth Engine script under Node with a stand-in `ee` object. That catches JavaScript errors, but **not Earth Engine semantics**. The script has **never run in Earth Engine**: there was no access from the sandbox. Expect small API fixes on the first run.
- The HLS folder reader is tested only on file names. **It has not read real HLS granules**, because LP DAAC was unreachable.

## Layout

```
compositecheck/core.py      numpy maths: all checks, no I/O
compositecheck/catalog.py   manifest and HLS file discovery, stack assembly
compositecheck/io.py        rasterio reading/writing (command line)
compositecheck/gdal_io.py   the same with GDAL only (QGIS; command-line fallback)
compositecheck/report.py    CSV/JSON, findings, one-page chart
compositecheck/sensors.py   band names, HLS bandpass coefficients, layer docs
compositecheck/cli.py       command line
qgis/                       Processing script
gee/                        Earth Engine script
tests/                      synthetic tests, QGIS smoke test, GEE dry run
demo/                       data download, runner, outputs
```

## Not done yet

- A real-HLS run, a real-QGIS run and a real-GEE run.
- Validating dominance and the outlier screen, for example against Francini's count-noise correlation or labelled haze scenes.
- Francini criteria 2 and 3.
- Reading GeoMAD and other DE Africa products straight from STAC. (Searching HLS by area is now `compositecheck.fetch`, untested against the live service.)
- Packaging the QGIS script and ClassSpectra as one "Map QA" plugin.
