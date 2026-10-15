# Remote Sensing Portfolio

Small, open tools for working with satellite data, focused on Africa and on NASA products (HLS, OPERA, ECOSTRESS, NISAR).

Each tool lives in its own folder with the same shape:

- a Python core and command-line tool,
- a QGIS Processing script or plugin,
- a Google Earth Engine (JavaScript) version where it fits,
- a small African demo you can rerun, and
- a README that says plainly what has and has not been tested.

## Tools

| Folder | What it does |
|---|---|
| [`classspectra/`](classspectra/) | Spectral signatures and class separability for any land-cover map over any image |
| [`compositecheck/`](compositecheck/) | Quality check for multi-date composites: per-pixel provenance, scene dominance, outlier scenes, Landsat vs Sentinel-2 consistency |
| [`distwatch/`](distwatch/) | Watches areas for new OPERA DIST-ALERT vegetation loss and reports only what is new since the last run |
| [`qamaskbuilder/`](qamaskbuilder/) | Builds cloud and quality masks from HLS, Landsat, MODIS, ECOSTRESS and OPERA QA layers, and fixes the HLS southern-hemisphere CRS bug |

Tools are added one pull request at a time, so a folder appears here once its PR is merged.

## Large demo data

Rasters over a few MB are not committed. Each tool's `demo/run_demo.sh` (or `demo/make_demo_data.py`) downloads or rebuilds them from free public sources.
