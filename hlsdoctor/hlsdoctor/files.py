"""Checks of HLS files already on disk: half-finished downloads, login pages
saved as .tif, retired versions, the southern-hemisphere CRS label, missing
EPSG codes, scale and no-data settings, and folder-level mix-ups."""

import os
import re
import sys
from collections import defaultdict

from .http import is_tiff, looks_html, looks_s3_error
from .report import FAIL, INFO, PASS, WARN, Result

_here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:  # reuse QA Mask Builder's fix when it sits next to this tool
    sys.path.insert(0, os.path.join(_here, "qamaskbuilder"))
    from qamask.crsfix import hls_crs_fix
    CRSFIX_SOURCE = "qamaskbuilder"
except ImportError:
    from ._crsfix_copy import hls_crs_fix
    CRSFIX_SOURCE = "copy"
finally:
    if sys.path and sys.path[0] == os.path.join(_here, "qamaskbuilder"):
        sys.path.pop(0)

HLS_RE = re.compile(r"HLS\.(?P<prod>L30|S30)\.T(?P<tile>\d{2}[A-Z]{3})\.(?P<date>\d{7})T(?P<time>\d{6})"
                    r"\.v(?P<ver>\d+\.\d+)\.(?P<band>[A-Za-z0-9]+)\.tif$", re.I)

# HLS v2.0 band numbers. The same number means different light in L30 and S30.
BANDS = {
    "L30": {"B01": "coastal aerosol", "B02": "blue", "B03": "green", "B04": "red", "B05": "NIR",
            "B06": "SWIR 1", "B07": "SWIR 2", "B09": "cirrus", "B10": "thermal 1", "B11": "thermal 2"},
    "S30": {"B01": "coastal aerosol", "B02": "blue", "B03": "green", "B04": "red", "B05": "red edge 1",
            "B06": "red edge 2", "B07": "red edge 3", "B08": "NIR broad", "B8A": "NIR narrow",
            "B09": "water vapour", "B10": "cirrus", "B11": "SWIR 1", "B12": "SWIR 2"},
}
SAME_LIGHT = [("NIR", "B05", "B8A"), ("SWIR 1", "B06", "B11"), ("SWIR 2", "B07", "B12"), ("cirrus", "B09", "B10")]
ANGLES = {"SZA", "SAA", "VZA", "VAA"}


def _meta(path):
    """File metadata with GDAL or rasterio, or None when neither is installed."""
    try:
        from osgeo import gdal, osr
        gdal.PushErrorHandler("CPLQuietErrorHandler")
        try:
            ds = gdal.Open(path)
            if ds is None:
                raise RuntimeError(gdal.GetLastErrorMsg() or "GDAL could not open the file")
            srs = ds.GetSpatialRef()
            epsg = matched = None
            if srs is not None:
                if srs.GetAuthorityName(None) == "EPSG":
                    epsg = int(srs.GetAuthorityCode(None))
                else:
                    s2 = srs.Clone()
                    if s2.AutoIdentifyEPSG() == 0 and s2.GetAuthorityCode(None):
                        matched = int(s2.GetAuthorityCode(None))
            gt = ds.GetGeoTransform()
            b = ds.GetRasterBand(1)
            return {"epsg": epsg, "epsg_matched": matched, "has_crs": srs is not None,
                    "top": gt[3], "bottom": gt[3] + gt[5] * ds.RasterYSize,
                    "nodata": b.GetNoDataValue(), "scale": b.GetScale(), "offset": b.GetOffset(),
                    "dtype": gdal.GetDataTypeName(b.DataType).lower(), "tags": ds.GetMetadata() or {},
                    "block": tuple(b.GetBlockSize()), "overviews": b.GetOverviewCount(), "count": ds.RasterCount}
        finally:
            gdal.PopErrorHandler()
    except ImportError:
        pass
    try:
        import rasterio
    except ImportError:
        return None
    with rasterio.open(path) as s:
        epsg = matched = None
        if s.crs:
            epsg = s.crs.to_epsg()
            if epsg is None:
                matched = s.crs.to_epsg(confidence_threshold=20)
        by, bx = s.block_shapes[0]
        return {"epsg": epsg, "epsg_matched": matched, "has_crs": s.crs is not None,
                "top": s.bounds.top, "bottom": s.bounds.bottom, "nodata": s.nodata,
                "scale": s.scales[0], "offset": s.offsets[0], "dtype": s.dtypes[0], "tags": s.tags(),
                "block": (bx, by), "overviews": len(s.overviews(1)), "count": s.count}


