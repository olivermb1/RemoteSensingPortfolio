"""Two ways to read the HDF5 file, with the same small interface.

- H5pyReader: used by the command line (pip install h5py).
- GdalReader: GDAL's multidimensional API, for QGIS, whose Python usually
  has GDAL with HDF5 support but not h5py.

Windows are (row0, row1, col0, col1), end-exclusive.
"""

import numpy as np


def _to_text(v):
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    if isinstance(v, np.ndarray):
        if v.dtype.kind in "SO":
            return [_to_text(x) for x in v.tolist()]
        if v.shape == ():
            return v.item()
        return v.tolist()
    if isinstance(v, (list, tuple)):
        return [_to_text(x) for x in v]
    if isinstance(v, np.generic):
        return v.item()
    return v


class H5pyReader:
    backend = "h5py"

    def __init__(self, path):
        import h5py
        self.path = path
        self._f = h5py.File(path, "r")

    def exists(self, p):
        return p in self._f

    def shape(self, p):
        return tuple(self._f[p].shape)

    def dtype(self, p):
        return self._f[p].dtype

    def read(self, p, window=None):
        ds = self._f[p]
        if ds.shape == ():
            return ds[()]
        if window is None:
            return ds[()]
        r0, r1, c0, c1 = window
        if ds.ndim == 2:
            return ds[r0:r1, c0:c1]
        return ds[:, r0:r1, c0:c1]

    def value(self, p, default=None):
        if p not in self._f:
            return default
        return _to_text(self._f[p][()])

    def attr(self, p, name, default=None):
        if p not in self._f or name not in self._f[p].attrs:
            return default
        return _to_text(self._f[p].attrs[name])

    def datasets(self):
        out = []
        import h5py

        def visit(name, obj):
            if isinstance(obj, h5py.Dataset):
                out.append(("/" + name, tuple(obj.shape), str(obj.dtype)))
        self._f.visititems(visit)
        return out

    def close(self):
        self._f.close()


class GdalReader:
    backend = "gdal"

    def __init__(self, path):
        from osgeo import gdal
        gdal.UseExceptions()
        self.path = path
        self._ds = gdal.OpenEx(path, gdal.OF_MULTIDIM_RASTER)
        if self._ds is None:
            raise IOError(f"GDAL could not open {path} as a multidimensional raster")
        self._root = self._ds.GetRootGroup()
        self._cache = {}

    def _arr(self, p):
        if p not in self._cache:
            try:
                self._cache[p] = self._root.OpenMDArrayFromFullname(p)
            except Exception:
                self._cache[p] = None
        return self._cache[p]

    def exists(self, p):
        return self._arr(p) is not None

    def shape(self, p):
        a = self._arr(p)
        return tuple(int(d.GetSize()) for d in a.GetDimensions())

    def dtype(self, p):
        from osgeo import gdal
        a = self._arr(p)
        dt = a.GetDataType()
        if dt.GetClass() == gdal.GEDTC_STRING:
            return np.dtype("O")
        from osgeo import gdal_array
        return np.dtype(gdal_array.GDALTypeCodeToNumericTypeCode(dt.GetNumericDataType()))

    def read(self, p, window=None):
        a = self._arr(p)
        nd = a.GetDimensionCount()
        if nd == 0:
            return np.asarray(self.value(p))
        if window is None:
            return a.ReadAsArray()
        r0, r1, c0, c1 = window
        if nd == 2:
            return a.ReadAsArray(array_start_idx=[r0, c0], count=[r1 - r0, c1 - c0])
        n0 = int(a.GetDimensions()[0].GetSize())
        return a.ReadAsArray(array_start_idx=[0, r0, c0], count=[n0, r1 - r0, c1 - c0])

    def value(self, p, default=None):
        from osgeo import gdal
        a = self._arr(p)
        if a is None:
            return default
        if a.GetDataType().GetClass() == gdal.GEDTC_STRING:
            v = a.Read()
            if isinstance(v, list) and a.GetDimensionCount() == 0 and len(v) == 1:
                return v[0]
            return v
        v = a.ReadAsArray()
        return _to_text(np.asarray(v))

    def attr(self, p, name, default=None):
        a = self._arr(p)
        if a is None:
            return default
        at = a.GetAttribute(name)
        if at is None:
            return default
        v = at.Read()
        if isinstance(v, (list, tuple)) and len(v) == 1:
            v = v[0]
        return _to_text(v)

    def datasets(self):
        out = []

        def walk(g, prefix):
            for n in g.GetMDArrayNames() or []:
                a = g.OpenMDArray(n)
                shp = tuple(int(d.GetSize()) for d in a.GetDimensions())
                out.append((f"{prefix}/{n}", shp, a.GetDataType().GetName() or "string"))
            for n in g.GetGroupNames() or []:
                walk(g.OpenGroup(n), f"{prefix}/{n}")
        walk(self._root, "")
        return out

    def close(self):
        self._cache.clear()
        self._root = None
        self._ds = None


def open_reader(path, backend="auto"):
    import os
    if backend == "auto":
        backend = os.environ.get("NISARGUNW_READER", "auto")
    if backend in ("auto", "h5py"):
        try:
            return H5pyReader(path)
        except ImportError:
            if backend == "h5py":
                raise
    return GdalReader(path)
