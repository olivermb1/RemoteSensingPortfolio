"""Read a GUNW file and write GeoTIFFs. I/O goes through a `backend` object
(rio_io for the command line, gdal_io for QGIS) so this module needs only numpy.
"""

import json
import os
import re

import numpy as np

from . import __version__
from . import core, product as P
from .readers import open_reader


class GunwProduct:
    def __init__(self, path, freq=None, pol=None, reader_backend="auto"):
        self.path = path
        self.r = open_reader(path, reader_backend)
        ptype = self.r.value(f"{P.IDENT}/productType")
        if ptype not in (None, "GUNW"):
            raise ValueError(f"{os.path.basename(path)} is a {ptype} product, not GUNW")
        freqs = self.r.value(f"{P.IDENT}/listOfFrequencies") or ["A"]
        if isinstance(freqs, str):
            freqs = [freqs]
        self.freq = freq or ("A" if "A" in freqs else freqs[0])
        pols = self.r.value(f"{P.grids_root(self.freq)}/listOfPolarizations")
        if pols is None:
            pols = self._guess_pols()
        if isinstance(pols, str):
            pols = [pols]
        self.pols = list(pols)
        if pol and pol not in self.pols:
            raise ValueError(f"Polarization {pol} not in product (has {self.pols})")
        self.pol = pol or (self.pols[0] if self.pols else "HH")

    def _guess_pols(self):
        out = []
        for p in ("HH", "VV", "HV", "VH"):
            if self.r.exists(f"{P.unw_group(self.freq)}/{p}/unwrappedPhase"):
                out.append(p)
        return out

    # --- paths -------------------------------------------------------------
    def layer_path(self, key):
        gfun, in_pol, name, _, _ = P.LAYERS[key]
        g = gfun(self.freq)
        return f"{g}/{self.pol}/{name}" if in_pol else f"{g}/{name}"

    def grid_for(self, key):
        """Grid of a file layer. Coordinates live in the pol group in current
        products; older layouts kept them one level up, so try both."""
        gfun, in_pol, _, _, _ = P.LAYERS[key]
        g = gfun(self.freq)
        for base in ([f"{g}/{self.pol}", g] if in_pol else [g, f"{g}/{self.pol}"]):
            if self.r.exists(f"{base}/xCoordinates"):
                return core.Grid.from_coords(self.r.read(f"{base}/xCoordinates"),
                                             self.r.read(f"{base}/yCoordinates"),
                                             self.epsg(base))
        raise KeyError(f"No xCoordinates/yCoordinates found for {key}")

    def epsg(self, base=None):
        for b in ([base] if base else []) + [P.RADAR_GRID]:
            p = f"{b}/projection"
            if self.r.exists(p):
                code = self.r.attr(p, "epsg_code")
                if code is None:
                    code = self.r.value(p)
                return int(code)
        raise KeyError("No projection dataset found")

    def has(self, key):
        return self.r.exists(self.layer_path(key))

    def read_layer(self, key, window=None):
        p = self.layer_path(key)
        a = self.r.read(p, window)
        fill = self.r.attr(p, "_FillValue")
        if key == "wrapped_phase":
            a = np.angle(a).astype(np.float32)
            a[~np.isfinite(a)] = np.nan
            return a, np.nan
        if np.issubdtype(a.dtype, np.floating):
            a = a.astype(np.float32)
            if fill is not None and not (isinstance(fill, float) and np.isnan(fill)):
                a[a == fill] = np.nan
            return a, np.nan
        return a, (None if fill is None else int(np.real(fill)))

    def center_frequency(self):
        return float(self.r.value(f"{P.grids_root(self.freq)}/centerFrequency"))

    def identification(self):
        out = {}
        for k in P.IDENT_FIELDS:
            v = self.r.value(f"{P.IDENT}/{k}")
            if v is not None:
                out[k] = v
        return out

    def cube(self, name):
        p = f"{P.RADAR_GRID}/{name}"
        if not self.r.exists(p):
            return None
        return (self.r.read(p), self.r.read(f"{P.RADAR_GRID}/xCoordinates"),
                self.r.read(f"{P.RADAR_GRID}/yCoordinates"),
                self.r.read(f"{P.RADAR_GRID}/heightAboveEllipsoid"))

    def close(self):
        self.r.close()