def check_file(path):
    """A list of findings for one file: (status, text, fix, gotcha)."""
    name = os.path.basename(path)
    f = []
    size = os.path.getsize(path)
    if size == 0:
        return [(FAIL, "the file is empty (0 bytes): the download stopped before any data came",
                 "Download it again.", "html-as-tif")], None
    with open(path, "rb") as fh:
        head = fh.read(1024)
    if looks_html(head):
        return [(FAIL, "this is a web page saved with a .tif name, almost always the Earthdata login page",
                 "Your download didn't send the Earthdata login. Fix ~/.netrc (run the full check) and download again.",
                 "html-as-tif")], None
    if looks_s3_error(head):
        code = re.search(rb"<Code>([^<]+)</Code>", head)
        return [(FAIL, f"this is an S3 error message ({code.group(1).decode() if code else 'unknown'}) saved with a .tif name",
                 "AccessDenied: s3:// links only work inside AWS us-west-2; use the https:// link. "
                 "Expired/RequestExpired: signed links last about an hour; fetch a fresh one.", "s3-region")], None
    if not is_tiff(head):
        return [(FAIL, "not a GeoTIFF (the first bytes are wrong); the file is damaged or something else",
                 "Download it again.", "html-as-tif")], None
    m = HLS_RE.search(name)
    try:
        meta = _meta(path)
    except Exception as e:  # noqa: BLE001
        return [(FAIL, f"starts like a GeoTIFF but can't be read ({str(e)[:120]}); usually a download that stopped part way",
                 "Download it again. Partial files often have the right name but a size much smaller than the others.",
                 "html-as-tif")], m
    if m:
        ver = m["ver"]
        if ver != "2.0":
            f.append((WARN, f"HLS version {ver}; v2.0 is the current release and older versions are retired",
                      "Search for short names HLSL30 / HLSS30 version 2.0.", "versions"))
        band = m["band"].upper()
        prod = m["prod"].upper()
        if band == "FMASK":
            f.append((INFO, "Fmask is a set of bit flags, not classes: value 64 is 'low aerosol, clear', not class 64",
                      "Decode bits with QA Mask Builder: python -m qamask build <this file>", "fmask"))
        elif band in BANDS[prod]:
            f.append((INFO, f"{prod} {band} is {BANDS[prod][band]}", "", "band-numbers"))
    if meta is None:
        f.append((INFO, "GDAL/rasterio not installed, so only the file type and name were checked", "pip install rasterio", ""))
        return f, m
    # CRS
    epsg = meta["epsg"]
    if meta["has_crs"] and epsg is None:
        code = meta["tags"].get("HORIZONTAL_CS_CODE", "")
        guess = meta["epsg_matched"] or (int(code.split(":")[1]) if code.upper().startswith("EPSG:") else None)
        f.append((INFO, "the CRS has no EPSG code attached (HLS files carry an unnamed 'UTM zone N' definition), so "
                  "rasterio's crs.to_epsg() returns None and some tools say 'unknown CRS'"
                  + (f"; it matches EPSG:{guess}" if guess else ""),
                  "In rasterio use crs.to_epsg(confidence_threshold=20); in QGIS set the layer CRS to "
                  + (f"EPSG:{guess}" if guess else "the UTM zone in the file name") + ".", "no-epsg"))
        epsg = guess
    elif not meta["has_crs"]:
        f.append((FAIL, "no CRS at all", "Set the UTM zone from the tile name (first two digits).", "no-epsg"))
    if epsg:
        fix = hls_crs_fix(epsg, meta["top"], meta["bottom"], name)
        if fix["needed"]:
            f.append((WARN, f"southern-hemisphere CRS label: {fix['reason']}",
                      "Relabel without resampling: python -m qamask fix-crs <file> --vrt (QA Mask Builder), "
                      "or leave it if you only work in this one file's CRS.", "southern-epsg"))
    # Scale and no-data
    band = m["band"].upper() if m else None
    if m and band != "FMASK" and band not in ANGLES:
        sf = meta["tags"].get("scale_factor")
        if meta["dtype"] == "int16":
            if meta["scale"] in (None, 1.0) and not sf:
                f.append((WARN, "no scale factor stored; HLS reflectance is stored x10000",
                          "Multiply by 0.0001 to get reflectance (thermal bands: check the product guide).", "scale"))
            else:
                s = sf or meta["scale"]
                f.append((INFO, f"stored as int16 with scale {s}: divide by {1 / float(s):g} for reflectance. HLS has no "
                          "offset, so the Sentinel-2 L2A '-1000' fix does not apply", "", "scale"))
        elif meta["dtype"].startswith("float"):
            f.append((INFO, "stored as floating point, so it was converted after download; check it was scaled exactly once",
                      "", "scale"))
        if meta["nodata"] is None:
            f.append((WARN, "no no-data value set; HLS fill pixels (-9999) will count as data",
                      "Set no-data to -9999 (QGIS: Layer Properties > Transparency; GDAL: gdal_edit -a_nodata -9999).", "nodata"))
    if m and band == "FMASK" and meta["nodata"] is None:
        f.append((WARN, "no no-data value set on Fmask; fill is 255", "Set no-data to 255.", "nodata"))
    if meta["block"][1] == 1 or meta["overviews"] == 0:
        f.append((INFO, "not tiled or no overviews, so this is a re-saved copy, not NASA's original cloud-optimised file "
                  "(fine on disk, slow if served over the web)", "", ""))
    return f, m


