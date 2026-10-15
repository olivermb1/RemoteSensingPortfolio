"""Finding scenes and assembling a Stack, independent of the raster library.

io.py (rasterio) and gdal_io.py (GDAL, used inside QGIS) each supply a
`read(path, band, dtype, fill)` function that returns one band on the
target grid; everything else is shared.
"""

import csv
import datetime as dt
import glob
import os
import re
from collections import defaultdict

import numpy as np

from . import core
from .sensors import COMMON_BANDS, HLS_BANDS

HLS_RE = re.compile(r"HLS\.(?P<prod>[LS]30)\.(?P<tile>T\w{5})\.(?P<y>\d{4})(?P<doy>\d{3})T(?P<time>\d{6})"
                    r"\.v(?P<ver>[\d.]+)\.(?P<band>\w+)\.tif$")


def manifest_scenes(path):
    """Scenes from a CSV with columns path, date, sensor and optionally fmask, scene_id.

    Each path is one multiband file with bands in COMMON_BANDS order
    (blue, green, red, nir, swir1, swir2). Relative paths are relative to the CSV.
    """
    base = os.path.dirname(os.path.abspath(path))
    rel = lambda p: p if os.path.isabs(p) else os.path.join(base, p)  # noqa: E731
    scenes = []
    with open(path, newline="") as fh:
        for r in csv.DictReader(fh):
            p = rel(r["path"])
            scenes.append({
                "bands": [(p, i + 1) for i in range(len(COMMON_BANDS))],
                "fmask": rel(r["fmask"]) if r.get("fmask") else None,
                "date": np.datetime64(r["date"], "D"), "sensor": r["sensor"],
                "id": r.get("scene_id") or os.path.splitext(os.path.basename(p))[0],
            })
    return scenes


def hls_scenes(folder):
    """Scenes from a folder (searched recursively) of NASA HLS v2.0 band files,
    e.g. HLS.S30.T36MZE.2024092T075619.v2.0.B04.tif plus its .Fmask.tif."""
    gran = defaultdict(dict)
    for p in glob.glob(os.path.join(folder, "**", "HLS.*.tif"), recursive=True):
        m = HLS_RE.search(os.path.basename(p))
        if m:
            gid = os.path.basename(p)[: m.start("band") - 1]
            gran[gid]["_m"] = m.groupdict()
            gran[gid][m["band"]] = p
    scenes = []
    for gid, files in gran.items():
        m = files["_m"]
        need = HLS_BANDS[m["prod"]]
        if not all(b in files for b in need):
            continue
        date = np.datetime64(dt.date(int(m["y"]), 1, 1) + dt.timedelta(int(m["doy"]) - 1), "D")
        scenes.append({"bands": [(files[b], 1) for b in need], "fmask": files.get("Fmask"),
                       "date": date, "sensor": m["prod"], "id": gid})
    if not scenes:
        raise ValueError(f"no complete HLS v2.0 granules found in {folder}")
    return scenes


def find_scenes(stack_path):
    """A manifest CSV or an HLS folder; returns (scenes, scale, nodata)."""
    if os.path.isdir(stack_path):
        return hls_scenes(stack_path), 1e-4, -9999
    return manifest_scenes(stack_path), 1e-4, -9999


def filter_scenes(scenes, start=None, end=None, sensors=None):
    """Keep scenes in [start, end] whose sensor label starts with one of `sensors`
    (e.g. ["S"] for Sentinel-2 only, ["L"] for Landsat only)."""
    if sensors:
        pre = tuple(x.strip().upper() for x in sensors if x.strip())
        scenes = [s for s in scenes if s["sensor"].upper().startswith(pre)]
    if start:
        scenes = [s for s in scenes if s["date"] >= np.datetime64(start, "D")]
    if end:
        scenes = [s for s in scenes if s["date"] <= np.datetime64(end, "D")]
    scenes = sorted(scenes, key=lambda s: (s["date"], s["id"]))
    if not scenes:
        raise ValueError("no scenes left after filtering by date and sensor")
    return scenes


def assemble(scenes, read, shape, fmask_bits=(0, 1, 2, 3), dilate=0, scale=1e-4, nodata=-9999,
             meta=None, progress=None):
    """Read every scene onto the grid and build a core.Stack.

    read(path, band, dtype, fill) -> 2-D array of `shape` on the target grid.
    progress(fraction) is called after each scene, if given.
    """
    T, B = len(scenes), len(COMMON_BANDS)
    h, w = shape
    refl = np.full((T, B, h, w), nodata, "int16")
    clear = np.zeros((T, h, w), bool)
    aer = np.zeros_like(clear)
    any_aer = False
    for t, s in enumerate(scenes):
        for b, (path, band) in enumerate(s["bands"]):
            refl[t, b] = read(path, band, "int16", nodata)
        has = np.all(refl[t] != nodata, axis=0)
        if s.get("fmask"):
            fm = read(s["fmask"], 1, "uint8", 255)
            c = core.fmask_clear(fm, fmask_bits)
            if dilate:
                c &= ~core.dilate(~c & (fm != 255), dilate)
            clear[t] = c & has
            aer[t] = core.fmask_aerosol_high(fm)
            any_aer |= bool(((fm != 255) & (((fm >> 6) & 3) > 0)).any())
        else:
            clear[t] = has
        if progress:
            progress((t + 1) / T)
    return core.Stack(
        refl=refl, clear=clear, dates=np.array([s["date"] for s in scenes]),
        sensors=[s["sensor"] for s in scenes], ids=[s["id"] for s in scenes],
        band_names=list(COMMON_BANDS), scale=scale, nodata=nodata,
        aerosol_high=aer if any_aer else None, meta=meta or {},
    )
