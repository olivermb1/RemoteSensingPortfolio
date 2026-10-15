"""Numpy-only maths: grids, windows, radar-cube interpolation, displacement."""

from dataclasses import dataclass

import numpy as np


@dataclass
class Grid:
    """A regular map grid described by pixel-centre coordinates."""
    x0: float   # centre of first column
    dx: float
    nx: int
    y0: float   # centre of first row
    dy: float   # usually negative
    ny: int
    epsg: int

    @classmethod
    def from_coords(cls, x, y, epsg):
        x = np.asarray(x, float)
        y = np.asarray(y, float)
        dx = (x[-1] - x[0]) / (len(x) - 1) if len(x) > 1 else 1.0
        dy = (y[-1] - y[0]) / (len(y) - 1) if len(y) > 1 else -1.0
        return cls(float(x[0]), float(dx), len(x), float(y[0]), float(dy), len(y), int(epsg))

    def geotransform(self, window=None):
        r0, c0 = (0, 0) if window is None else (window[0], window[2])
        left = self.x0 + (c0 - 0.5) * self.dx
        top = self.y0 + (r0 - 0.5) * self.dy
        return (left, self.dx, 0.0, top, 0.0, self.dy)

    def xs(self, window=None):
        c0, c1 = (0, self.nx) if window is None else (window[2], window[3])
        return self.x0 + np.arange(c0, c1) * self.dx

    def ys(self, window=None):
        r0, r1 = (0, self.ny) if window is None else (window[0], window[1])
        return self.y0 + np.arange(r0, r1) * self.dy

    def bounds(self):
        xs = (self.x0 - 0.5 * self.dx, self.x0 + (self.nx - 0.5) * self.dx)
        ys = (self.y0 - 0.5 * self.dy, self.y0 + (self.ny - 0.5) * self.dy)
        return min(xs), min(ys), max(xs), max(ys)

    def window_for_bounds(self, xmin, ymin, xmax, ymax):
        """Rows/cols of every pixel that touches the box; None if no overlap."""
        c_a = (xmin - self.x0) / self.dx + 0.5
        c_b = (xmax - self.x0) / self.dx + 0.5
        r_a = (ymin - self.y0) / self.dy + 0.5
        r_b = (ymax - self.y0) / self.dy + 0.5
        c0 = max(0, int(np.floor(min(c_a, c_b))))
        c1 = min(self.nx, int(np.ceil(max(c_a, c_b))))
        r0 = max(0, int(np.floor(min(r_a, r_b))))
        r1 = min(self.ny, int(np.ceil(max(r_a, r_b))))
        if c1 <= c0 or r1 <= r0:
            return None
        return (r0, r1, c0, c1)


def _interp_weights(coords, targets):
    """Index and weight for linear interpolation on a monotonic 1-D axis (clamped)."""
    coords = np.asarray(coords, float)
    n = len(coords)
    if n == 1:
        return np.zeros(len(targets), int), np.zeros(len(targets))
    idx = np.arange(n, dtype=float)
    if coords[-1] < coords[0]:
        f = np.interp(np.asarray(targets, float), coords[::-1], idx[::-1])
    else:
        f = np.interp(np.asarray(targets, float), coords, idx)
    i = np.minimum(np.floor(f).astype(int), n - 2)
    return i, f - i


