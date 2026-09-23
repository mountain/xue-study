"""Draw the archived fields, so the artifact can be looked at rather than inferred.

WHAT IS ON THE FIGURE
---------------------
Top row, three maps over High Asia (55-140E, 5-60N), all from the same three
archived runs:
    GFS thetae850      the field whose plateau is pinned at the encoding ceiling
    ECMWF thetae850    the control: same level, same box, same quantization
    GFS tmp500         a level that actually exists above the plateau's ground
Bottom row: one transect along 30N through the plateau box.  A map shows that
something is flat; a transect shows HOW flat, against the two models that are
not flat.  That is the panel that carries the number.

WHY THE COLOURS ARE NOT XUE'S COLOURS VERBATIM
----------------------------------------------
xue's temperature ramp is in degrees Celsius, -60..50.  thetae850 is in Kelvin,
230..357, so every code falls past the ramp's top stop and the layer comes back
one constant colour -- this is measured, not asserted, in
`scripts/fig_palette_reach.py`, which runs xue's own `buildPalette`.

So this figure takes xue's STOPS (its colours, unchanged, in order) and
re-labels them onto each variable's own codebook range.  The palette is xue's;
only the axis it is stretched over is stated here.  Inventing a private colormap
would have made this figure incomparable with the viewer; using xue's axis
unchanged would have made it a solid rectangle.

THE SATURATION SHADING
----------------------
Cells within 2 K of the ceiling are drawn in flat ink over the field.  That
threshold is CHOSEN, not derived, and the figure says so.  The point of the
shading is not emphasis: it marks cells whose value is not a value.  Every
shaded cell holds a different true equivalent potential temperature, all of them
printed as the largest code the format can carry.

Usage:
  uv run --with numpy --with matplotlib python scripts/fig_high_asia_fields.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt                                      # noqa: E402
from matplotlib.colors import ListedColormap, Normalize               # noqa: E402

import figstyle                                                      # noqa: E402
from poster_field import BOXES, CEIL_TOL_K, Poster, load, runs_with   # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
figstyle.use()

DOMAIN = (55.0, 140.0, 5.0, 60.0)          # west, east, south, north
PLATEAU = BOXES["高原 80-92E,26-32N"]
TRANSECT_LAT = 30.0

# ORIENTATION WITHOUT A BASEMAP
# -----------------------------
# A map of High Asia with no geography on it is unreadable, so the obvious move
# is a coastline.  That move does not work here: Natural Earth came back
# truncated from two hosts in a row (38 KB, then a 140 KB file with a JPEG
# header spliced into the middle by a resumed fetch) -- the host-level partial
# block this project has hit before.  Vendoring an external boundary file is
# also barred by the publication boundary.
#
# So orientation is built from stated coordinates instead: a graticule, a set of
# landmarks, and -- the one that matters -- the collapse site this study exists
# for.  Nothing on the figure is derived from them; they are labels.
LANDMARKS = [
    ("Delhi", 28.61, 77.21), ("Kolkata", 22.57, 88.36),
    ("Dhaka", 23.81, 90.41), ("Karachi", 24.86, 67.01),
    ("Lhasa", 29.65, 91.14), ("Ürümqi", 43.83, 87.62),
    ("Kashgar", 39.47, 75.99), ("Beijing", 39.90, 116.41),
    ("Shanghai", 31.23, 121.47), ("Chengdu", 30.57, 104.07),
    ("Hanoi", 21.03, 105.85), ("Bangkok", 13.76, 100.50),
    ("Tashkent", 41.30, 69.24), ("Ulaanbaatar", 47.89, 106.91),
    ("Tokyo", 35.68, 139.69), ("Hong Kong", 22.32, 114.17),
    ("Kunming", 25.04, 102.71), ("Yangon", 16.87, 96.20),
]
# The 2026-08-26 Langtang Lirung collapse, 28.2853N 85.5252E, as recorded in
# docs/xue-verification-report.md.  This is the whole reason for the study.
SITE = ("Langtang Lirung 2026-08-26", 28.2853, 85.5252)

# xue's own temperature stops, in the order and colours xue uses them.  Only
# the values they are hung on are replaced, per variable, at draw time.
XUE_STOPS = [(-60, 39, 25, 89), (-50, 49, 54, 149), (-40, 55, 103, 190),
             (-30, 65, 155, 201), (-20, 111, 201, 183), (-10, 181, 226, 174),
             (0, 238, 239, 179), (10, 254, 217, 118), (20, 253, 153, 66),
             (30, 230, 85, 48), (40, 179, 32, 55), (50, 112, 20, 65)]


def xue_cmap(lo: float, hi: float) -> ListedColormap:
    """xue's colour order, stretched onto [lo, hi] instead of -60..50 degC."""
    stops = sorted(XUE_STOPS)
    pos = np.linspace(0.0, 1.0, len(stops))
    grid = np.linspace(0.0, 1.0, 256)
    rgb = np.empty((256, 4))
    for ch in range(3):
        vals = np.array([s[1 + ch] for s in stops], dtype=float) / 255.0
        rgb[:, ch] = np.interp(grid, pos, vals)
    rgb[:, 3] = 1.0
    cmap = ListedColormap(rgb, name=f"xue[{lo:g},{hi:g}]")
    cmap._stated_range = (lo, hi)                                    # noqa: SLF001
    return cmap


