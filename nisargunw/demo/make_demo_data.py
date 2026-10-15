"""Build a synthetic NISAR L2 GUNW file over Fentale volcano, Ethiopia.

The HDF5 layout (paths, dtypes, fill values, attributes, pixel-centre
coordinates, radar grid cube) follows the isce3 GUNW writer, product spec
1.2.1. The numbers are invented: a dike-like deformation pattern shaped
after the 2024-25 Fentale-Dofen intrusion, with ionosphere, troposphere,
solid Earth tide, noise, Lake Beseka as water, a second connected component
offset by 2*pi, and a no-data wedge at the frame edge. The dates are
placeholders inside NISAR's operating period.

Needs: numpy, h5py, rasterio, pyproj. Uses the real Copernicus GLO-30 DEM, tiles N08/N09 E039
(downloaded once from the public AWS bucket into ~/.cache/nisargunw).

Writes demo/data/<granule>.h5, demo/data/dem_fentale.tif and
demo/data/truth_los_displacement.tif (the deformation put into the file).
"""

import os
import urllib.request

import h5py
import numpy as np
import rasterio
from affine import Affine
from pyproj import Transformer
from rasterio.warp import Resampling, reproject

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
SRC = os.environ.get("NISARGUNW_CACHE", os.path.expanduser("~/.cache/nisargunw"))
DEM_URL = ("https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_{t}_DEM/"
           "Copernicus_DSM_COG_10_{t}_DEM.tif")
DEM_TILES = ["N08_00_E039_00", "N09_00_E039_00"]
EPSG = 32637
GRANULE = ("NISAR_L2_PR_GUNW_001_172_A_045_004_2000_SH_20251104T154958_20251104T155033_"
           "20251116T154959_20251116T155034_X05010_N_F_J_001")
CENTER_FREQ = 1.2575e9
LAM = 299_792_458.0 / CENTER_FREQ
rng = np.random.default_rng(42)


def b(s):
    return np.bytes_(s.encode("utf-8"))


def get_dem():
    os.makedirs(SRC, exist_ok=True)
    out = []
    for t in DEM_TILES:
        p = os.path.join(SRC, f"cop_dem_{t}.tif")
        if not os.path.exists(p):
            print(f"downloading Copernicus DEM tile {t} ...")
            urllib.request.urlretrieve(DEM_URL.format(t=t), p + ".part")
            os.replace(p + ".part", p)
        out.append(p)
    return out


def to_grid(src_paths, x0, dx, nx, y0, dy, ny, crs=f"EPSG:{EPSG}", transform=None):
    """Mosaic the DEM tiles onto a grid (later tiles fill only what is still empty)."""
    out = np.full((ny, nx), np.nan, np.float32)
    transform = transform or Affine(dx, 0, x0 - dx / 2, 0, dy, y0 - dy / 2)
    for p in src_paths:
        part = np.full_like(out, np.nan)
        with rasterio.open(p) as src:
            reproject(rasterio.band(src, 1), part, dst_transform=transform, dst_crs=crs,
                      dst_nodata=np.nan, resampling=Resampling.bilinear)
        out = np.where(np.isfinite(out), out, part)
    return out