def short_name(prod, path):
    gid = prod.identification().get("granuleId") or os.path.splitext(os.path.basename(path))[0]
    # NISAR_L2_PR_GUNW_001_030_A_019_002_2000_SH_<4 dates>_D00404_N_F_J_001
    m = re.match(r"NISAR_L2_\w\w_GUNW_\d+_(\d+)_([AD])_(\d+)_.*?_(\d{8})T\d+_\d{8}T\d+_(\d{8})T", gid)
    if m:
        track, d, frame, ref, sec = m.groups()
        return f"GUNW_T{track}{d}_F{frame}_{ref}_{sec}"
    return gid


def inspect(path, reader_backend="auto"):
    prod = GunwProduct(path, reader_backend=reader_backend)
    info = {"file": os.path.abspath(path), "reader": prod.r.backend,
            "frequency": prod.freq, "polarizations": prod.pols,
            "identification": prod.identification()}
    try:
        cf = prod.center_frequency()
        info["center_frequency_hz"] = cf
        info["wavelength_m"] = P.wavelength(cf)
    except Exception:
        pass
    layers = {}
    for k in P.LAYERS:
        if prod.has(k):
            g = prod.grid_for(k)
            layers[k] = {"path": prod.layer_path(k), "shape": [g.ny, g.nx],
                         "posting_m": [abs(g.dx), abs(g.dy)], "epsg": g.epsg}
    info["layers"] = layers
    info["radar_grid_cube"] = {k: prod.r.shape(f"{P.RADAR_GRID}/{v}")
                               for k, v in P.CUBE.items() if prod.r.exists(f"{P.RADAR_GRID}/{v}")}
    prod.close()
    return info


def _expand_layers(layers):
    if layers in (None, "", "default"):
        return list(P.DEFAULT_LAYERS)
    if isinstance(layers, str):
        layers = [s.strip() for s in layers.split(",") if s.strip()]
    if "all" in layers:
        return list(P.LAYERS) + list(P.DERIVED)
    if "default" in layers:
        i = layers.index("default")
        layers = layers[:i] + list(P.DEFAULT_LAYERS) + layers[i + 1:]
        layers = list(dict.fromkeys(layers))
    bad = [l for l in layers if l not in P.LAYERS and l not in P.DERIVED]
    if bad:
        raise ValueError(f"Unknown layer(s): {bad}. Choose from {list(P.LAYERS) + list(P.DERIVED)}")
    return layers