def draw_landmarks(ax, label_all: bool):
    """Graticule + landmarks + the study site.  No external geometry."""
    ax.grid(color="#ffffff", alpha=0.22, lw=0.6, zorder=3)
    for name, la, lo in LANDMARKS:
        if not (DOMAIN[0] < lo < DOMAIN[1] and DOMAIN[2] < la < DOMAIN[3]):
            continue
        ax.plot([lo], [la], marker="o", ms=2.6, color="#1b2027",
                mec="white", mew=0.7, zorder=6)
        if label_all:
            ax.annotate(name, (lo, la), xytext=(3.2, 2.0),
                        textcoords="offset points", fontsize=7.4,
                        color="#101418", zorder=7,
                        path_effects=None)
    name, la, lo = SITE
    ax.plot([lo], [la], marker="*", ms=15, color="#ffffff",
            mec="#c1121f", mew=1.5, zorder=8)
    if label_all:
        ax.annotate(name, (lo, la), xytext=(11, -13), textcoords="offset points",
                    fontsize=8.4, color="#7a0b13", fontweight="bold", zorder=9,
                    bbox=dict(facecolor="white", alpha=0.80, edgecolor="#c1121f",
                              lw=0.7, pad=2))


def window(p: Poster, box):
    """The sub-grid inside a lon/lat box, plus its own extent."""
    ri, li = p.box(*box)
    return (p.values[np.ix_(ri, li)], p.valid[np.ix_(ri, li)],
            (p.lon[li][0], p.lon[li][-1], p.lat[ri][-1], p.lat[ri][0]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", default=str(ROOT / "archive"))
    ap.add_argument("--out", default=str(ROOT / "figures" / "high-asia-fields.png"))
    ap.add_argument("--json", default=str(ROOT / "figures" / "high-asia-fields.json"))
    args = ap.parse_args()
    archive = Path(args.archive)

    def newest(coll, var):
        items = runs_with(archive, coll, var)
        if not items:
            raise SystemExit(f"archive/{coll} 里没有 {var}-poster")
        return items[-1]

    panes = [
        ("gfs", "thetae850", "GFS · θe850", "K"),
        ("ecmwf", "thetae850", "ECMWF · θe850（对照）", "K"),
        ("gfs", "tmp500", "GFS · 500 hPa T", "°C"),
    ]
    loaded = {}
    for coll, var, _t, _u in panes:
        item = newest(coll, var)
        loaded[(coll, var)] = (load(archive, coll, item, var), item)

    fig = plt.figure(figsize=(14.6, 10.0), dpi=140)
    gs = fig.add_gridspec(2, 3, height_ratios=[2.25, 1.0], hspace=0.46,
                          wspace=0.11, left=0.045, right=0.985, top=0.855,
                          bottom=0.135)

    plt.rcParams["hatch.color"] = "#101418"
    plt.rcParams["hatch.linewidth"] = 1.1

    summary, images, axes = {}, {}, []
    for k, (coll, var, title, unit) in enumerate(panes):
        p, item = loaded[(coll, var)]
        ax = fig.add_subplot(gs[0, k])
        axes.append(ax)
        sub, mask, extent = window(p, DOMAIN)
        # The axis a viewer needs is the CODEBOOK's, not this window's min/max:
        # a per-window stretch would make two panels that look alike while
        # meaning different numbers.
        cmap = xue_cmap(p.q["offset"], p.ceiling)
        cmap.set_bad((0, 0, 0, 0))
        shown = np.where(mask, sub, np.nan)
        im = ax.imshow(shown, extent=extent, origin="upper", cmap=cmap,
                       norm=Normalize(p.q["offset"], p.ceiling),
                       interpolation="nearest", zorder=2)
        images[(coll, var)] = im

        # The saturation overlay has to be unmissable: it is not emphasis, it
        # is the mark of a cell whose value is not a value.
        sat = (mask & (sub >= p.ceiling - CEIL_TOL_K)).astype(float)
        if sat.any():
            glon = np.linspace(extent[0], extent[1], sat.shape[1])
            glat = np.linspace(extent[3], extent[2], sat.shape[0])
            ax.contourf(glon, glat, sat, levels=[0.5, 1.5],
                        colors=["#f2f4f6"], alpha=0.34, zorder=5)
            ax.contourf(glon, glat, sat, levels=[0.5, 1.5], colors="none",
                        hatches=["////"], zorder=6)

        draw_landmarks(ax, label_all=(k == 0))
        ax.add_patch(plt.Rectangle((PLATEAU[0], PLATEAU[2]),
                                   PLATEAU[1] - PLATEAU[0], PLATEAU[3] - PLATEAU[2],
                                   fill=False, edgecolor="#ffd400", lw=1.8, zorder=7))
        ax.set_xlim(DOMAIN[0], DOMAIN[1])
        ax.set_ylim(DOMAIN[2], DOMAIN[3])
        ax.set_title(title, fontsize=11.5, pad=7)
        ax.set_xticks([60, 80, 100, 120, 140])
        ax.set_yticks([10, 20, 30, 40, 50])
        ax.tick_params(labelsize=8.5)
        if k == 0:
            ax.set_ylabel("纬度 °N", fontsize=9)
        else:
            ax.set_yticklabels([])

        st = p.box_stats(*PLATEAU)
        summary[f"{coll}/{var}"] = {"item": item, "ceiling": p.ceiling, **st}
        ax.text(0.018, 0.965,
                f"高原框：中位 {st['median']:.1f} {unit}   饱和 "
                f"{st['saturated_frac']*100:.1f}%",
                transform=ax.transAxes, fontsize=9.2, color="white", zorder=8,
                va="top",
                bbox=dict(facecolor=figstyle.INK, alpha=0.80, edgecolor="none",
                          pad=3.5))

    # One colorbar for the two thetae850 panels, because they are the same
    # quantity and must be read against one axis.  tmp500 gets its own: a
    # different variable in a different unit cannot share a scale, and pretending
    # otherwise is how two panels get compared as if they were comparable.
    cb1 = fig.colorbar(images[("gfs", "thetae850")], ax=axes[:2],
                       orientation="horizontal", fraction=0.055, pad=0.10,
                       aspect=40)
    q = loaded[("gfs", "thetae850")][0].q
    cb1.set_label(f"θe850  K ｜ 色标轴取自该变量自身的码位区间 "
                  f"{q['offset']:g}–{q['offset'] + q['scale'] * q['maximumCode']:g}",
                  fontsize=8.6)
    cb1.ax.tick_params(labelsize=8.5)
    cb2 = fig.colorbar(images[("gfs", "tmp500")], ax=axes[2],
                       orientation="horizontal", fraction=0.055, pad=0.10,
                       aspect=14)
    q5 = loaded[("gfs", "tmp500")][0].q
    cb2.set_label(f"500 hPa T  °C｜码位区间 "
                  f"{q5['offset']:g}–{q5['offset'] + q5['scale'] * q5['maximumCode']:g}",
                  fontsize=8.6)
    cb2.ax.tick_params(labelsize=8.5)

    # ---- bottom: the transect, which is where the number lives -------------
    ax = fig.add_subplot(gs[1, :])
    cols = {"gfs": figstyle.BAD, "ecmwf": figstyle.NEUTRAL, "aifs": figstyle.OK}
    for coll in ("gfs", "ecmwf", "aifs"):
        items = runs_with(archive, coll, "thetae850")
        if not items:
            continue
        p = load(archive, coll, items[-1], "thetae850")
        j = int(np.argmin(np.abs(p.lat - TRANSECT_LAT)))
        lon, row, ok = p.lon, p.values[j], p.valid[j]
        m = ok & (lon >= DOMAIN[0]) & (lon <= DOMAIN[1])
        ax.plot(lon[m], row[m], color=cols[coll], lw=2.0,
                label=f"{coll}（{items[-1][-10:]}）")
        gf = np.flatnonzero(m & (lon >= PLATEAU[0]) & (lon <= PLATEAU[1]))
        if coll == "gfs" and gf.size:
            ax.plot(lon[gf], row[gf], color=figstyle.WARN, lw=3.4, alpha=0.5,
                    zorder=3, solid_capstyle="butt")
    g = loaded[("gfs", "thetae850")][0]
    ax.axvspan(PLATEAU[0], PLATEAU[1], color="#ffd400", alpha=0.18, zorder=0)
    ax.axhline(g.ceiling, color=figstyle.INK, lw=1.4, ls="--", zorder=4)
    ax.text(DOMAIN[1] - 1.0, g.ceiling + 1.2, f"编码上限 {g.ceiling:.0f} K",
            ha="right", va="bottom", fontsize=9.2, color=figstyle.INK)
    # The two controls are annotated against the SAME quantity, so the reader
    # does not have to estimate the separation off the plot.
    for coll in ("ecmwf", "aifs"):
        items = runs_with(archive, coll, "thetae850")
        if not items:
            continue
        p = load(archive, coll, items[-1], "thetae850")
        j = int(np.argmin(np.abs(p.lat - TRANSECT_LAT)))
        lon, row, ok = p.lon, p.values[j], p.valid[j]
        m = ok & (lon >= PLATEAU[0]) & (lon <= PLATEAU[1])
        ax.plot(lon[m], row[m], color=cols[coll], lw=3.6, alpha=0.42, zorder=3,
                solid_capstyle="butt")
    ax.annotate(f"框内中位 {summary['gfs/thetae850']['median']:.1f} K",
                xy=(PLATEAU[1] - 3, summary["gfs/thetae850"]["median"]),
                xytext=(PLATEAU[1] + 5, g.ceiling - 5.0), fontsize=9.2,
                color=figstyle.BAD, fontweight="bold", va="top",
                arrowprops=dict(arrowstyle="->", color=figstyle.BAD, lw=1.3))
    ax.annotate(f"框内中位 {summary['ecmwf/thetae850']['median']:.1f} K",
                xy=(PLATEAU[0] + 2, summary["ecmwf/thetae850"]["median"]),
                xytext=(PLATEAU[0] - 15, 306), fontsize=9.2,
                color=figstyle.NEUTRAL, fontweight="bold",
                arrowprops=dict(arrowstyle="->", color=figstyle.NEUTRAL, lw=1.3))
    ax.text(np.mean(PLATEAU[:2]), 299, "高原框", ha="center", fontsize=9,
            color="#8a6d00")
    ax.set_xlim(DOMAIN[0], DOMAIN[1])
    # Headroom kept above the ceiling line so the legend has a band of its
    # own: at 296-364 the legend sat on the curves through 60-80E.
    ax.set_ylim(296, 378)
    ax.set_xlabel("经度 °E（沿 30°N 取一行）", fontsize=10)
    ax.set_ylabel("θe850  K", fontsize=10)
    ax.set_title("同一纬度上的一行：高原框内 GFS 贴着上限走成一条平线，另两家低 30 K 以上",
                 fontsize=11.5)
    figstyle.tidy(ax, "both")
    ax.legend(fontsize=9, frameon=False, loc="upper left", ncols=3)

    figstyle.title(
        fig, "同一个模式，同一个地方，两个层次：一个被削平，一个没有",
        "三张图取自 archive/ 的三次归档运行 poster 首帧，域相同、时刻相同。黄色框是高原框"
        "（80-92E, 26-32N）；斜纹＝落在编码上限 2 K 以内的格点（阈值选定，非导出）。"
        "GFS 的 θe850 在框内一半以上落到斜纹里，ECMWF 同一层次一格都没有。")
    figstyle.footer(
        fig, "源：archive/ 的 poster（0.5° 降采样网格，非全分辨率 store），本仓库现场解码；"
             "经纬映射已由 scripts/poster_grid_check.py 用 4,982 条机场实测检验（1.70 K 对 7.19 K）。"
             "边界：色标用 xue 的颜色顺序、但按各变量自身的码位区间重标定 —— xue 现行的用法会把 θe850 "
             "整层画成一个常数色（scripts/fig_palette_reach.py 实测 1/255）；这一处不是照抄，是本图的改动。")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    Path(args.json).write_text(json.dumps(summary, indent=1, ensure_ascii=False))
    print("\n高原框内统计（现场重算）")
    for key, st in summary.items():
        coll, var = key.split("/")
        print(f"  {coll:<6}{var:<10} 中位 {st['median']:7.1f}  "
              f"饱和 {st['saturated_frac']*100:6.2f}%  "
              f"落在上限处 {st['at_ceiling_frac']*100:6.2f}%  上限 {st['ceiling']:.1f}")
    print(f"\n  写入 {out} 和 {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
