"""quicklook.png: where each scene sits relative to where it should be."""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

# One hue per NASA flag, ordered good to bad; grey when no flag was found.
COLORS = {"best": "#1b7837", "good": "#7fbf7b", "suspect": "#e08214", "poor": "#b2182b", None: "#8c8c8c"}


def plot(path, results, tolerance_m):
    meas = [r for r in results if r.get("dx_m") is not None]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.8), gridspec_kw={"width_ratios": [1, 1.4]})
    lim = max([tolerance_m * 2] + [abs(r["dx_m"]) for r in meas] + [abs(r["dy_m"]) for r in meas]) * 1.1
    ax1.add_patch(plt.Circle((0, 0), tolerance_m, fill=False, ls="--", lw=1, color="#555"))
    for r in meas:
        ax1.scatter(r["dx_m"] / 1000, -r["dy_m"] / 1000 * 1, s=46, color=COLORS.get(r["geo_qa"], "#8c8c8c"),
                    marker="o" if r.get("m_ok") else "x", zorder=3)
    ax1.patches[0].set_radius(tolerance_m / 1000)
    ax1.set_xlim(-lim / 1000, lim / 1000)
    ax1.set_ylim(-lim / 1000, lim / 1000)
    ax1.set_aspect("equal")
    ax1.axhline(0, color="#ccc", lw=0.8, zorder=0)
    ax1.axvline(0, color="#ccc", lw=0.8, zorder=0)
    ax1.set_xlabel("km east")
    ax1.set_ylabel("km north")
    ax1.set_title("Measured offset (dashed: tolerance; x: unreliable)", fontsize=10)

    rs = sorted(results, key=lambda r: r["time"])
    y = range(len(rs))
    vals = [r["offset_m"] / 1000 if r.get("m_ok") else 0 for r in rs]
    ax2.barh(list(y), vals, color=[COLORS.get(r["geo_qa"], "#8c8c8c") for r in rs], height=0.6)
    ax2.axvline(tolerance_m / 1000, ls="--", lw=1, color="#555")
    ax2.set_yticks(list(y))
    ax2.set_yticklabels([f"{r['time'][:10]} {r['orbit'] or ''}/{r['scene'] or ''}" for r in rs], fontsize=8)
    for i, r in enumerate(rs):
        ax2.text(max(vals + [0.1]) * 1.02, i, r["decision"], va="center", fontsize=8)
    ax2.invert_yaxis()
    ax2.set_xlabel("offset (km)")
    ax2.set_title("Per scene, coloured by NASA flag", fontsize=10)
    for s in ("top", "right"):
        ax1.spines[s].set_visible(False)
        ax2.spines[s].set_visible(False)
    handles = [plt.Line2D([], [], marker="o", ls="", color=c, label=k or "no flag") for k, c in COLORS.items()]
    fig.legend(handles=handles, loc="lower center", ncol=5, frameon=False, fontsize=9)
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    fig.savefig(path, dpi=120)
    plt.close(fig)