def convert(path, out_dir, backend, layers=None, freq=None, pol=None, bbox=None,
            corrections=P.CORRECTIONS, dem=None, height=0.0, ref_mode="largest",
            ref_lonlat=None, min_coherence=0.0, components="largest", sign=-1.0,
            prefix=None, quicklook=True, reader_backend="auto", log=print):
    """Convert one GUNW file. Returns the metadata dict (also written as JSON)."""
    layers = _expand_layers(layers)
    corrections = [c for c in (corrections or []) if c]
    for c in corrections:
        if c not in P.CORRECTIONS:
            raise ValueError(f"Unknown correction {c}; choose from {P.CORRECTIONS}")
    os.makedirs(out_dir, exist_ok=True)
    prod = GunwProduct(path, freq, pol, reader_backend)
    stem = prefix or short_name(prod, path)
    warnings = []

    def warn(msg):
        warnings.append(msg)
        log("WARNING: " + msg)

    meta = {"tool": f"nisargunw {__version__}", "input": os.path.abspath(path),
            "reader": prod.r.backend, "frequency": prod.freq, "polarization": prod.pol,
            "identification": prod.identification(), "outputs": {}, "warnings": warnings}

    ugrid = prod.grid_for("unwrapped_phase")
    meta["epsg"] = ugrid.epsg
    box = None
    if bbox is not None:
        box = backend.lonlat_bounds_to_crs(bbox, ugrid.epsg)
        uwin = ugrid.window_for_bounds(*box)
        if uwin is None:
            raise ValueError("The bounding box does not overlap this product.")
    else:
        uwin = (0, ugrid.ny, 0, ugrid.nx)
    meta["window_80m"] = list(uwin)
    gt = ugrid.geotransform(uwin)
    shape = (uwin[1] - uwin[0], uwin[3] - uwin[2])

    def write(key, arr, nodata, grid=ugrid, window=uwin, units=None, desc=None):
        units = units or (P.LAYERS[key][3] if key in P.LAYERS else P.DERIVED[key][0])
        desc = desc or (P.LAYERS[key][4] if key in P.LAYERS else P.DERIVED[key][1])
        fn = os.path.join(out_dir, f"{stem}_{key}.tif")
        tags = {"UNITS": units, "DESCRIPTION": desc, "NISAR_FREQUENCY": prod.freq,
                "NISAR_POLARIZATION": prod.pol, "SOURCE": os.path.basename(path)}
        ident = meta["identification"]
        for k in ("referenceZeroDopplerStartTime", "secondaryZeroDopplerStartTime",
                  "trackNumber", "frameNumber", "orbitPassDirection"):
            if k in ident:
                tags["NISAR_" + k] = str(ident[k])
        backend.write(fn, arr, grid.geotransform(window), grid.epsg, nodata, desc, tags)
        meta["outputs"][key] = {"file": os.path.basename(fn), "units": units,
                                "stats": core.summarise(arr) if np.issubdtype(arr.dtype, np.floating) else None}
        log(f"  wrote {os.path.basename(fn)}")

    # ---------------- plain file layers ----------------
    for key in [l for l in layers if l in P.LAYERS]:
        if not prod.has(key):
            warn(f"layer {key} is not in this product; skipped")
            continue
        g = prod.grid_for(key)
        if g.nx == ugrid.nx and g.ny == ugrid.ny and g.x0 == ugrid.x0 and g.y0 == ugrid.y0:
            win = uwin
        else:
            win = g.window_for_bounds(*box) if box else (0, g.ny, 0, g.nx)
        a, nd = prod.read_layer(key, win)
        write(key, a, nd, grid=g, window=win)

    need = set(l for l in layers if l in P.DERIVED)
    if not need:
        meta.update(_finish(meta, out_dir, stem))
        prod.close()
        return meta

    # ---------------- heights for the radar-grid cube ----------------
    xs, ys = ugrid.xs(uwin), ugrid.ys(uwin)
    heights = None
    if dem:
        heights = backend.dem_on_grid(dem, gt, shape, ugrid.epsg)
        bad = ~np.isfinite(heights)
        if bad.all():
            warn("DEM does not cover the output area; using constant height")
            heights = None
        elif bad.any():
            heights[bad] = np.nanmedian(heights)
        meta["heights"] = {"source": os.path.abspath(dem), "note":
                           "DEM heights used as heights above the ellipsoid (geoid offset ignored)"}
    if heights is None:
        heights = np.full(shape, float(height), np.float32)
        meta["heights"] = {"source": "constant", "value_m": float(height)}
        if dem is None and (need - {"keep_mask"}):
            warn(f"no DEM given: radar-grid layers are sampled at a constant {height} m "
                 "above the ellipsoid. Pass --dem for hilly areas.")

    cubes = {}

    def cube_layer(name):
        if name not in cubes:
            c = prod.cube(P.CUBE[name])
            cubes[name] = None if c is None else core.interp_cube(c[0], c[1], c[2], c[3], xs, ys, heights)
        return cubes[name]

    inc = cube_layer("incidence_angle")
    if "incidence_angle" in need:
        if inc is None:
            warn("incidenceAngle cube missing; incidence_angle skipped")
        else:
            write("incidence_angle", inc, np.nan)
    if need & {"los_east", "los_north", "los_up"}:
        lx, ly = cube_layer("los_x"), cube_layer("los_y")
        if lx is None or ly is None:
            warn("LOS unit-vector cubes missing; los_east/north/up skipped")
        else:
            lu = np.sqrt(np.clip(1 - lx.astype(np.float64) ** 2 - ly.astype(np.float64) ** 2, 0, 1)).astype(np.float32)
            for k, a in (("los_east", lx), ("los_north", ly), ("los_up", lu)):
                if k in need:
                    write(k, a, np.nan)

    tropo = None
    if "troposphere" in need or "troposphere" in corrections:
        w, h = cube_layer("wet_tropo"), cube_layer("hydro_tropo")
        if w is not None and h is not None:
            tropo = (w + h).astype(np.float32)
        if "troposphere" in need and tropo is not None:
            write("troposphere", tropo, np.nan)
    set_ = None
    if "solid_earth_tide" in need or "solid_earth_tide" in corrections:
        set_ = cube_layer("set")
        if "solid_earth_tide" in need and set_ is not None:
            write("solid_earth_tide", set_, np.nan)

    if not (need & {"los_displacement", "vertical_displacement", "keep_mask"}):
        meta.update(_finish(meta, out_dir, stem))
        prod.close()
        return meta

    # ---------------- displacement ----------------
    unw, _ = prod.read_layer("unwrapped_phase", uwin)
    cc, ccfill = prod.read_layer("connected_components", uwin)
    keep = np.isfinite(unw) & (cc > 0)
    if ccfill is not None:
        keep &= cc != ccfill
    if prod.has("mask"):
        mbits, mfill = prod.read_layer("mask", uwin)
        valid, water = P.decode_mask(mbits, mfill)
        keep &= valid & ~water
        meta["water_pixels"] = int(water.sum())
    else:
        warn("no product mask layer; water is not masked")
    if min_coherence and min_coherence > 0:
        coh, _ = prod.read_layer("coherence", uwin)
        keep &= np.nan_to_num(coh, nan=0) >= min_coherence
    sizes = core.component_sizes(cc, keep)
    meta["components"] = {"pixels_per_component": sizes, "policy": components}
    if components == "largest" and len(sizes) > 1:
        big = max(sizes, key=sizes.get)
        keep &= cc == big
        log(f"  {len(sizes)} connected components; keeping the largest (#{big}, "
            f"{sizes[big]} px). Use --components all to keep the rest.")
    elif len(sizes) > 1:
        warn(f"{len(sizes)} connected components kept: each may be offset from the others "
             "by a whole number of 2*pi (about 12 cm LOS at L-band)")

    phase = unw.astype(np.float32).copy()
    applied, skipped = [], []
    for c in corrections:
        if c == "ionosphere":
            arr = prod.read_layer("ionosphere", uwin)[0] if prod.has("ionosphere") else None
        elif c == "troposphere":
            arr = tropo
        else:
            arr = set_
        if arr is None or not np.isfinite(arr[keep]).any():
            skipped.append(c)
            warn(f"{c} correction not available in this product; not applied")
            continue
        arr = np.where(np.isfinite(arr), arr, 0).astype(np.float32)
        phase -= arr
        applied.append(c)
    meta["corrections"] = {"applied": applied, "skipped": skipped,
                           "note": "each correction phase is subtracted from unwrappedPhase"}

    lam = P.wavelength(prod.center_frequency())
    meta["wavelength_m"] = lam
    meta["sign"] = {"value": sign, "meaning": "LOS = sign * phase * wavelength / (4 pi); "
                    "with -1, positive = towards the satellite"}
    los = core.phase_to_los(phase, lam, sign)
    los[~keep] = np.nan

    ref_rc = None
    if ref_lonlat is not None:
        x, y = backend.lonlat_to_crs(ref_lonlat[0], ref_lonlat[1], ugrid.epsg)
        r = int(round((y - ugrid.y0) / ugrid.dy)) - uwin[0]
        c = int(round((x - ugrid.x0) / ugrid.dx)) - uwin[2]
        if not (0 <= r < shape[0] and 0 <= c < shape[1]):
            raise ValueError("The reference point is outside the output area.")
        ref_rc, ref_mode = (r, c), "point"
    los, rinfo = core.reference(los, keep, cc, ref_mode, ref_rc)
    if ref_rc is not None:
        rinfo["lonlat"] = list(ref_lonlat)
    meta["reference"] = rinfo

    if "los_displacement" in need:
        write("los_displacement", los, np.nan)
    if "vertical_displacement" in need:
        if inc is None:
            warn("incidenceAngle cube missing; vertical_displacement skipped")
        else:
            write("vertical_displacement", (los / np.cos(np.deg2rad(inc))).astype(np.float32), np.nan)
    if "keep_mask" in need:
        write("keep_mask", keep.astype(np.uint8), 255)

    meta["kept_pixels"] = int(keep.sum())
    meta["kept_fraction"] = float(keep.mean())
    if quicklook:
        try:
            from .quicklook import quicklook as ql
            fn = os.path.join(out_dir, f"{stem}_quicklook.png")
            ql(fn, los, unw, cc, keep, gt, meta)
            meta["quicklook"] = os.path.basename(fn)
        except ImportError:
            pass
    meta.update(_finish(meta, out_dir, stem))
    prod.close()
    return meta


def _finish(meta, out_dir, stem):
    fn = os.path.join(out_dir, f"{stem}_metadata.json")
    meta["metadata_file"] = os.path.basename(fn)
    with open(fn, "w") as f:
        json.dump(meta, f, indent=2, default=str)
    return {}
