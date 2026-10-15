"""File-to-file runs shared by the command line (rasterio) and QGIS (GDAL). `io` is
droughtcheck.rio or droughtcheck.gdal_io."""
from __future__ import annotations

import os
import sys

import numpy as np

from . import drought as D
from . import greenness as G
from . import report as R


def load_legend(name):
    """Land cover legends come from ClassSpectra when it sits next to this tool."""
    if name in (None, "none"):
        return {}
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.path.insert(0, os.path.join(here, "classspectra"))
    try:
        from classspectra.legends import LEGENDS
        return LEGENDS[name]
    except Exception:
        from ._legends import LEGENDS
        return LEGENDS[name]
    finally:
        sys.path.pop(0)


def align(io, stack, labels, months):
    """Put a labelled monthly stack on a list of target months (NaN where missing)."""
    pos = {"%04d-%02d" % io.month_of(l): i for i, l in enumerate(labels) if io.month_of(l)}
    out = np.full((len(months),) + stack.shape[1:], np.nan)
    for t, m in enumerate(months):
        if m in pos:
            out[t] = stack[pos[m]]
    return out


def drought_files(io, precip, out, temps=None, pet=None, log=print, **opts):
    P, prof, labels = io.read_stack(precip)
    y0, m0 = io.month_of(labels[0])
    months = D.month_labels(y0, m0, P.shape[0])
    if ["%04d-%02d" % io.month_of(l) for l in labels] != months:
        P = align(io, P, labels, months)
    kw = {}
    if temps:
        Tx, tprof, tl = io.read_stack(temps, "tmax")
        Tn, _, nl = io.read_stack(temps, "tmin")
        kw["tmax"] = io.regrid(align(io, Tx, tl, months), tprof, prof)
        kw["tmin"] = io.regrid(align(io, Tn, nl, months), tprof, prof)
        kw["lat"] = io.pixel_latitudes(prof)
    elif pet:
        E, eprof, el = io.read_stack(pet)
        kw["pet"] = io.regrid(align(io, E, el, months), eprof, prof)
    log(f"{P.shape[0]} months ({months[0]} to {months[-1]}), {P.shape[1]} x {P.shape[2]} pixels")
    res = D.run(P, y0, m0, **opts, **kw)
    f = D.findings(res)
    R.write_drought_outputs(out, res, f, prof, lambda p, arr, labs: io.write_stack(p, arr, prof, labs))
    for line in f:
        log(line)
    return res, f


def greenness_files(io, ndvi, drought_dir, landcover, out, clear=None, min_clear=1, legend="worldcover",
                    scales=(1, 3, 6), log=print, **opts):
    N, nprof, nl = io.read_stack(ndvi)
    months = ["%04d-%02d" % io.month_of(l) for l in nl]
    spi = {}
    for s in scales:
        path = os.path.join(drought_dir, f"spi_{s}.tif")
        if os.path.exists(path):
            Z, zprof, zl = io.read_stack(path)
            spi[s] = io.regrid(align(io, Z, zl, months), zprof, nprof)
    if not spi:
        raise ValueError(f"no spi_*.tif in {drought_dir}; run the drought step first")
    L, lprof, _ = io.read_stack(landcover)
    lc = L[0]
    if (lprof["width"], lprof["height"]) != (nprof["width"], nprof["height"]) or lprof["transform"] != nprof["transform"]:
        lc = io.regrid(L[:1], lprof, nprof, "mode")[0]
    lc = np.nan_to_num(lc).astype(int)
    if clear:
        C, _, cl = io.read_stack(clear)
        N[align(io, C, cl, months) < min_clear] = np.nan
    log(f"{len(months)} NDVI months ({months[0]} to {months[-1]}), SPI scales {sorted(spi)}")
    res = G.run(N, months, spi, lc, load_legend(legend), **opts)
    f = G.findings(res)
    R.write_greenness_outputs(out, res, f, lambda p, arr, labs: io.write_stack(p, arr, nprof, labs))
    for line in f:
        log(line)
    return res, f
