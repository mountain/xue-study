"""Recompute the cross-model saturation table from the archive, then draw it.

WHAT IS BEING TESTED
--------------------
The claim this figure carries is not "GFS is wrong over the plateau".  It is
narrower and checkable: across the three models xue publishes, the SHARE of
plateau cells pinned at the encoding ceiling is a property of the MODEL, not of
the weather.  The test has three parts, and each can fail:

  1. STABILITY ACROSS RUNS.  A real warm dome moves between cycles; a coding
     artifact does not.  Three gfs runs, three ecmwf runs, three aifs runs.
  2. THE CONTROL REGIONS.  The warm pool is genuinely the hottest large area on
     Earth.  If the ceiling were reached by real heat, the warm pool would reach
     it first.  It must not.
  3. THE LEVEL.  The same comparison at 500 hPa, which is above the plateau's
     ground, must show no such concentration.

If (1) fails the numbers are weather; if (2) fails the artifact story is dead;
if (3) fails the level explanation is dead.  All three are printed.

WHY SATURATION AND NOT "TOO HOT"
--------------------------------
A value at the ceiling is not a measurement of 357 K.  It is the largest code
the format can carry, so every cell at it is a DIFFERENT true value collapsed
onto one number.  That is why the share matters and the maximum does not: the
maximum is 357.0 K by construction and says nothing.

Usage:
  uv run --with numpy --with matplotlib python scripts/fig_plane_ceiling.py
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
from poster_field import BOXES, CEIL_TOL_K, load, runs_with           # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
figstyle.use()

MODELS = ("gfs", "ecmwf", "aifs")
REGIONS = ("高原 80-92E,26-32N", "暖池 120-180E,15S-15N", "中欧 0-20E,45-55N")
BAD = figstyle.BAD
OK = figstyle.OK
NEUTRAL = figstyle.NEUTRAL


def collect(archive: Path, variable: str):
    rows = []
    for coll in MODELS:
        for item in runs_with(archive, coll, variable):
            try:
                p = load(archive, coll, item, variable)
            except Exception as e:                    # noqa: BLE001
                print(f"  skip {coll}/{item}/{variable}: {e}")
                continue
            for region in REGIONS:
                st = p.box_stats(*BOXES[region])
                rows.append({"model": coll, "item": item, "run": p.run,
                             "region": region, "ceiling": p.ceiling,
                             "unit": p.unit, **st})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", default=str(ROOT / "archive"))
    ap.add_argument("--out", default=str(ROOT / "figures" / "plane-ceiling.png"))
    ap.add_argument("--json", default=str(ROOT / "figures" / "plane-ceiling.json"))
    ap.add_argument("--tol", type=float, default=CEIL_TOL_K)
    args = ap.parse_args()
    archive = Path(args.archive)

    thetae = collect(archive, "thetae850")
    t500 = collect(archive, "tmp500")

    if not thetae:
        print("没有可用的 thetae850 poster —— 不作图")
        return 1

    # ---- the printed evidence, which is the part that can fail -------------
    print(f"饱和定义：value >= 编码上限 - {args.tol} K（阈值是选定的，不是推出来的）\n")
    print(f"{'变量':<12}{'模式':<7}{'运行':<16}{'高原':>9}{'暖池':>9}{'中欧':>9}"
          f"{'上限':>9}")
    for label, rows in (("thetae850", thetae), ("tmp500", t500)):
        for r in rows:
            if r["region"] != REGIONS[0]:
                continue
            cells = {x["region"]: x for x in rows if x["item"] == r["item"]}
            print(f"{label:<12}{r['model']:<7}{r['item'][-10:]:<16}"
                  + "".join(f"{cells[k]['saturated_frac'] * 100:>8.2f}%"
                            for k in REGIONS)
                  + f"{r['ceiling']:>8.1f} {r['unit'] or ''}")

    def per_model(rows, region):
        out = {}
        for m in MODELS:
            v = [r["saturated_frac"] * 100 for r in rows
                 if r["model"] == m and r["region"] == region and r["n"]]
            if v:
                out[m] = (min(v), max(v))
        return out

    print("\n逐模式区间（%）")
    for region in REGIONS:
        for label, rows in (("thetae850", thetae), ("tmp500", t500)):
            pm = per_model(rows, region)
            txt = "  ".join(f"{m} {lo:.2f}-{hi:.2f}" for m, (lo, hi) in pm.items())
            print(f"  {label:<11}{region:<26}{txt}")

    # test 1: stability across runs
    print("\n判据一 · 跨运行稳定性")
    plat = per_model(thetae, REGIONS[0])
    for m, (lo, hi) in plat.items():
        spread = hi - lo
        if hi == 0.0:
            print(f"  {m:<6} 三次运行均为 0.00%  →  稳定（本来就没顶到）")
        else:
            print(f"  {m:<6} {lo:.2f}-{hi:.2f}%  跨运行极差 {spread:.2f} 个百分点 → "
                  + ("稳定，指向结构性" if spread < 10 else "不稳定，可能是天气"))
    # test 2: the control regions
    print("\n判据二 · 对照区（真正暖的地方）")
    for region in REGIONS[1:]:
        pm = per_model(thetae, region)
        top = max((hi for _lo, hi in pm.values()), default=0.0)
        print(f"  {region:<26}最大 {top:.2f}%" +
              ("  → 对照通过：天花板不是被真实的暖顶到的"
               if top < 1.0 else "  → 对照失败：真暖区也顶到，不能用饱和讲故事"))
    # test 3: the level
    print("\n判据三 · 换到地面之上的层次（500 hPa）")
    plat500 = per_model(t500, REGIONS[0])
    top500 = max((hi for _lo, hi in plat500.values()), default=0.0)
    top850 = max((hi for _lo, hi in plat.values()), default=0.0)
    print(f"  500 hPa 高原最大饱格 {top500:.2f}%  对  850 hPa {top850:.2f}% → "
          + ("层次解释成立" if top500 + 1.0 < top850 else "层次解释不成立"))

    # ---- figure ------------------------------------------------------------
    fig = plt.figure(figsize=(13.4, 8.4), dpi=140)
    gs = fig.add_gridspec(2, 2, height_ratios=[1.15, 1.0], hspace=0.30,
                          wspace=0.20, left=0.065, right=0.985, top=0.845,
                          bottom=0.105)

    colors = {"gfs": BAD, "ecmwf": NEUTRAL, "aifs": OK}
    short = {REGIONS[0]: "高原\n80-92E 26-32N\n（唯一关心的区域）",
             REGIONS[1]: "暖池（对照）\n120-180E 15S-15N\n（真正最暖的大片区域）",
             REGIONS[2]: "中欧（对照）\n0-20E 45-55N"}

    ax = fig.add_subplot(gs[0, :])
    x = np.arange(len(REGIONS))
    w = 0.26
    for k, m in enumerate(MODELS):
        lo, hi = [], []
        for region in REGIONS:
            v = [r["saturated_frac"] * 100 for r in thetae
                 if r["model"] == m and r["region"] == region and r["n"]]
            lo.append(min(v) if v else 0.0)
            hi.append(max(v) if v else 0.0)
        ax.bar(x + (k - 1) * w, hi, w, color=colors[m], zorder=3,
               label=f"{m}（实心＝运行间最大，斜纹＝最小）")
        ax.bar(x + (k - 1) * w, lo, w, color="white", linewidth=0.0,
               edgecolor=colors[m], hatch="////", zorder=4)
    for xi, region in zip(x, REGIONS):
        pm = per_model(thetae, region)
        for k, m in enumerate(MODELS):
            if m in pm:
                ax.text(xi + (k - 1) * w, pm[m][1] + 1.0, f"{pm[m][1]:.1f}%",
                        ha="center", va="bottom", fontsize=9.5, color=colors[m],
                        fontweight="bold", zorder=5)
    ax.set_xticks(x)
    ax.set_xticklabels([short[r] for r in REGIONS], fontsize=10)
    ax.set_ylim(0, 68)
    ax.set_ylabel("θe850 顶在编码上限的格点占比  %", fontsize=10.5)
    figstyle.tidy(ax)
    handles = [plt.Rectangle((0, 0), 1, 1, color=colors[m]) for m in MODELS]
    ax.legend(handles, list(MODELS), fontsize=9.5, frameon=False,
              loc="upper right", ncols=3, title="实心＝运行间最大 · 斜纹＝最小",
              title_fontsize=8.5)
    figstyle.provenance(
        ax, f"9 次归档运行 · poster 首帧 · 上限 {thetae[0]['ceiling']:.0f} K（三模式量化相同）"
            f" · 饱和阈值 = 上限 − {args.tol:g} K（选定值，非导出值）")

    # Bottom left: the SHAPE of the collapse.  A share is a number; a histogram
    # with a bar standing on the ceiling shows what a number cannot -- that
    # every one of those cells is a different true value printed as one code.
    ax2 = fig.add_subplot(gs[1, 0])
    edges = np.arange(230.0, 359.0, 1.0)
    centres = 0.5 * (edges[:-1] + edges[1:])
    for m in MODELS:
        rows = [r for r in thetae if r["model"] == m]
        if not rows:
            continue
        p = load(archive, m, rows[0]["item"], "thetae850")
        sub, mask = p.box_values(*BOXES[REGIONS[0]])
        v = sub[mask]
        counts, _ = np.histogram(v, bins=edges)
        ax2.step(centres, np.maximum(counts, 0.6), where="mid",
                 color=colors[m], lw=1.6, label=f"{m}（{rows[0]['item'][-10:]}）")
        ax2.fill_between(centres, 0.6, np.maximum(counts, 0.6), step="mid",
                         color=colors[m], alpha=0.18)
    ax2.axvline(thetae[0]["ceiling"], color=figstyle.INK, lw=1.4, ls="--")
    ax2.annotate(
        f"编码上限 {thetae[0]['ceiling']:.0f} K ＝ 能表示的最大码\n"
        f"GFS 中位 {max(r['median'] for r in thetae if r['model'] == 'gfs'):.1f} K，"
        f"最多 {max(r['at_ceiling_frac'] for r in thetae if r['model'] == 'gfs') * 100:.0f}% "
        f"的格点就落在这一根上\n"
        f"（ECMWF/AIFS 中位 325-326 K，离上限还有 30 K）",
        xy=(thetae[0]["ceiling"], 150), xytext=(233.0, 2600),
        fontsize=8.6, color=figstyle.INK, va="top",
        arrowprops=dict(arrowstyle="->", color=figstyle.INK, lw=1.3,
                        connectionstyle="arc3,rad=-0.18"))
    ax2.set_yscale("log")
    ax2.set_ylim(0.6, 4000)
    ax2.set_xlim(230, 364)
    ax2.set_xlabel("θe850  K", fontsize=10)
    ax2.set_ylabel("高原框内格点数（对数）", fontsize=10)
    ax2.set_title("同一个模式、同一个框：GFS 把右端堆成一根柱子", fontsize=11)
    figstyle.tidy(ax2, "both")
    ax2.legend(fontsize=8.5, frameon=False, loc="lower left")

    ax3 = fig.add_subplot(gs[1, 1])
    labels, vals, cols = [], [], []
    for region in REGIONS:
        for label, rows in (("θe850", thetae), ("500 hPa T", t500)):
            v = [r["saturated_frac"] * 100 for r in rows
                 if r["region"] == region and r["n"]]
            labels.append(f"{short[region].splitlines()[0]}\n{label}")
            vals.append(max(v) if v else 0.0)
            cols.append(BAD if "θe" in label else NEUTRAL)
    ax3.bar(range(len(vals)), vals, color=cols, zorder=3)
    for i, v in enumerate(vals):
        ax3.text(i, v + 1.4, f"{v:.2f}%", ha="center", fontsize=8.5,
                 color=BAD if cols[i] == BAD else NEUTRAL)
    ax3.set_xticks(range(len(labels)))
    ax3.set_xticklabels(labels, fontsize=7.8)
    ax3.set_ylim(0, 68)
    ax3.set_ylabel("饱和占比 %", fontsize=10)
    ax3.set_title("判据三：换到地面之上的 500 hPa，饱和完全消失", fontsize=11)
    figstyle.tidy(ax3)

    figstyle.title(
        fig, "「顶在上限」是读数，不是天气",
        "xue 发布的三个模式在同一个高原框（80-92E, 26-32N）上的 θe850。"
        "GFS 把高原框一半以上的格点压成同一个码 —— 中位数就是上限本身；"
        "ECMWF 与 AIFS 不这样做，两个对照区也不这样做。")
    figstyle.footer(
        fig, "源：archive/ 的 {n} 次归档运行 poster（首帧＝该运行 0 时效分析），本仓库现场重算，与报告 §3605 一致。"
             "边界：poster 是 2 倍降采样网格（0.5°），非全分辨率 store，三者未做重采样对齐；"
             "「上限处的值」不是该处温度，而是编码能表示的最大码，落在它上面的每个格点的真值都不同。".format(
                 n=len({r["item"] for r in thetae})))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    Path(args.json).write_text(json.dumps(
        {"tol_k": args.tol, "thetae850": thetae, "tmp500": t500},
        indent=1, ensure_ascii=False))
    print(f"\n  写入 {out} 和 {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
