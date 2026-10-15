# DIST Watch

**Each run tells you only the vegetation loss that is new since your last run**, from NASA OPERA DIST-ALERT-HLS, with hectares per area. This is option 3 from the shortlist, aimed at deforestation and EUDR checks in the West African cocoa belt (Ghana, Côte d'Ivoire), but it works anywhere DIST-ALERT covers.

DIST-ALERT is a near-global 30 m vegetation-disturbance alert built from Landsat + Sentinel-2 (HLS) and updated every 2 to 4 days. Each granule is cumulative: it holds every disturbance found so far. That makes it awkward to answer the question a supply-chain or forest team actually asks: *what changed in my areas since I last looked?* DIST Watch keeps a small state folder that records which pixels it has already reported, so each run returns only what is new.

It comes in three forms:

| Form | File | Data | Status |
|---|---|---|---|
| Python package and command line | `distwatch/` | Real DIST-ALERT GeoTIFFs (downloads them with an Earthdata login) | Tested on synthetic stand-in data |
| QGIS Processing script | `qgis/distwatch_processing.py` | The same, using only GDAL/numpy shipped with QGIS | **Not run in QGIS** |
| Google Earth Engine script | `gee/distwatch_gee.js` | An HLS-based **approximation** of DIST-ALERT, because Earth Engine doesn't carry DIST-ALERT | **Not run in Earth Engine** |

## What a run does

1. Picks the newest DIST-ALERT granule for each MGRS tile that touches your areas.
2. Keeps pixels that pass your rules. The defaults are set for EUDR checks: **confirmed** alerts, **at least 50%** vegetation cover lost (`VEG-ANOM-MAX`), first detected **after 2020-12-31** (the EUDR cutoff, and also the zero point of DIST's date layers), in patches of **3+ pixels** (0.27 ha). An optional forest mask, such as JRC GFC2020, keeps only loss of forest.
3. Removes pixels reported on an earlier run, so what remains is new. A pixel that was provisional at the last run and is confirmed now counts as new now, which a simple date filter would miss.
4. Groups new pixels into patches, and totals them per area.
5. Records this run's pixels in the state folder (unless you pass `--dry-run`).

MGRS tiles overlap by about 10 km, so the same clearing can appear in two tiles. Each location is counted once, for the tile whose centre is nearest.

## Outputs (one folder per run)

| File | Contents |
|---|---|
| `summary.md` | Readable summary: new hectares and patches per area, tiles used, rule changes |
| `area_summary.csv` | Per area: area, new loss (ha, % of area, patches, mean loss %, first and last detection date), total loss since the cutoff, `NEW LOSS` flag, whether any tile covers it |
| `new_loss.geojson` | One polygon per new patch: hectares, detection dates, mean and max loss %, number of anomalous observations, centroid, which areas it touches, tile, granule, run number |
| `new_loss_<tile>.tif` | Map per tile: 1 = new this run, 2 = reported earlier, 3 = loss in patches below the size limit, 255 = no data |
| `tiles.csv` | Per tile: granule, date, whether it is the same granule as last run, hectares new, earlier, below size, withdrawn. These are per tile, before the overlap rule, so they can add up to more than the run total. |
| `quicklook.png` | Map of the run (when matplotlib is installed) |
| `run.json` | Everything above plus the rules, for audit |

The state folder holds `state.json` (run history, granules used and rules) and one compressed `<tile>.npz` per tile, which records the run at which each pixel was first reported. If you change the rules between runs, the run warns you that some "new" loss may come from the rule change.

## Command line

```bash
pip install -r requirements.txt

# First time: download the newest granule per tile and report everything since the cutoff.
python -m distwatch run --areas farms.geojson --state state/ --fetch --out runs/2026-10-15

# Later: same command, new --out. Only loss added since the last run is reported.
python -m distwatch run --areas farms.geojson --state state/ --fetch --out runs/2026-11-01

# Useful options
--forest-mask gfc2020.tif     # only loss of forest (any raster, non-zero = forest; reprojected on the fly)
--level provisional           # earlier, less certain alerts (or 'first' for every first detection)
--min-loss 30                 # include partial loss / degradation
--data folder/                # use granules you already downloaded
--as-of 2025-02-15            # ignore granules after a date, to replay history
--dry-run                     # write outputs without updating the state

python -m distwatch fetch --areas farms.geojson --dest granules/ --list   # see what's available
python -m distwatch status --state state/                                # run history
python -m distwatch codes                                                # status codes and levels
```

Downloads need a free [NASA Earthdata](https://urs.earthdata.nasa.gov/) login, in `~/.netrc` (`machine urs.earthdata.nasa.gov login USER password PASS`) or as a token in `EARTHDATA_TOKEN`. Areas are GeoJSON polygons in lon/lat; the name comes from a `name` property unless you pass `--name-field`.

To try it on real data, run `demo/fetch_real_dist.sh` on your own computer. It watches two boxes in the cocoa belt (Sefwi Wiawso in Ghana and Soubré in Côte d'Ivoire, in `demo/real_areas_cocoa_belt.geojson`).

## QGIS

Processing Toolbox > Scripts > Add Script to Toolbox… and pick `qgis/distwatch_processing.py`. The script finds the package in the folder above itself, or through the `DISTWATCH_PATH` environment variable. Inputs: an areas layer in any CRS, a name field, a state folder, an optional granules folder, a Download checkbox, and the same rules as the command line. When the run finishes, it loads the new-loss patches and the per-area table into the project. It reads and writes through `distwatch/gdal_io.py`, because QGIS ships GDAL but not rasterio.

## Google Earth Engine

Earth Engine has HLS but not DIST-ALERT, so `gee/distwatch_gee.js` builds a simpler alert from HLS. For each pixel it compares NDVI with a baseline: the median of the same season over the previous 3 years. A view counts as anomalous when NDVI has fallen by `MIN_LOSS`% or more, and a pixel is confirmed after 2 anomalous clear views. By default it keeps only JRC GFC2020 forest. The "since last run" part works through a state image exported to your assets: set `PREVIOUS_STATE` to the last run's asset and move `END_DATE` forward. It exports the per-area CSV, the new-patch GeoJSON and the new state. **It is an approximation, not DIST-ALERT**: DIST uses vegetation cover fraction, per-date baselines and a more careful confirmation logic. `gee/test_gee_mock.js` checks only that the script runs end to end against a fake `ee`.

## Demo (synthetic data)

NASA's servers (CMR and LP DAAC) can't be reached from the sandbox where this was built, so the demo uses a **synthetic stand-in** made by `demo/make_demo_data.py`. The files use DIST-ALERT's real names, layers, status codes and date numbering, on two overlapping 12 km tile subsets near Sefwi Wiawso, Ghana (named after MGRS 30NWM and 30NXM). The demo has three monthly granules per tile, a lon/lat forest mask and six watch areas. Every clearing in it is invented.

`demo/run_demo.sh` replays three runs a month apart. Outputs are in `demo/output/`.

| Run (as of) | New loss | Patches | What the demo is built to show |
|---|---:|---:|---|
| 1 (2025-01-15) | 39.7 ha | 3 | First run reports every clearing since the cutoff; a <50% degradation patch and one-pixel speckle are left out |
| 2 (2025-02-15) | 40.1 ha | 4 | Three new clearings, plus one that was provisional at run 1 and is confirmed now. The clearing in the tile overlap is counted once. |
| 3 (2025-03-15) | 21.3 ha | 4 | Growth at the edge of a run-2 clearing counts only the added pixels; a still-provisional alert waits |
| same as run 2, run again | 0 ha | 0 | Same granules give nothing new (checked in the tests) |

With the forest mask the runs report 12.7, 34.5 and 21.2 ha (`demo/output/forest_run_*`).

## Tests

```bash
python -m pytest tests      # 9 tests: codes, rules, diff, patches, overlap rule, file names, 3-run demo end to end
node gee/test_gee_mock.js   # GEE script control flow against a fake ee
```

## What is untested, and what to check

- **No real DIST-ALERT file has been read.** Before trusting the numbers, check the status codes in `distwatch/products.py` against the current DIST-ALERT product specification. The tool assumes v1 codes: 0 none; 1, 2, 3 = first, provisional, confirmed with <50% loss; 4, 5, 6 = the same with ≥50% loss; 7, 8 = finished; 255 = no data. If a new product version renumbers them, change `STATUS` and `LEVELS` there. Also check the file-name pattern and the nodata values of the date layers.
- **Searching and downloading** (`distwatch/fetch.py`, NASA CMR plus Earthdata login) has never reached the live service.
- **The QGIS script and `gdal_io.py`** have never run: no QGIS or GDAL bindings were available.
- **The Earth Engine script** has never run in Earth Engine. The `JRC/GFC2020/V2` collection ID and the HLS band choices should be checked in the catalog.
- Areas are rasterised on the 30 m grid (pixel centres inside the polygon), so very small plots under about 1 ha have coarse totals.
- The run reads only the newest granule per tile. If a pixel's alert appears and is dropped between two runs, DIST Watch never sees it.

## Files

```
distwatch/products.py   collection, file names, layers, status codes, dates
distwatch/core.py       rules, diff against state, patches, overlap rule, per-area rows (numpy only)
distwatch/watch.py      one run end to end; outputs
distwatch/state.py      the state folder
distwatch/catalog.py    newest local granule per tile
distwatch/fetch.py      NASA CMR search and Earthdata download
distwatch/rio_io.py     rasterio/shapely/pyproj I/O (command line)
distwatch/gdal_io.py    the same with GDAL only (QGIS)
distwatch/quicklook.py  PNG map
qgis/                   Processing script
gee/                    Earth Engine script and its mock test
demo/                   synthetic data, scripts, outputs, real-data script
tests/                  pytest suite
```

## Possible next steps

- A scheduled run (cron or GitHub Action) that emails or posts `summary.md` when `NEW LOSS` appears.
- Read OPERA DIST-ANN (annual) to label reported patches as lasting loss once the year closes.
- Add OPERA DIST-S1 (radar) alerts, which see through cloud, for the West African rainy season.