def interp_cube(cube, cube_x, cube_y, cube_h, xs, ys, heights, block_rows=256):
    """Sample a radar grid cube (nh, ny, nx) at every pixel of a target grid.

    xs, ys: 1-D centre coordinates of the target grid; heights: 2-D array
    (len(ys), len(xs)) of heights above the ellipsoid, or a scalar. Bilinear in
    x/y, linear in height, clamped at the cube edges. NaN in the cube stays NaN.
    """
    cube = np.asarray(cube, np.float64)
    cube_h = np.asarray(cube_h, float)
    order = np.argsort(cube_h)
    cube, cube_h = cube[order], cube_h[order]
    ix, wx = _interp_weights(cube_x, xs)
    iy, wy = _interp_weights(cube_y, ys)
    # along x for every level and cube row: (nh, ny_cube, ncols)
    along_x = cube[:, :, ix] * (1 - wx) + cube[:, :, ix + 1] * wx if cube.shape[2] > 1 else \
        np.repeat(cube[:, :, :1], len(xs), axis=2)
    nrows = len(ys)
    out = np.empty((nrows, len(xs)), np.float32)
    h_all = np.broadcast_to(np.asarray(heights, float), (nrows, len(xs)))
    nh = len(cube_h)
    for r0 in range(0, nrows, block_rows):
        r1 = min(nrows, r0 + block_rows)
        a = along_x[:, iy[r0:r1], :]
        if cube.shape[1] > 1:
            b = along_x[:, iy[r0:r1] + 1, :]
            w = wy[r0:r1][None, :, None]
            lev = a * (1 - w) + b * w            # (nh, rows, cols)
        else:
            lev = a
        h = h_all[r0:r1]
        if nh == 1:
            out[r0:r1] = lev[0]
            continue
        k, wk = _interp_weights(cube_h, h.ravel())
        k = k.reshape(h.shape)
        wk = wk.reshape(h.shape)
        lo = np.take_along_axis(lev, k[None], 0)[0]
        hi = np.take_along_axis(lev, (k + 1)[None], 0)[0]
        out[r0:r1] = lo * (1 - wk) + hi * wk
    return out


def phase_to_los(phase, wavelength, sign=-1.0):
    """Radians -> metres along the line of sight.

    With sign=-1 (default) a positive result is motion TOWARDS the satellite.
    That holds when the interferogram is reference x conj(secondary), as isce3
    forms it, and is the convention MintPy uses. Check against the GUNW spec.
    """
    return sign * phase * wavelength / (4 * np.pi)


def component_sizes(cc, keep):
    labels = cc[keep & (cc > 0)].astype(np.int64)
    if labels.size == 0:
        return {}
    counts = np.bincount(labels)
    return {int(i): int(c) for i, c in enumerate(counts) if c > 0 and i > 0}


def reference(values, keep, cc=None, mode="largest", ref_rc=None, win=1):
    """Subtract a reference value. Returns (values, info dict).

    mode: 'point' (median in a (2*win+1)^2 box at ref_rc), 'largest' (median of
    the largest connected component), 'median' (median of all kept pixels),
    'none'.
    """
    v = values.astype(np.float32, copy=True)
    info = {"mode": mode}
    if mode == "none":
        return v, info
    if mode == "point":
        r, c = ref_rc
        box = (slice(max(0, r - win), r + win + 1), slice(max(0, c - win), c + win + 1))
        sel = v[box][keep[box] & np.isfinite(v[box])]
        if sel.size == 0:
            raise ValueError("The reference point has no valid pixels near it; pick another.")
        if cc is not None:
            info["component"] = int(np.bincount(cc[box][keep[box]].astype(np.int64)).argmax())
        ref = float(np.median(sel))
        info.update(row=int(r), col=int(c))
    else:
        sel_mask = keep & np.isfinite(v)
        if mode == "largest" and cc is not None:
            sizes = component_sizes(cc, sel_mask)
            if sizes:
                big = max(sizes, key=sizes.get)
                sel_mask = sel_mask & (cc == big)
                info["component"] = big
        sel = v[sel_mask]
        if sel.size == 0:
            raise ValueError("No valid pixels to reference to.")
        ref = float(np.median(sel))
    v -= ref
    info["value_subtracted"] = ref
    return v, info


def summarise(a, keep=None):
    a = np.asarray(a, float)
    m = np.isfinite(a) if keep is None else (keep & np.isfinite(a))
    if not m.any():
        return {"valid_pixels": 0}
    s = a[m]
    return {"valid_pixels": int(m.sum()), "min": float(s.min()), "p02": float(np.percentile(s, 2)),
            "median": float(np.median(s)), "p98": float(np.percentile(s, 98)), "max": float(s.max())}
