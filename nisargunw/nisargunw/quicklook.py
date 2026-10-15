"""PNG overview: unwrapped phase, connected components, LOS displacement."""

import numpy as np


def quicklook(path, los, unw, cc, keep, gt, meta):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    ny, nx = los.shape
    ext = [gt[0] / 1000, (gt[0] + nx * gt[1]) / 1000, (gt[3] + ny * gt[5]) / 1000, gt[3] / 1000]
    fig, ax = plt.subplots(1, 3, figsize=(15, 5), constrained_layout=True)
    im = ax[0].imshow(unw, cmap="twilight", extent=ext)
    ax[0].set_title("Unwrapped phase (rad), as in the file")
    fig.colorbar(im, ax=ax[0], shrink=0.8)
    ccm = np.where(cc > 0, cc, np.nan).astype(float)
    ccm[cc == 65535] = np.nan
    im = ax[1].imshow(ccm, cmap="tab10", extent=ext, interpolation="nearest")
    ax[1].set_title("Connected components (0 = blank)")
    v = los[np.isfinite(los)]
    lim = float(np.percentile(np.abs(v), 99)) * 100 if v.size else 1
    im = ax[2].imshow(los * 100, cmap="RdBu_r", vmin=-lim, vmax=lim, extent=ext)
    corr = ",".join(meta.get("corrections", {}).get("applied", [])) or "none"
    ax[2].set_title(f"LOS displacement (cm, + towards satellite)\ncorrections: {corr}")
    fig.colorbar(im, ax=ax[2], shrink=0.8)
    for a in ax:
        a.set_xlabel(f"x (km, EPSG:{meta.get('epsg')})")
    ax[0].set_ylabel("y (km)")
    ident = meta.get("identification", {})
    fig.suptitle(f"{ident.get('granuleId', '')[:90]}\n"
                 f"{str(ident.get('referenceZeroDopplerStartTime', ''))[:10]} to "
                 f"{str(ident.get('secondaryZeroDopplerStartTime', ''))[:10]}, "
                 f"{ident.get('orbitPassDirection', '')}, track {ident.get('trackNumber', '')}",
                 fontsize=9)
    fig.savefig(path, dpi=110)
    plt.close(fig)
