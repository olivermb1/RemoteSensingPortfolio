"""One run: water classes per date -> flood map -> hectares per zone."""
import datetime as dt
import os

import numpy as np

from . import core


def _water(io, source, paths, grid, opts, clouds=None, baseline_db=None, threshold=None):
    """Class arrays for a list of files of one source type."""
    out, info = [], []
    for i, p in enumerate(paths):
        if source == "dswx":
            out.append(io.dswx_classes(p, grid))
        elif source == "mask":
            out.append(io.mask_classes(p, grid))
        elif source == "optical":
            c = clouds[i] if clouds else None
            out.append(io.optical_classes(p, grid, c, opts.get("cloud_kind", "scl"), opts.get("scale", 1.0)))
        elif source == "sar":
            db = io.sar_db(p, grid)
            t = threshold
            how = "given"
            if t is None:
                t, how = core.sar_threshold(db, default=opts.get("sar_default", -18.0), smooth=opts.get("smooth", 5))
            if baseline_db is not None and opts.get("sar_method", "change") == "change":
                out.append(core.sar_change_water(db, baseline_db, t, opts.get("drop_db", 3.0),
                                                 opts.get("loose_db", -14.0), opts.get("smooth", 5)))
            else:
                out.append(core.sar_water(db, t, opts.get("smooth", 5)))
            info.append(dict(file=os.path.basename(p), threshold_db=round(t, 2), threshold_from=how))
        else:
            raise ValueError(f"unknown source {source}")
    return out, info


def run(source, event, baseline=None, cropland=None, crop_preset="worldcover", zones=None,
        name_field=None, permanent=None, permanent_threshold=0.8, event_clouds=None,
        baseline_clouds=None, event_combine="any", baseline_combine="any", out_dir="out", backend=None, **opts):
    """`backend` is the I/O module: floodcrop.io (rasterio, default) or
    floodcrop.gdal_io (GDAL only, used inside QGIS). `zones` is a file path,
    or (zones, crs) already read by the backend's read_zones."""
    if backend is None:
        from . import io as backend  # rasterio; QGIS passes gdal_io instead
    io = backend
    os.makedirs(out_dir, exist_ok=True)
    grid = io.Grid.of(event[0])
    meta = dict(tool="floodcrop", version="0.1", run_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                source=source, event=[os.path.basename(p) for p in event],
                baseline=[os.path.basename(p) for p in (baseline or [])], cropland=cropland and os.path.basename(cropland),
                crop_preset=crop_preset, permanent=permanent and os.path.basename(permanent),
                permanent_threshold=permanent_threshold, event_combine=event_combine,
                baseline_combine=baseline_combine, grid=dict(crs=str(grid.crs), shape=grid.shape,
                                                             res=[abs(grid.transform[0]), abs(grid.transform[4])]),
                options=opts)

    # baseline first (SAR change detection needs its backscatter)
    base_cls, base_db = None, None
    sar_t = opts.pop("sar_threshold", None)
    if baseline:
        if source == "sar":
            dbs = [io.sar_db(p, grid) for p in baseline]
            base_db = np.nanmedian(np.stack(dbs), axis=0) if len(dbs) > 1 else dbs[0]
        bl, binfo = _water(io, source, baseline, grid, opts, baseline_clouds, threshold=sar_t)
        base_cls = core.combine(bl, baseline_combine)
        meta["baseline_detail"] = binfo
    ev, einfo = _water(io, source, event, grid, opts, event_clouds, baseline_db=base_db, threshold=sar_t)
    ev_cls = core.combine(ev, event_combine)
    meta["event_detail"] = einfo

    perm = io.permanent_mask(permanent, grid, permanent_threshold) if permanent else None
    flood = core.flood_classes(ev_cls, base_cls, perm)
    area = core.pixel_area_m2(grid.transform, grid.shape, io.is_geographic(grid))
    crop = io.crop_fraction(cropland, grid, crop_preset) if cropland else np.ones(grid.shape, np.float32)

    io.write(os.path.join(out_dir, "flood_classes.tif"), flood, grid, nodata=None)
    fc = np.where(flood == core.F_NEW_WATER, np.nan_to_num(crop), 0).astype(np.float32)
    fc[flood == core.F_UNOBSERVED] = np.nan
    io.write(os.path.join(out_dir, "flooded_crop_fraction.tif"), fc, grid, nodata=np.nan)

    rows, geoms = [], []
    if zones:
        zs, zcrs = io.read_zones(zones, name_field) if isinstance(zones, str) else zones
        for name, props, geom, mask in io.zone_masks(zs, zcrs, grid):
            r = dict(zone=name, **core.zone_summary(flood, crop, area, mask, base_cls))
            rows.append(r)
            geoms.append((geom, props, r))
        meta["zones"] = os.path.basename(zones) if isinstance(zones, str) else f"{len(zs)} polygons"
        meta["zones_crs"] = str(zcrs)
    whole = dict(zone="(whole grid)", **core.zone_summary(flood, crop, area, np.ones(grid.shape, bool), base_cls))
    meta["totals"] = {k: round(v, 2) for k, v in whole.items() if k != "zone"}
    meta["pixels"] = {core.FLOOD_LABELS[k]: int((flood == k).sum()) for k in core.FLOOD_LABELS}
    return dict(grid=grid, flood=flood, crop=crop, area=area, event=ev_cls, baseline=base_cls,
                rows=rows, whole=whole, geoms=geoms, meta=meta, zones_crs=meta.get("zones_crs"))