def check_paths(paths, verbose=False):
    files = []
    for p in paths:
        if os.path.isdir(p):
            for root, _, names in os.walk(p):
                files += [os.path.join(root, n) for n in sorted(names) if n.lower().endswith((".tif", ".tiff"))]
        elif os.path.isfile(p):
            files.append(p)
        else:
            files.append(p)
    out, granules, clean, no_epsg = [], defaultdict(dict), 0, []
    for path in files:
        if not os.path.isfile(path):
            out.append(Result("file", os.path.basename(path), FAIL, f"{path} does not exist."))
            continue
        findings, m = check_file(path)
        if m:
            gid = f"{m['prod'].upper()}.T{m['tile'].upper()}.{m['date']}T{m['time']}"
            granules[gid][m["band"].upper()] = path
        if any(g == "no-epsg" and st == INFO for st, _, _, g in findings):
            no_epsg.append(os.path.basename(path))
        worst = FAIL if any(s == FAIL for s, *_ in findings) else WARN if any(s == WARN for s, *_ in findings) else PASS
        shown = [x for x in findings if verbose or x[0] in (FAIL, WARN)]
        if worst == PASS and not verbose:
            clean += 1
            continue
        detail = "\n".join(f"- {t}" for _, t, _, _ in shown)
        fixes = [fx for s, _, fx, _ in shown if fx and s in (FAIL, WARN)]
        gotcha = next((g for s, _, _, g in shown if g and s in (FAIL, WARN)), "")
        out.append(Result("file", os.path.basename(path), worst if shown else PASS, detail,
                          " ".join(dict.fromkeys(fixes)), gotcha, {"path": path}))
    if clean:
        out.insert(0, Result("files", f"{clean} file(s) with nothing to fix", PASS, ""))
    if no_epsg:
        out.append(Result("epsg", "EPSG code on the CRS", WARN,
                          f"{len(no_epsg)} file(s) (e.g. {no_epsg[0]}) store an unnamed 'UTM zone N' CRS with no EPSG "
                          "code. The CRS is right, but rasterio's crs.to_epsg() returns None and some tools report "
                          "'unknown CRS' or treat same-zone tiles as different.",
                          "rasterio: crs.to_epsg(confidence_threshold=20); GDAL: AutoIdentifyEPSG(); QGIS: set the "
                          "layer CRS to EPSG:326 + the zone in the tile name (327 + zone south of the equator, after "
                          "the CRS fix).", "no-epsg"))
    out += folder_checks(granules)
    if not files:
        out.append(Result("files", "HLS files", WARN, "No .tif files found at the given path(s)."))
    return out


def folder_checks(granules):
    out = []
    if not granules:
        return out
    prods = {g.split(".")[0] for g in granules}
    if prods == {"L30", "S30"}:
        rows = "; ".join(f"{n}: L30 {a} = S30 {b}" for n, a, b in SAME_LIGHT)
        out.append(Result("bands", "Landsat (L30) and Sentinel-2 (S30) files together", INFO,
                          "The same band number means different light in the two products: " + rows +
                          ". S30 B05 is red edge, not NIR. Pick bands by name, not number.", gotcha="band-numbers"))
    by_date = defaultdict(set)
    for g in granules:
        prod, tile, when = g.split(".")
        by_date[(prod, when[:7])].add(tile)
    dup = {k: v for k, v in by_date.items() if len(v) > 1}
    if dup:
        (prod, day), tiles = next(iter(dup.items()))
        out.append(Result("tiles", "Neighbouring MGRS tiles", WARN,
                          f"{len(dup)} date(s) appear on more than one tile (e.g. {prod} {day} on {', '.join(sorted(tiles))}). "
                          "Tiles overlap by several kilometres, so a time series or composite over the overlap counts "
                          "the same observation twice.", "Keep one tile per area (most tools have a --tile option).", "tiles"))
    nomask = [g for g, b in granules.items() if "FMASK" not in b and len(b) > 0]
    if nomask:
        out.append(Result("fmask", "Fmask alongside the bands", WARN,
                          f"{len(nomask)} granule(s) have bands but no Fmask file (e.g. {nomask[0]}).",
                          "Download the .Fmask.tif too; without it clouds can't be masked.", "fmask"))
    return out
