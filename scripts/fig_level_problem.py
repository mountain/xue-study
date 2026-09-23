"""Measure, rather than assume, which pressure levels the plateau's ground is above.

WHY THIS IS THE FIRST FIGURE OF THE WHOLE STUDY
-----------------------------------------------
Everything downstream inherits one geometric fact: over the Tibetan Plateau the
surface pressure is near 580 hPa, so the 850 hPa surface is BELOW the ground
over most of the box the study keeps asking about.  A request for "850 hPa
temperature over the plateau" is therefore not a request for an observation.  It
is a request for an extrapolation, and each system answers it by its own
convention (see `scripts/fig_conventions.py`).

Until now that fact was RECORDED -- the number 582.6 hPa came from the report's
§3605 and was not recomputed here.  This script measures it from ERA5's own
surface pressure and surface geopotential, so the mechanism rests on a number
this repository produced.

WHAT IS MEASURED AND HOW
------------------------
Source: ARCO ERA5, `surface_pressure` and `geopotential_at_surface`, 1959-2022
6-hourly, equiangular 240x121, anonymous access.  For the plateau box the script
reports the surface-pressure distribution and the fraction of gridpoints below
each standard level.  It also reports the height of each level ABOVE the ground,
from `geopotential`, which is the version of the statement that does not depend
on a pressure threshold at all.

WHAT THIS DOES NOT CLAIM
------------------------
It is ERA5's terrain, not the real terrain, and a 1.5 deg grid cell is not a
point.  The plateau's true relief is far more extreme than any model grid can
carry, so the fractions here are a statement about ERA5's representation of the
plateau, which is exactly what matters when the question is asked of ERA5 or of
any model on a comparable grid.

Usage:
  export UV_CACHE_DIR=/tmp/uv-cache
  uv run --with numpy --with xarray --with zarr --with fsspec --with aiohttp \
     --with gcsfs --with matplotlib python scripts/fig_level_problem.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt                                      # noqa: E402

import figstyle                                                      # noqa: E402
from poster_field import BOXES                                        # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
figstyle.use()

URL = ("https://storage.googleapis.com/gcp-public-data-arco-era5/ar/"
       "1959-2022-6h-240x121_equiangular_with_poles_conservative.zarr")
PLATEAU = BOXES["高原 80-92E,26-32N"]
WARMPOOL = BOXES["暖池 120-180E,15S-15N"]
LEVELS = [850, 500, 250]
R_GAS, G_ACC = 287.05, 9.80665


def open_era5():
    import fsspec
    import xarray as xr
    ds = xr.open_zarr(fsspec.get_mapper(URL), chunks=None, consolidated=True)
    lon = np.asarray(ds.longitude.values, dtype=float)
    lat = np.asarray(ds.latitude.values, dtype=float)
    return ds, lat, lon


def box_mask(lat, lon, box):
    """Boolean mask for a lon/lat box, with the seam handled as a UNION.

    `(lon >= w) | (lon <= e)` is the union and is right ONLY when the box crosses
    the 0/360 seam.  Using it unconditionally is how a mask once selected the
    entire globe; using the intersection unconditionally is how it selects
    nothing.  The branch below is the fix, and the caller prints the share.
    """
    west, east, south, north = box
    if west <= east:
        mx = (lon >= west) & (lon <= east)
    else:
        mx = (lon >= west) | (lon <= east)
    my = (lat >= south) & (lat <= north)
    m = my[:, None] & mx[None, :]
    if m.sum() == 0:
        raise ValueError(f"box {box} 选了 0 格")
    if m.sum() > 0.5 * m.size:
        raise ValueError(f"box {box} 选了 {m.sum()}/{m.size} 格，超过一半，框错了")
    return m


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2020)
    ap.add_argument("--month", default="09")
    ap.add_argument("--out", default=str(ROOT / "figures" / "level-problem.png"))
    ap.add_argument("--json", default=str(ROOT / "figures" / "level-problem.json"))
    args = ap.parse_args()

    ds, lat, lon = open_era5()
    print(f"ERA5 ARCO：lat {lat[0]:.1f}..{lat[-1]:.1f}，lon {lon[0]:.1f}..{lon[-1]:.1f}，"
          f"格距 {abs(lat[1] - lat[0]):.2f}°")
    print(f"层次 {list(ds.level.values)}")

    lon180 = np.where(lon > 180.0, lon - 360.0, lon)
    order = np.argsort(lon180)

    window = dict(time=slice(f"{args.year}-{args.month}-01",
                             f"{args.year}-{args.month}-30T23"))
    sp = ds["surface_pressure"].sel(window)              # Pa
    # geopotential_at_surface is STATIC in this store -- it has no time
    # dimension at all.  Slicing it by time raises rather than silently
    # broadcasting, which is the behaviour to want.
    zg_surf = ds["geopotential_at_surface"].transpose(..., "latitude", "longitude")
    print(f"读取窗口 {args.year}-{args.month}：{sp.sizes['time']} 个时次；"
          f"地形静止（dims={dict(zg_surf.sizes)}）")

    def field_box(da, box, reduce="median"):
        # Transpose by NAME rather than trusting the on-disk order: this store
        # hands back (longitude, latitude), not (latitude, longitude), and
        # assuming the wrong one put a 240-long index onto a 121-long axis.
        da = da.transpose(..., "latitude", "longitude")
        a = np.asarray(da.values, dtype=float)
        if a.ndim == 3:
            a = np.nanmedian(a, axis=0)
        a = a[:, order]
        m = box_mask(lat, lon180[order], box)
        return a, m

    sp_pa, m_pl = field_box(sp, PLATEAU)
    zg, _ = field_box(zg_surf, PLATEAU)
    sp_hpa = sp_pa / 100.0
    elev = zg / G_ACC
    pl = sp_hpa[m_pl]
    el = elev[m_pl]

    print(f"\n高原框 {PLATEAU}：{m_pl.sum()} 格（占全域 {m_pl.mean()*100:.2f}%）")
    print(f"  地面气压中位 {np.median(pl):.1f} hPa   "
          f"p10-p90 {np.percentile(pl, 10):.1f}-{np.percentile(pl, 90):.1f} hPa")
    print(f"  地形高度中位 {np.median(el):.0f} m   p10-p90 "
          f"{np.percentile(el, 10):.0f}-{np.percentile(el, 90):.0f} m")

    frac = {}
    for lev in LEVELS:
        f = float((pl < lev).mean())
        frac[lev] = f
        print(f"  {lev:>4} hPa 位于地下的格点：{f*100:6.2f}%")

    # The threshold-free version of the same statement: how far above the
    # ground each level actually is, from geopotential rather than from a
    # pressure cutoff.  A level at -400 m is underground whatever the threshold.
    zg_lev = ds["geopotential"].transpose(
        ..., "latitude", "longitude").sel(
        level=LEVELS, time=f"{args.year}-{args.month}-15T00")
    zg_lev_surf = zg_surf          # already transposed to (latitude, longitude)
    heights, h850_full = {}, None
    for lev in LEVELS:
        z = np.asarray(zg_lev.sel(level=lev).values, dtype=float)[:, order]
        zs = np.asarray(zg_lev_surf.values, dtype=float)[:, order]
        above = (z - zs) / G_ACC
        v = above[m_pl]
        heights[lev] = {"median": float(np.median(v)),
                        "p10": float(np.percentile(v, 10)),
                        "p90": float(np.percentile(v, 90)),
                        "underground_frac": float((v < 0).mean()),
                        "per_cell_m": [round(float(x), 1) for x in v]}
        if lev == 850:
            h850_full = (z - zs) / G_ACC      # whole grid, not just the box
        print(f"  {lev:>4} hPa 距地面中位 {np.median(v):+7.0f} m  "
              f"(p10-p90 {np.percentile(v, 10):+.0f}..{np.percentile(v, 90):+.0f})  "
              f"地下占比 {heights[lev]['underground_frac']*100:5.1f}%")

    # The control: over the warm pool nobody has to extrapolate anything.
    sp_wp, m_wp = field_box(sp, WARMPOOL)
    wp = (sp_wp / 100.0)[m_wp]
    wp_frac = float((wp < 850).mean())
    print(f"\n对照 · 暖池 {WARMPOOL}：地面气压中位 {np.median(wp):.1f} hPa，"
          f"850 hPa 在地下 {wp_frac*100:.2f}%")
    control_ok = wp_frac < 0.02 and frac[850] > 0.5
    print("判定：" + ("对照通过 —— 850 hPa 只在高原框内是「地下」"
                    if control_ok else "对照未通过 —— 不得据此讲层次的故事"))

    # ---- figure -----------------------------------------------------------
    fig = plt.figure(figsize=(14.0, 7.6), dpi=140)
    gs = fig.add_gridspec(1, 3, width_ratios=[1.5, 1.15, 0.95], wspace=0.26,
                          left=0.05, right=0.985, top=0.79, bottom=0.165)

    axm = fig.add_subplot(gs[0, 0])
    # The map shows HOW FAR ABOVE THE GROUND the 850 hPa surface sits, not the
    # surface pressure.  Two reasons: it is the quantity the whole study turns
    # on, and its zero is meaningful -- so one diverging scale can say
    # "underground" on one side and "in the air" on the other without the
    # reader having to hold a threshold in their head.  A rainbow of pressure
    # would have made the plateau one more colour.
    ext = (lon180[order][0], lon180[order][-1], lat[0], lat[-1])
    im = axm.imshow(h850_full, extent=ext, origin="lower", cmap="RdBu",
                    vmin=-4500, vmax=4500, interpolation="nearest",
                    aspect="auto")
    axm.contour(np.linspace(*ext[:2], h850_full.shape[1]),
                np.linspace(*ext[2:], h850_full.shape[0]),
                h850_full, levels=[0.0], colors="#101418", linewidths=2.0)
    axm.add_patch(plt.Rectangle((PLATEAU[0], PLATEAU[2]),
                                PLATEAU[1] - PLATEAU[0], PLATEAU[3] - PLATEAU[2],
                                fill=False, edgecolor="#ffd400", lw=2.2, zorder=6))
    axm.text(123, 46, "深红＝850 hPa 在地面【之下】\n蓝白＝在地面之上\n黑线＝两者交界",
             fontsize=8.8, color="#101418", zorder=7,
             bbox=dict(facecolor="white", alpha=0.86, edgecolor="#bbbfc4",
                       lw=0.8, pad=4))
    axm.set_xlim(60, 140)
    axm.set_ylim(5, 60)
    axm.set_xlabel("经度 °E", fontsize=9.5)
    axm.set_ylabel("纬度 °N", fontsize=9.5)
    axm.set_title("850 hPa 距地面的高度（ERA5，2020-09-15 00Z）", fontsize=11)
    cb = fig.colorbar(im, ax=axm, orientation="horizontal", fraction=0.05,
                      pad=0.10, aspect=30, extend="both")
    cb.set_label("850 hPa 在地面之上的高度  m", fontsize=9)
    cb.ax.tick_params(labelsize=8)

    axh = fig.add_subplot(gs[0, 1])
    # Linear counts, not log: with 32 cells in the box the log axis showed
    # nothing, and a panel that shows nothing is worse than no panel.
    axh.hist(pl, bins=np.arange(540, 990, 20), color="#8d99ae", zorder=3,
             edgecolor="white", lw=0.7)
    axh.set_ylim(0, max(6, int(np.histogram(pl, bins=np.arange(540, 990, 20))[0].max()) + 2))
    med = float(np.median(pl))
    axh.axvline(med, color=figstyle.INK, lw=1.5, ls="--", zorder=4)
    axh.annotate(f"中位 {med:.0f} hPa", xy=(med, axh.get_ylim()[1] * 0.40),
                 xytext=(med + 46, axh.get_ylim()[1] * 0.30), fontsize=9.5,
                 color=figstyle.INK,
                 arrowprops=dict(arrowstyle="->", color=figstyle.INK, lw=1.2))
    axh.axvline(850, color=figstyle.BAD, lw=2.0, zorder=4)
    axh.annotate("850 hPa", xy=(850, axh.get_ylim()[1] * 0.30),
                 xytext=(866, axh.get_ylim()[1] * 0.42), fontsize=10,
                 color=figstyle.BAD, fontweight="bold",
                 arrowprops=dict(arrowstyle="->", color=figstyle.BAD, lw=1.2))
    axh.set_xlim(540, 990)
    axh.set_xlabel("高原框内地面气压  hPa", fontsize=10)
    axh.set_ylabel("格点数", fontsize=10)
    axh.set_title("框内地面气压分布", fontsize=11.5)
    figstyle.tidy(axh, "both")
    axh.text(0.975, 0.97,
             "地下格点占比\n"
             + "\n".join(f"{l} hPa　{frac[l]*100:.0f}%" for l in LEVELS)
             + f"\n框内最低 {pl.min():.0f} hPa，故 500/250\n永远落在这条轴的左侧之外\n"
               "（即永远在地面之上）",
             transform=axh.transAxes, ha="right", va="top", fontsize=9.0,
             bbox=dict(facecolor="white", edgecolor="#bbbfc4", lw=1.0, pad=4))

    # The right panel answers a different question from the histogram: not
    # "where is the ground" but "where are the LEVELS relative to it".  The
    # ground is drawn as one median line with its spread stated in words,
    # because the box's southern edge reaches low ground and a shaded p10-p90
    # band would cover most of the panel and say nothing.
    # One dot per grid cell, per level.  A strip cannot collide with itself,
    # and it shows the thing the percentiles hide: whether ANY cell in the box
    # gives the level a meaning.  For 850 hPa, none does.
    axv = fig.add_subplot(gs[0, 2])
    lcols = {850: figstyle.BAD, 500: figstyle.OK, 250: "#6a4c93"}
    rng = np.random.default_rng(7)          # jitter only; no data depends on it
    for k, lev in enumerate(LEVELS):
        vals = np.array(heights[lev]["per_cell_m"], dtype=float)
        y = k + rng.uniform(-0.16, 0.16, vals.size)
        axv.scatter(vals, y, s=34, color=lcols[lev], alpha=0.85,
                    edgecolor="white", lw=0.6, zorder=4)
        axv.plot([np.median(vals)] * 2, [k - 0.32, k + 0.32], color=figstyle.INK,
                 lw=2.4, zorder=5)
        axv.text(np.median(vals), k + 0.40, f"中位 {np.median(vals):+.0f} m",
                 ha="center", fontsize=8.8, color=figstyle.INK)
    axv.axvline(0.0, color=figstyle.INK, lw=1.5, ls="--", zorder=3)
    axv.axvspan(-5200, 0, color="#fbe3e0", zorder=0)
    axv.text(-4900, 2.62, "地面之下", fontsize=9.2, color="#8c1c13")
    axv.text(200, 2.62, "地面之上", fontsize=9.2, color="#1c5c8c")
    axv.set_yticks(range(len(LEVELS)))
    axv.set_yticklabels([f"{l} hPa" for l in LEVELS], fontsize=11)
    axv.set_ylim(-0.55, 2.95)
    axv.set_xlim(-5200, 11500)
    axv.set_xlabel("该层在地面之上的高度  m（每点＝高原框内一个格点）", fontsize=9.5)
    axv.set_title("同一件事的另一种说法", fontsize=11.5)
    figstyle.tidy(axv, "x")

    figstyle.title(
        fig, "高原的地面在 850 hPa 之下 —— 这一条是本步实测的",
        f"ERA5 自己报的地面气压与位势，{args.year}-{args.month}。"
        f"高原框内地面气压中位 {np.median(pl):.1f} hPa，"
        f"{frac[850]*100:.0f}% 的格点上 850 hPa 位于地下；"
        f"而 500 hPa 在 {100 - heights[500]['underground_frac']*100:.0f}% 的格点上都还在地面之上。")
    figstyle.footer(
        fig, "源：ARCO ERA5（匿名，1959-2022 六小时，240×121 等角网格），本仓库现场读取 "
             f"{args.year}-{args.month}。边界：这是 ERA5 的地形，不是真实地形 —— "
             "1.5° 格点装不下高原的真实起伏，故这些比例是「ERA5 怎么表示高原」的陈述，"
             "这正是向 ERA5 或同量级网格提问时该用的那一句。「地下」的判据是 p < 该层气压，"
             "右侧面板另给了不依赖阈值的说法（位势差 < 0）。")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    Path(args.json).write_text(json.dumps({
        "year": args.year, "month": args.month,
        "plateau_box": PLATEAU, "cells": int(m_pl.sum()),
        "surface_pressure_median_hpa": float(np.median(pl)),
        "surface_pressure_p10_p90": [float(np.percentile(pl, 10)),
                                     float(np.percentile(pl, 90))],
        "elevation_median_m": float(np.median(el)),
        "underground_frac": {str(k): v for k, v in frac.items()},
        "level_height_above_ground_m": {str(k): v for k, v in heights.items()},
        "warmpool_surface_pressure_median_hpa": float(np.median(wp)),
        "warmpool_underground_frac_850": wp_frac,
    }, indent=1, ensure_ascii=False))
    print(f"\n  写入 {out} 和 {args.json}")
    return 0 if control_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
