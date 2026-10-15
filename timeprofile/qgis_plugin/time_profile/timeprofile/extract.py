"""The extractor: for every scene and feature, read only the pixels the feature
covers, mask clouds, compute the index, and summarise. Backend-agnostic: pass
rio_io or gdal_io as `io`."""

import numpy as np

from . import geom
from .indices import resolve
from .sensors import clear_mask

FIELDS = ["feature", "index", "date", "year", "doy", "sensor", "tile", "scene", "status", "value", "median",
          "std", "p10", "p90", "n_pixels", "n_valid", "n_clear", "clear_pct", "selection", "flag"]


def _stats(v):
    return {"value": float(np.mean(v)), "median": float(np.median(v)), "std": float(np.std(v)),
            "p10": float(np.percentile(v, 10)), "p90": float(np.percentile(v, 90))}


class Extractor:
    """Reusable across calls (caches pixel selections per grid), e.g. one per QGIS session."""

    def __init__(self, io, use_mask=True, extra_drop=(), buffer=0, min_clear=50.0):
        self.io, self.use_mask, self.extra_drop = io, use_mask, tuple(extra_drop)
        self.buffer, self.min_clear = buffer, min_clear
        self._tf, self._px = {}, {}

    def _transformer(self, crs):
        if crs not in self._tf:
            self._tf[crs] = self.io.make_transformer(crs)
        return self._tf[crs]

    def _pixels(self, feat, inf):
        key = (id(feat), inf.crs, inf.gt, inf.width, inf.height, self.buffer)
        if key not in self._px:
            self._px[key] = geom.pixels(feat, inf.gt, inf.width, inf.height, self._transformer(inf.crs), self.buffer)
        return self._px[key]

    @staticmethod
    def _read(h, band, rows, cols):
        r0, c0 = rows.min(), cols.min()
        win = h.read(band, int(c0), int(r0), int(cols.max() - c0 + 1), int(rows.max() - r0 + 1))
        return win[rows - r0, cols - c0]

    def _sample(self, h, band, ref, rows, cols):
        """Values of one band at the ref grid's pixel centres (handles 10 m vs 20 m files)."""
        inf = h.info
        if inf.gt == ref.gt:
            return self._read(h, band, rows, cols)
        x0, dx, _, y0, _, dy = ref.gt
        px, py = x0 + (cols + 0.5) * dx, y0 + (rows + 0.5) * dy
        X0, DX, _, Y0, _, DY = inf.gt
        c = np.floor((px - X0) / DX).astype(int)
        r = np.floor((py - Y0) / DY).astype(int)
        ok = (r >= 0) & (r < inf.height) & (c >= 0) & (c < inf.width)
        out = np.full(rows.shape, np.nan)
        if ok.any():
            out[ok] = self._read(h, band, r[ok], c[ok])
        return out

    def scene_rows(self, scene, features, formulas):
        """Rows (dicts, FIELDS) for one scene; features outside the scene give no row."""
        usable = [f for f in formulas if all(b in scene.bands for b in f.bands)]
        missing = sorted({b for f in formulas for b in f.bands} - set(scene.bands))
        note = f"{scene.id}: no {', '.join(missing)} band, so no {', '.join(f.name for f in formulas if f not in usable)}" \
            if missing else None
        if not usable:
            return [], note
        formulas = usable
        need = sorted({b for f in formulas for b in f.bands})
        handles = {}

        def h(path):
            if path not in handles:
                handles[path] = self.io.open_raster(path)
            return handles[path]
        try:
            ref = h(scene.bands[need[0]][0]).info
            out, warn = [], set()
            for feat in features:
                sel = self._pixels(feat, ref)
                if sel is None:
                    continue
                rows, cols, how = sel
                valid = np.ones(rows.shape, bool)
                data = {}
                for b in need:
                    path, band = scene.bands[b]
                    hb = h(path)
                    raw = self._sample(hb, band, ref, rows, cols).astype("float64")
                    nod = scene.nodata if scene.nodata is not None else hb.info.nodata[band - 1]
                    if nod is not None:
                        valid &= raw != nod
                    valid &= np.isfinite(raw)
                    data[b] = raw * scene.scale + scene.offset
                if not valid.any():
                    continue  # feature in the scene's grid but outside its data footprint
                if scene.scale != 1.0 or scene.offset:  # reflectance products: impossible values are bad data
                    bad = valid & np.any([(data[b] < -0.05) | (data[b] > 2.0) for b in need], axis=0)
                    if bad.sum() > 0.5 * valid.sum():
                        warn.add(f"{scene.id}: most pixels have impossible reflectance (check scale/offset); "
                                 "they were left out")
                    valid &= ~bad
                    if not valid.any():
                        continue
                clear = valid.copy()
                if self.use_mask and scene.mask:
                    mpath, mband, kind = scene.mask
                    qa = self._sample(h(mpath), mband, ref, rows, cols)
                    qa_ok = np.isfinite(qa)
                    qa = np.where(qa_ok, qa, 0).astype("int64")
                    clear &= qa_ok & ((qa != 0) if kind == "binary" else clear_mask(qa, kind, self.extra_drop))
                for f in formulas:
                    v = f(data)
                    good = clear & np.isfinite(v)
                    n_valid, n_clear = int(valid.sum()), int(good.sum())
                    pct = 100.0 * n_clear / n_valid
                    row = {"feature": feat["name"], "index": f.name, "date": scene.date.isoformat(),
                           "year": scene.date.year, "doy": scene.date.timetuple().tm_yday, "sensor": scene.sensor,
                           "tile": scene.tile, "scene": scene.id, "n_pixels": int(rows.size), "n_valid": n_valid,
                           "n_clear": n_clear, "clear_pct": round(pct, 1), "selection": how, "flag": ""}
                    if n_clear and pct >= self.min_clear:
                        row.update(status="clear", **_stats(v[good]))
                    else:
                        row.update(status="masked", value=None, median=None, std=None, p10=None, p90=None)
                    out.append(row)
            if note:
                warn.add(note)
            return out, "; ".join(sorted(warn)) or None
        finally:
            for hd in handles.values():
                hd.close()