def main():
    os.makedirs(DATA, exist_ok=True)
    dem_src = get_dem()
    to_utm = Transformer.from_crs(4326, EPSG, always_xy=True)
    to_ll = Transformer.from_crs(EPSG, 4326, always_xy=True)

    # 24 x 24 km around Fentale, snapped to the 80 m grid (pixel centres at k*80 + 40)
    cx, cy = to_utm.transform(39.88, 8.95)
    n80, d80 = 300, 80.0
    x0 = np.floor((cx - n80 * d80 / 2) / d80) * d80 + d80 / 2
    y0 = np.floor((cy + n80 * d80 / 2) / d80) * d80 - d80 / 2
    x80 = x0 + np.arange(n80) * d80
    y80 = y0 - np.arange(n80) * d80
    n20 = n80 * 4
    x20 = (x0 - d80 / 2 + 10) + np.arange(n20) * 20.0
    y20 = (y0 + d80 / 2 - 10) - np.arange(n20) * 20.0

    h80 = to_grid(dem_src, x80[0], d80, n80, y80[0], -d80, n80)
    h20 = to_grid(dem_src, x20[0], 20.0, n20, y20[0], -20.0, n20)
    with rasterio.open(os.path.join(DATA, "dem_fentale.tif"), "w", driver="GTiff", width=n80 * 2,
                       height=n80 * 2, count=1, dtype="float32", crs="EPSG:4326",
                       transform=_ll_transform(to_ll, x80, y80, n80 * 2), compress="deflate",
                       nodata=np.nan) as dst:
        dst.write(_ll_dem(dem_src, to_ll, x80, y80, n80 * 2), 1)

    # radar grid cube: 2 km posting with a 4 km margin, 20 heights
    cxs = np.arange(x80[0] - 4000, x80[-1] + 4001, 2000.0)
    cys = np.arange(y80[0] + 4000, y80[-1] - 4001, -2000.0)
    hs = np.arange(-500.0, 9001.0, 500.0)
    HC, YC, XC = np.meshgrid(hs, cys, cxs, indexing="ij")

    def inc_of(x, h):  # incidence grows ~0.06 deg/km across range (east), falls with height
        return 37.0 + 0.06 * (x - cx) / 1000 - 0.0004 * h

    heading = np.deg2rad(-12.0)          # ascending, flying NNW
    look_az = heading + np.pi / 2        # right-looking: ENE from satellite to ground
    g2s_az = look_az + np.pi             # ground to satellite: WSW

    def los_vec(x, h):
        i = np.deg2rad(inc_of(x, h))
        return np.sin(i) * np.sin(g2s_az), np.sin(i) * np.cos(g2s_az), np.cos(i)

    def wet_tropo(x, y, h):   # differential wet delay as phase (rad); decays with height
        return (5.0 + 1.5 * (x - cx) / 12000.0) * np.exp(-np.maximum(h, -500) / 2000.0)

    def hydro_tropo(x, y, h):
        return 1.2 * np.exp(-np.maximum(h, -500) / 8000.0)

    def set_phase(x, y, h):
        return 0.25 + 0.15 * (x - cx) / 12000.0 - 0.1 * (y - cy) / 12000.0 + 0 * h

    # ---- truth on the 80 m grid ----
    X, Y = np.meshgrid(x80, y80)
    dxk, dyk = to_utm.transform(39.925, 8.985)    # dike centre near Fentale summit
    strike = np.deg2rad(20.0)                     # NNE, along the rift
    s = (X - dxk) * np.sin(strike) + (Y - dyk) * np.cos(strike)   # along strike, m
    d = (X - dxk) * np.cos(strike) - (Y - dyk) * np.sin(strike)   # across strike (ESE +)
    s_km, d_km = s / 1000, d / 1000
    taper = np.exp(-(s_km / 9.0) ** 2)
    uz = taper * (0.10 * (np.exp(-((d_km - 4.5) / 2.2) ** 2) + np.exp(-((d_km + 4.5) / 2.2) ** 2))
                  - 0.22 * np.exp(-(d_km / 1.3) ** 2))
    uperp = taper * 0.28 * np.tanh(d_km / 1.2) * np.exp(-(np.abs(d_km) / 6.0) ** 2)
    ue, un = uperp * np.cos(strike), -uperp * np.sin(strike)
    le, ln, lu = los_vec(X, h80)
    los_true = (ue * le + un * ln + uz * lu).astype(np.float32)    # m, + towards satellite

    iono = (3.0 * (X - cx) / 12000.0 + 1.5 * (Y - cy) / 12000.0
            + 1.2 * np.exp(-(((X - cx + 6000) / 7000) ** 2 + ((Y - cy - 3000) / 7000) ** 2)))
    trop = wet_tropo(X, Y, h80) + hydro_tropo(X, Y, h80)
    setp = set_phase(X, Y, h80)
    phi_def = -4 * np.pi / LAM * los_true

    # ---- masks, coherence, components ----
    blat, blon = 8.893, 39.885                    # Lake Beseka
    bx, by = to_utm.transform(blon, blat)
    lake = (((X - bx) / 2200) ** 2 + ((Y - by) / 1200) ** 2) < 1
    # frame-edge wedge with no data (SW corner)
    wedge = ((X - x80[0]) + (Y - y80[-1])) < 4500
    slope = np.hypot(*np.gradient(np.nan_to_num(h80, nan=np.nanmean(h80)), d80))
    coh = np.clip(0.82 - 0.6 * slope + rng.normal(0, 0.04, X.shape), 0.05, 0.98)
    # irrigated sugar-cane belt (Metehara estate): low coherence band south of the lake
    cane = (np.abs((Y - (by - 3800)) + 0.25 * (X - bx)) < 900) & (X > bx - 9000)
    coh[cane] = np.clip(rng.normal(0.15, 0.04, cane.sum()), 0.02, 0.3)
    coh[lake] = np.clip(rng.normal(0.08, 0.03, lake.sum()), 0.01, 0.2)
    cc = np.ones(X.shape, np.uint16)
    island = (Y < (by - 3800) - 0.25 * (X - bx) - 900) & (X > bx - 9000)    # south of the cane belt
    cc[island] = 2
    cc[(coh < 0.25)] = 0
    cc[lake] = 0
    nlooks = 16
    sig = np.sqrt((1 - coh ** 2) / (2 * nlooks * coh ** 2))
    noise = rng.normal(0, 1, X.shape) * np.minimum(sig, 3)
    unw = (phi_def + iono + trop + setp + noise).astype(np.float32)
    unw[island] += 2 * np.pi          # unwrapping ambiguity between components
    unw[cc == 0] = unw[cc == 0] + rng.normal(0, 1.5, (cc == 0).sum())
    unw_off = 3 * 2 * np.pi           # products are not zeroed anywhere in particular
    unw += unw_off

    fill_f = np.nan
    for a in (unw, coh):
        a[wedge] = fill_f
    coh = coh.astype(np.float32)
    cc[wedge] = 65535
    mask = np.full(X.shape, 11, np.uint32)        # subswath 1 in both RSLCs
    mask[lake] = 111
    mask[wedge] = 255
    valid = np.full(X.shape, 3, np.uint8)
    valid[wedge] = 255
    iono_est = (iono + rng.normal(0, 0.05, X.shape)).astype(np.float32)
    iono_est[wedge] = np.nan
    iono_unc = np.full(X.shape, 0.2, np.float32)
    iono_unc[wedge] = np.nan
    los_true[wedge] = np.nan

    # ---- 20 m wrapped interferogram ----
    X2, Y2 = np.meshgrid(x20, y20)
    up = lambda a: np.repeat(np.repeat(a, 4, 0), 4, 1)
    le2, ln2, lu2 = los_vec(X2, h20)
    phi20 = (up(phi_def) + up(iono) + wet_tropo(X2, Y2, h20) + hydro_tropo(X2, Y2, h20)
             + up(setp)).astype(np.float32)
    coh20 = np.clip(up(coh) + rng.normal(0, 0.05, X2.shape), 0.01, 0.99).astype(np.float32)
    sig20 = np.sqrt((1 - coh20 ** 2) / (2 * 4 * coh20 ** 2))
    phi20 += (rng.normal(0, 1, X2.shape) * np.minimum(sig20, 3)).astype(np.float32)
    wr = (np.exp(1j * phi20) * (0.2 + coh20)).astype(np.complex64)
    w20 = up(wedge)
    wr[w20] = np.complex64(np.nan + 1j * np.nan)
    coh20[w20] = np.nan
    mask20 = up(mask)
    valid20 = up(valid)

    # ---- write HDF5 ----
    out = os.path.join(DATA, GRANULE + ".h5")
    with h5py.File(out, "w") as f:
        f.attrs["Conventions"] = b("CF-1.7")
        f.attrs["title"] = b("NISAR L2 GUNW Product (SYNTHETIC DEMO, invented values)")
        f.attrs["institution"] = b("synthetic")
        ident = f.require_group("science/LSAR/identification")
        lons, lats = to_ll.transform([x80[0], x80[-1], x80[-1], x80[0], x80[0]],
                                     [y80[0], y80[0], y80[-1], y80[-1], y80[0]])
        poly = "POLYGON ((" + ",".join(f"{a:.6f} {c:.6f}" for a, c in zip(lons, lats)) + "))"
        for k, v in {
            "granuleId": GRANULE, "missionId": "NISAR", "productType": "GUNW", "productLevel": "L2",
            "productVersion": "0.1.0", "productSpecificationVersion": "1.2.1",
            "compositeReleaseId": "X05010", "orbitPassDirection": "Ascending",
            "lookDirection": "Right", "radarBand": "L", "instrumentName": "LSAR",
            "processingCenter": "SYNTHETIC", "processingType": "Nominal",
            "referenceZeroDopplerStartTime": "2025-11-04T15:49:58.000000000",
            "referenceZeroDopplerEndTime": "2025-11-04T15:50:33.000000000",
            "secondaryZeroDopplerStartTime": "2025-11-16T15:49:59.000000000",
            "secondaryZeroDopplerEndTime": "2025-11-16T15:50:34.000000000",
            "isGeocoded": "True", "isFullFrame": "False", "boundingPolygon": poly,
            "processingDateTime": "2026-10-15T00:00:00", "productDoi": "(synthetic)",
        }.items():
            ident[k] = b(v)
        ident["trackNumber"] = np.uint32(172)
        ident["frameNumber"] = np.uint16(45)
        ident["listOfFrequencies"] = np.array([b"A"])

        gr = f.require_group("science/LSAR/GUNW/grids/frequencyA")
        gr["centerFrequency"] = np.float64(CENTER_FREQ)
        gr["centerFrequency"].attrs["units"] = b("hertz")
        gr["listOfPolarizations"] = np.array([b"HH"])

        def geo(g, xs, ys):
            for name, v in (("xCoordinates", xs), ("yCoordinates", ys)):
                ds = g.require_dataset(name, shape=v.shape, dtype="f8", data=v)
                ds.attrs["units"] = b("meters")
                ds.attrs["description"] = b(f"{name[0].upper()} coordinates in specified projection")
                ds.make_scale()
            g["xCoordinateSpacing"] = np.float64(xs[1] - xs[0])
            g["yCoordinateSpacing"] = np.float64(ys[1] - ys[0])
            proj(g)

        def lay(g, name, a, units, desc, fill=None):
            ds = g.create_dataset(name, data=a, compression="gzip", compression_opts=4,
                                  shuffle=True, chunks=True)
            ds.attrs["units"] = b(units)
            ds.attrs["description"] = b(desc)
            ds.attrs["grid_mapping"] = b("projection")
            if fill is None:
                fill = {"f": np.float32(np.nan), "c": np.complex64(np.nan + 1j * np.nan)}.get(
                    a.dtype.kind, np.iinfo(a.dtype).max if a.dtype.kind == "u" else None)
            ds.attrs["_FillValue"] = np.asarray(fill, dtype=a.dtype)
            ds.dims[0].attach_scale(g["yCoordinates"]) if "yCoordinates" in g else None
            ds.dims[1].attach_scale(g["xCoordinates"]) if "xCoordinates" in g else None

        for grp_name, xs, ys, items in (
            ("unwrappedInterferogram", x80, y80, [
                ("coherenceMagnitude", coh, "1", "Coherence magnitude between HH layers", None),
                ("connectedComponents", cc, "1", "Connected components for HH layer", 65535),
                ("ionospherePhaseScreen", iono_est, "radians", "Ionosphere phase screen", None),
                ("ionospherePhaseScreenUncertainty", iono_unc, "radians",
                 "Uncertainty of the ionosphere phase screen", None),
                ("unwrappedPhase", unw, "radians", "Unwrapped interferogram between HH layers", None),
                ("validDataMask", valid, "1", "Valid mask for the HH layers", 255)]),
            ("wrappedInterferogram", x20, y20, [
                ("coherenceMagnitude", coh20, "1", "Coherence magnitude between HH layers", None),
                ("wrappedInterferogram", wr, "1", "Complex wrapped interferogram between HH layers", None),
                ("validDataMask", valid20, "1", "Valid mask for the HH layers", 255)]),
            ("pixelOffsets", x80, y80, [
                ("alongTrackOffset", np.where(wedge, np.nan, rng.normal(0, 0.15, X.shape)).astype(np.float32),
                 "meters", "Along-track offset", None),
                ("slantRangeOffset", np.where(wedge, np.nan, -los_true + rng.normal(0, 0.1, X.shape)).astype(np.float32),
                 "meters", "Slant range offset", None),
                ("correlationSurfacePeak", np.where(wedge, np.nan, np.clip(coh * 0.9, 0, 1)).astype(np.float32),
                 "1", "Normalized cross-correlation surface peak", None),
                ("validDataMask", valid, "1", "Valid mask for the HH layers", 255)]),
        ):
            g = gr.require_group(grp_name)
            geo(g, xs, ys)
            lay(g, "mask", mask20 if grp_name == "wrappedInterferogram" else mask, "1",
                "Combination of a water mask, a mask of subswaths of valid samples, and data anomalies", 255)
            pg = g.require_group("HH")
            geo(pg, xs, ys)
            for name, a, units, desc, fill in items:
                lay(pg, name, a, units, desc, fill)

        rg = f.require_group("science/LSAR/GUNW/metadata/radarGrid")
        for name, v in (("xCoordinates", cxs), ("yCoordinates", cys), ("heightAboveEllipsoid", hs)):
            rg[name] = v
            rg[name].attrs["units"] = b("meters")
        proj(rg)
        lx, ly, lz = los_vec(XC, HC)
        cubes = {
            "incidenceAngle": (inc_of(XC, HC), "degrees"),
            "elevationAngle": (inc_of(XC, HC) - 3.0, "degrees"),
            "losUnitVectorX": (lx, "1"), "losUnitVectorY": (ly, "1"),
            "alongTrackUnitVectorX": (np.full(XC.shape, np.sin(heading)), "1"),
            "alongTrackUnitVectorY": (np.full(XC.shape, np.cos(heading)), "1"),
            "wetTroposphericPhaseScreen": (wet_tropo(XC, YC, HC), "radians"),
            "hydrostaticTroposphericPhaseScreen": (hydro_tropo(XC, YC, HC), "radians"),
            "slantRangeSolidEarthTidesPhase": (set_phase(XC, YC, HC), "radians"),
            "perpendicularBaseline": (np.full(XC.shape, 85.0), "meters"),
            "parallelBaseline": (np.full(XC.shape, 40.0), "meters"),
        }
        for name, (v, units) in cubes.items():
            ds = rg.create_dataset(name, data=v.astype(np.float32 if "Phase" not in name else np.float64))
            ds.attrs["units"] = b(units)
            ds.attrs["grid_mapping"] = b("projection")
            ds.attrs["_FillValue"] = np.float32(np.nan)

    prof = dict(driver="GTiff", width=n80, height=n80, count=1, dtype="float32", crs=f"EPSG:{EPSG}",
                transform=Affine(d80, 0, x80[0] - d80 / 2, 0, -d80, y80[0] + d80 / 2),
                compress="deflate", nodata=np.nan)
    with rasterio.open(os.path.join(DATA, "truth_los_displacement.tif"), "w", **prof) as dst:
        dst.write(los_true, 1)
        dst.update_tags(UNITS="meters", DESCRIPTION="Invented LOS deformation put into the demo file "
                        "(+ towards satellite), before referencing")
    print(f"wrote {out} ({os.path.getsize(out) / 1e6:.1f} MB)")


def proj(g):
    from pyproj import CRS
    ds = g.require_dataset("projection", shape=(), dtype=np.uint32, data=EPSG)
    ds.attrs["epsg_code"] = np.int32(EPSG)
    ds.attrs["spatial_ref"] = b(CRS.from_epsg(EPSG).to_wkt())
    ds.attrs["grid_mapping_name"] = b("universal_transverse_mercator")
    ds.attrs["utm_zone_number"] = np.int32(37)
    ds.attrs["description"] = b("Product map grid projection: EPSG code, with additional "
                                "projection information as HDF5 Attributes")


def _ll_transform(to_ll, x80, y80, n):
    lons, lats = to_ll.transform([x80[0] - 2000, x80[-1] + 2000], [y80[0] + 2000, y80[-1] - 2000])
    return Affine((lons[1] - lons[0]) / n, 0, lons[0], 0, (lats[1] - lats[0]) / n, lats[0])


def _ll_dem(src_paths, to_ll, x80, y80, n):
    return to_grid(src_paths, 0, 0, n, 0, 0, n, crs="EPSG:4326",
                   transform=_ll_transform(to_ll, x80, y80, n))


if __name__ == "__main__":
    main()
