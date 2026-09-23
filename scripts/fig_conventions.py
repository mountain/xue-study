"""Three systems, one question, three conventions -- and what that costs a reader.

THE QUESTION
------------
"What is the equivalent potential temperature at 850 hPa over the Tibetan
Plateau (80-92E, 26-32N)?"

The plateau's ground sits near 580 hPa.  850 hPa is therefore BELOW the surface
over most of that box, and an isobaric level that is underground is not a place
the atmosphere has a temperature at.  It is a request for an extrapolation.

Three independent systems answer that request three different ways, and this
figure is about the divergence between the answers -- not about which one is
right, because the question has no observational answer to be right about.

    ERA5        gives a value that hugs the ground
    GFS / xue   gives a value extrapolated by a lapse rate, and the published
                poster then clips it at the encoding ceiling
    MERRA-2     refuses: 65.1% of the box is masked, and the mask sits where
                the surface pressure is below 850 hPa (agreement 97.3%)

RECORDED VERSUS OBSERVED HERE
-----------------------------
This repository distinguishes a number read from elsewhere from a number
measured in this repository, and every bar on this figure carries its own tag.
Only the GFS, ECMWF and AIFS rows are recomputed here, from the archived
posters.  The ERA5 and MERRA-2 rows are RECORDED from the report's §2656, whose
own sources are the ARCO ERA5 archive and MERRA-2 M2T1NXSLV.

THE CONTROL IS THE POINT
------------------------
Above the warm pool -- where 850 hPa is genuinely in the free atmosphere and
everyone has real data -- the same three systems agree.  A divergence that
appears only where the level is underground, and vanishes where it is not, is a
statement about the level, not about the physics.

THE COMPARABILITY TRAP
----------------------
MERRA-2's valid-subset mean is 353.81 K and ERA5's box mean is 331.62 K, and
putting those two numbers side by side makes MERRA-2 look like the middle
opinion.  It is not.  MERRA-2's mean is over the 34.86% of cells where the level
is above ground; ERA5's is over the whole box.  The two averages are over
different sets of gridpoints, so the comparison is between two different
questions, and the figure draws that rather than tabulating it away.

Usage:
  uv run --with numpy --with matplotlib python scripts/fig_conventions.py
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
from poster_field import BOXES, load, runs_with                       # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
figstyle.use()

PLATEAU = BOXES["高原 80-92E,26-32N"]
WARMPOOL = BOXES["暖池 120-180E,15S-15N"]

# RECORDED, not measured here.  Each carries the report section it came from,
# because a number that loses its provenance is a number that will be
# re-cited as if it had been measured.
RECORDED = {
    "era5_plateau": (331.6, "63 年九月框内中位", "§2656 表"),
    "era5_warmpool": (338.64, "63 年九月框内中位", "§2656"),
    "merra_mask_frac": (0.6514, "T850 屏蔽比例", "§2656"),
    "merra_mask_agree": (0.973, "屏蔽位置与 PS<850 吻合", "§2656"),
    "merra_valid_mean": (353.81, "有效子集均值", "§2656"),
    "merra_valid_median": (354.25, "有效子集中位", "§2656"),
    "merra_valid_share": (0.3486, "有效子集占框", "§2656"),
    "merra_warmpool": (338.63, "暖池有效子集均值", "§2656"),
    "gfs_plateau_range": ((366.2, 371.3), "高原均值区间（另一处读取）", "§2656 表"),
    "surface_pressure": (582.6, "高原地面气压中位", "§3605"),
    "surface_pressure_merra": (579.7, "MERRA-2 PS 中位", "§2656"),
    "surface_pressure_era5": (582.6, "ERA5 PS 中位", "§2656"),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", default=str(ROOT / "archive"))
    ap.add_argument("--out", default=str(ROOT / "figures" / "conventions.png"))
    ap.add_argument("--json", default=str(ROOT / "figures" / "conventions.json"))
    args = ap.parse_args()
    archive = Path(args.archive)

    # ---- what this repository can measure now -----------------------------
    here = {}
    for coll in ("gfs", "ecmwf", "aifs"):
        items = runs_with(archive, coll, "thetae850")
        if not items:
            continue
        pl, wp = [], []
        for it in items:
            p = load(archive, coll, it, "thetae850")
            pl.append(p.box_stats(*PLATEAU))
            wp.append(p.box_stats(*WARMPOOL))
        here[coll] = {
            "n_runs": len(items),
            "plateau_median": float(np.median([s["median"] for s in pl])),
            "plateau_median_lo": float(min(s["median"] for s in pl)),
            "plateau_median_hi": float(max(s["median"] for s in pl)),
            "plateau_sat": float(np.mean([s["saturated_frac"] for s in pl])),
            "warmpool_median": float(np.median([s["median"] for s in wp])),
            "ceiling": max(s["ceiling"] for s in pl),
        }

    print("本仓库现场重算（archive/ 的 θe850 poster）")
    for coll, d in here.items():
        print(f"  {coll:<7}{d['n_runs']} 次运行  高原框中位 "
              f"{d['plateau_median']:7.1f} K（{d['plateau_median_lo']:.1f}-"
              f"{d['plateau_median_hi']:.1f}）  饱和 {d['plateau_sat']*100:5.1f}%"
              f"  暖池中位 {d['warmpool_median']:7.1f} K")
    ceiling = here["gfs"]["ceiling"]

    print("\nRECORDED（来自报告，未在本步重算）")
    for k, (v, what, src) in RECORDED.items():
        print(f"  {k:<26}{str(v):<18}{what:<24}{src}")

    # The control must be able to fail: if the systems disagreed over the warm
    # pool too, the plateau divergence would say nothing about the level.
    wp_vals = [here[c]["warmpool_median"] for c in here]
    wp_spread = max(wp_vals) - min(wp_vals)
    print(f"\n判据 · 暖池对照：归档三模式暖池中位极差 {wp_spread:.2f} K "
          f"（ERA5 与 MERRA-2 记录的差 {abs(RECORDED['era5_warmpool'][0] - RECORDED['merra_warmpool'][0]):.2f} K）")
    plat_vals = [here[c]["plateau_median"] for c in here]
    print(f"判据 · 高原：归档三模式高原中位极差 {max(plat_vals) - min(plat_vals):.2f} K")
    ok = wp_spread < 3.0 and (max(plat_vals) - min(plat_vals)) > 10.0
    print(f"  注：归档 poster 的暖池中位比 RECORDED 的 ERA5/MERRA-2 暖池值高约 "
          f"{np.mean(wp_vals) - RECORDED['era5_warmpool'][0]:.2f} K —— "
          "不同批次、不同格点，不并入对照")
    print("判定：" + ("对照通过 —— 分歧只出现在层次位于地下的那个框里"
                    if ok else "对照未通过 —— 不得据此讲层次的故事"))

    # ---- figure -----------------------------------------------------------
    fig = plt.figure(figsize=(14.0, 8.2), dpi=140)
    gs = fig.add_gridspec(1, 2, width_ratios=[1.9, 1.0], wspace=0.20,
                          left=0.055, right=0.985, top=0.795, bottom=0.135)

    ax = fig.add_subplot(gs[0, 0])
    rows = [
        ("ERA5", RECORDED["era5_plateau"][0], "RECORDED",
         "给值 · 贴着地面", figstyle.NEUTRAL, None),
        ("ECMWF", here["ecmwf"]["plateau_median"], "本仓库实测",
         f"给值 · 归档 {here['ecmwf']['n_runs']} 次运行中位", "#2b6cb0", None),
        ("AIFS", here["aifs"]["plateau_median"], "本仓库实测",
         f"给值 · 归档 {here['aifs']['n_runs']} 次运行中位", "#2b6cb0", None),
        ("GFS / xue", here["gfs"]["plateau_median"], "本仓库实测",
         f"给值 · 外推后被 {ceiling:.0f} K 上限削平（饱和 {here['gfs']['plateau_sat']*100:.0f}%）",
         figstyle.BAD, "note"),
        ("MERRA-2", None, "RECORDED", "拒绝作答 · 屏蔽两个数之间的那一段",
         figstyle.WARN, (RECORDED["merra_valid_mean"][0],)),
    ]
    y = np.arange(len(rows))[::-1]
    lo_x, hi_x = 318.0, 376.0
    for yi, (name, val, tag, note, colr, extra) in zip(y, rows):
        if val is not None:
            ax.barh(yi, val - lo_x, left=lo_x, height=0.52, color=colr, zorder=3)
            ax.text(val + 0.8, yi, f"{val:.1f} K", va="center", fontsize=10.5,
                    fontweight="bold", color=colr, zorder=5)
        else:
            # MERRA-2's row is not a value: it is a refusal with a shape.  The
            # whole box is drawn, the masked share is hatched out, and the
            # valid-subset mean sits at the far right with a warning not to read
            # it against ERA5's bar.
            ax.barh(yi, hi_x - lo_x, left=lo_x, height=0.52, color="#fdf3dd",
                    edgecolor=figstyle.WARN, lw=1.2, zorder=3)
            mask_w = (hi_x - lo_x) * RECORDED["merra_mask_frac"][0]
            ax.barh(yi, mask_w, left=lo_x, height=0.52, color="none",
                    edgecolor=figstyle.WARN, hatch="////", lw=0.0, zorder=4)
            ax.text(lo_x + mask_w / 2, yi,
                    f"屏蔽 {RECORDED['merra_mask_frac'][0]*100:.1f}%"
                    f"（＝850 hPa 在地下）",
                    ha="center", va="center", fontsize=9.4, color="#7a5a00",
                    zorder=6)
            v = extra[0]
            ax.plot([v], [yi], marker="D", ms=8, color=figstyle.WARN, zorder=7)
            # The value sits INSIDE the row it belongs to, on a boxed label, so
            # it cannot be read as a second bar and cannot collide with the row
            # above.  Its whole point is that it is measured on a different set
            # of gridpoints than the ERA5 bar two rows up.
            ax.text(v - 1.6, yi,
                    f"有效子集（{RECORDED['merra_valid_share'][0]*100:.1f}% 的格点）"
                    f"均值 {v:.2f} K",
                    ha="right", va="center", fontsize=8.4, color="#6b4e00",
                    zorder=8,
                    bbox=dict(facecolor="white", alpha=0.88,
                              edgecolor=figstyle.WARN, lw=0.7, pad=2.2))
        ax.text(lo_x + 0.7, yi - 0.40, note, va="top", fontsize=8.6,
                color=figstyle.DIM, zorder=6)
        ax.text(hi_x - 0.5, yi + 0.30, tag, va="bottom", ha="right",
                fontsize=7.6, zorder=6,
                color=figstyle.OK if tag == "本仓库实测" else figstyle.FAINT)
    ax.axvline(ceiling, color=figstyle.INK, lw=1.3, ls="--", zorder=5)
    ax.text(ceiling - 0.6, len(rows) - 0.42, f"xue 编码上限 {ceiling:.0f} K",
            ha="right", va="top", fontsize=9, color=figstyle.INK)
    # The band that is not a temperature at all.
    ax.axvspan(lo_x, lo_x + (hi_x - lo_x) * 0.0, color="none")
    ax.set_yticks(y)
    ax.set_yticklabels([r[0] for r in rows], fontsize=11)
    ax.set_xlim(lo_x, hi_x)
    ax.set_ylim(-0.95, len(rows) - 0.15)
    ax.set_xlabel("高原框（80-92E, 26-32N）上的 θe850  K", fontsize=10.5)
    ax.set_title("同一个问题：三个系统各选了一种做法", fontsize=12)
    figstyle.tidy(ax, "x")

    ax2 = fig.add_subplot(gs[0, 1])
    # THE CONTROL THAT HOLDS EVERYTHING ELSE FIXED
    # --------------------------------------------
    # Comparing ERA5 against MERRA-2 tests two systems but also two datasets,
    # two date windows and two processing chains.  Comparing the three ARCHIVED
    # runs across two boxes changes exactly one thing -- the region -- so any
    # difference in spread is attributable to the region.
    plat = [here[c]["plateau_median"] for c in ("gfs", "ecmwf", "aifs")]
    warm = [here[c]["warmpool_median"] for c in ("gfs", "ecmwf", "aifs")]
    plat_spread, warm_spread = max(plat) - min(plat), max(warm) - min(warm)
    groups = [("高原框\n80-92E 26-32N", plat, figstyle.BAD),
              ("暖池\n120-180E 15S-15N", warm, figstyle.OK)]
    xs = np.arange(len(groups))
    for x, (lab, vals, colr) in zip(xs, groups):
        for k, v in enumerate(vals):
            ax2.plot([x + (k - 1) * 0.27] * 2, [0, v - 320],
                     color=colr, lw=7, alpha=0.30 + 0.25 * k,
                     solid_capstyle="round", zorder=3)
            ax2.plot([x + (k - 1) * 0.27], [v - 320], marker="o", ms=7,
                     color=colr, zorder=4)
        ax2.annotate("", xy=(x - 0.30, max(vals) - 320),
                     xytext=(x - 0.30, min(vals) - 320),
                     arrowprops=dict(arrowstyle="<->", color=figstyle.INK,
                                     lw=1.3))
        # The spread label goes ABOVE its group, not beside it: beside it, it
        # landed on the warm pool's own value labels.
        ax2.text(x, max(vals) - 320 + 4.5, f"极差 {max(vals) - min(vals):.2f} K",
                 ha="center", va="bottom", fontsize=10, fontweight="bold",
                 color=figstyle.INK,
                 bbox=dict(facecolor="white", alpha=0.9, edgecolor="none",
                           pad=2.5))
        for k, v in enumerate(vals):
            ax2.text(x + (k - 1) * 0.27, v - 320 + 0.9, f"{v:.1f}",
                     ha="center", fontsize=8.2, color=colr)
    ax2.set_xticks(xs)
    ax2.set_xticklabels([g[0] for g in groups], fontsize=10)
    ax2.set_xlim(-0.95, 1.95)
    ax2.set_ylim(0, 50)
    ax2.set_ylabel("θe850 相对 320 K 的偏移  K", fontsize=10)
    ax2.set_title("能失败的对照：同样三次运行，只换区域", fontsize=12)
    figstyle.tidy(ax2)
    figstyle.title(
        fig, "问一个观测上没有定义的量，就会得到三种约定",
        "高原地面气压中位 582.6 hPa（RECORDED，报告 §3605），所以 850 hPa 在高原框大部分格点上位于地下。"
        "ERA5 贴着地面给值，GFS 按递减率外推、再由 357 K 编码上限削平，MERRA-2 直接屏蔽 —— "
        "同样这三次归档运行，换到 850 hPa 真实存在的暖池上，极差只有 1.5 K。")
    figstyle.footer(
        fig, "本仓库实测部分：archive/ 的 gfs/ecmwf/aifs θe850 poster 首帧，现场解码重算（R=RECORDED 者来自报告 §2656，"
             "其源为 ARCO ERA5 与 MERRA-2 M2T1NXSLV，本步未复算）。"
             "两处必须自己踩住的不可比性：(1) MERRA-2 的 353.81 K 是对「850 hPa 在地面之上」的那 "
             f"{RECORDED['merra_valid_share'][0]*100:.2f}% 格点求的，ERA5 的 331.6 K 是对整个框求的 —— 并排放会读成「MERRA-2 居中」，那是假象；"
             "(2) ERA5 是 63 年九月中位、其余是一次分析，时间窗不同；"
             f"(3) 归档 poster 的暖池中位（{min(wp_vals):.1f}–{max(wp_vals):.1f} K）比 RECORDED 的 ERA5/MERRA-2 暖池值"
             f"（{RECORDED['era5_warmpool'][0]:.2f}/{RECORDED['merra_warmpool'][0]:.2f} K）高约 "
             f"{np.mean(wp_vals) - RECORDED['era5_warmpool'][0]:.1f} K —— 跨仪器的比较与右侧的同仪器对照不是同一个量，本图没有合并它们。"
             "任何建立在高原 850 hPa 上的风险指数都继承这套约定。")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    Path(args.json).write_text(json.dumps(
        {"here": here, "recorded": {k: v[0] for k, v in RECORDED.items()}},
        indent=1, ensure_ascii=False))
    print(f"\n  写入 {out} 和 {args.json}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