def dedupe(rows):
    """One row per feature, index, date and sensor: where overlapping tiles both see a
    feature on the same day, keep the one with most clear (then valid) pixels."""
    best = {}
    for r in rows:
        k = (r["feature"], r["index"], r["date"], r["sensor"])
        score = (r["n_clear"], r["n_valid"])
        if k not in best or score > best[k][0]:
            best[k] = (score, r)
    kept = [v[1] for v in best.values()]
    kept.sort(key=lambda r: (r["feature"], r["index"], r["date"], r["sensor"]))
    return kept, len(rows) - len(kept)


def extract(scenes, features, indices, io, use_mask=True, extra_drop=(), buffer=0, min_clear=50.0,
            progress=None, cancelled=None, extractor=None):
    """Rows for every scene x feature x index. indices: names, band names or 'NAME=formula'.
    progress(i, n) is called after each scene; cancelled() can stop early.
    Returns (rows, notes) where notes lists skipped scenes and dropped duplicates."""
    formulas = [resolve(i) if isinstance(i, str) else i for i in indices]
    ex = extractor or Extractor(io, use_mask, extra_drop, buffer, min_clear)
    rows, notes = [], []
    for i, s in enumerate(scenes, 1):
        if cancelled and cancelled():
            notes.append("cancelled")
            break
        try:
            r, note = ex.scene_rows(s, features, formulas)
        except Exception as e:  # one broken file should not stop a long run
            r, note = [], f"{s.id}: {type(e).__name__}: {e}"
        rows += r
        if note:
            notes.append(note)
        if progress:
            progress(i, len(scenes))
    rows, dup = dedupe(rows)
    if dup:
        notes.append(f"{dup} duplicate observations from overlapping tiles dropped")
    return rows, notes
