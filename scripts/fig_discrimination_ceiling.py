"""Draw the precision ceiling, and draw the correction to it on the same face.

WHY THE CORRECTION IS DRAWN AND NOT DROPPED
-------------------------------------------
The algebra is one line and contains no atmospheric physics:

    a PERFECT ranker flags a fraction a of the population,
    so precision = p/a and recall = 1, where p is the base rate.

That line survives any measurement error, because it is counting.  What did NOT
survive is the number that was substituted for the population.  The first version
of this result used 564 glacier PIXELS x 11 years = 6,204 site-years, and 564
pixels inside a 4.9 km box are not 564 glaciers: `scipy.ndimage.label` resolves
them into 3-4 connected bodies (report sections 3118-3124).  So the honest
population is 33-44 site-years.

Both numbers are drawn, because the difference between them IS the result:
the same detector (PDD, 91% alarm rate) reaches a precision ceiling of 0.018%
under the withdrawn count and 2.5% under the corrected one -- a factor of 140,
with no change in the physics or in the detector.

WHAT NEITHER NUMBER IS
----------------------
Neither 6,204 nor 33-44 is a defensible population.  Fixing a site-year count
requires the RGI/GLIMS boundary to say what "one glacier" is, and this repository
has never obtained that boundary.  So the figure's own verdict is the report's:
the algebra holds, the magnitude does not.  A reader who takes 2.5% away as "the"
ceiling has replaced one unjustified N with another.

The two wider populations (`high mountain asia`, `global`) are order-of-magnitude
guesses carried from `discrimination_ceiling.py`; they are drawn as such and are
NOT measurements of this repository.

Usage:
  uv run --with numpy --with matplotlib python scripts/fig_discrimination_ceiling.py
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

ROOT = Path(__file__).resolve().parents[1]
figstyle.use()

# One verified event: 2026-08-26 Langtang Lirung, 28.2853N 85.5252E (report 3067).
# E enters only as p = E/N, and at E = 1 the estimate is maximally fragile --
# one more event doubles p.  That fragility is a property of the evidence, not of
# the arithmetic, so it is printed rather than hidden.
EVENTS = 1

# The corrected population: 3-4 connected ice bodies in the Langtang 41x41
# neighbourhood, each watched for the 11 years the fixed pixel set supports.
CORRECTED_SITE_YEARS = (3 * 11, 4 * 11)          # 33 .. 44

# The withdrawn population.  Kept in the figure on purpose: it is the count the
# claim was built on, and a correction that erases its own predecessor cannot be
# audited.  `scripts/discrimination_ceiling.py` still carries this value in
# POPULATIONS -- the correction lives in docs/claims.toml, not in that script.
WITHDRAWN_SITE_YEARS = 564 * 11                  # 6,204

# Carried from discrimination_ceiling.py, labelled there as orders of magnitude.
WIDER = {"喜马拉雅（~ 数量级估计）": 100_000 * 11, "全球冰川（~ 数量级估计）": 200_000 * 11}

# Alarm rates measured by this study (report 3048-3051), with the failure each
# one represents.  These are the numbers the ceiling is being asked about.
DETECTORS = (
    ("正积温 PDD", 0.91, "91% 的时间都在触发 —— 饱和即无分辨力"),
    ("雨-冰阈值 50", 0.95, "95% 误报（阈值 275 则 0 命中）"),
)

ALARMS = np.logspace(-6, 0, 400)
TICKS = [1e-6, 1e-5, 1e-4, 1e-3, 1e-2, 1e-1, 1.0]


def precision_curve(n_site_years: float) -> np.ndarray:
    """A perfect ranker's precision at every alarm rate on the grid.

    Clipped at 1.0 because precision is a probability: below a = p the flagged
    set is smaller than the event set, and a perfect ranker simply flags the
    events.  The clip is where the curve's corner comes from, so it is stated
    rather than left to look like saturation of something else.
    """
    return np.minimum(1.0, (EVENTS / n_site_years) / ALARMS)


def check_text_fits(fig, ax, texts) -> None:
    """Refuse to ship a figure whose own labels run off its own axes.

    Numbers cannot catch this.  The first version of this figure printed the
    "half your alarms" label and the 2p annotation on top of each other and both
    past the right frame, and every value in it was right -- which is exactly why
    it is checked by measuring the drawn text, not by looking at the data.
    """
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    box = ax.get_window_extent(renderer)
    over = []
    for t in texts:
        tb = t.get_window_extent(renderer)
        l, r, b, u = box.x0 - tb.x0, tb.x1 - box.x1, box.y0 - tb.y0, tb.y1 - box.y1
        if max(l, r, b, u) > 1.0:                 # 1 px tolerance for hinting
            over.append((t.get_text().splitlines()[0][:28], l, r, b, u))
    if over:
        for txt, l, r, b, u in over:
            print(f"  ✗ 标注越出坐标框 {txt!r}: 左{l:+.0f} 右{r:+.0f} 下{b:+.0f} 上{u:+.0f} px")
        raise SystemExit("有图内标注越出坐标框 —— 拒绝出图（一张被裁掉半个标签的图比没有图更糟）")
    # ... and two labels must not sit on each other.  That is the failure hardest
    # to see in the numbers: two labels on one line read as one label, with a
    # value that is a mixture of both.  This check caught exactly that here.
    boxes = [(t, matplotlib.text.Text.get_window_extent(t, renderer)) for t in texts]
    clashes = []
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a, b = boxes[i][1], boxes[j][1]
            if a.x0 < b.x1 - 1 and b.x0 < a.x1 - 1 and a.y0 < b.y1 - 1 and b.y0 < a.y1 - 1:
                clashes.append((boxes[i][0].get_text().splitlines()[0][:22],
                                boxes[j][0].get_text().splitlines()[0][:22]))
    if clashes:
        for a, b in clashes:
            print(f"  ✗ 两条标注互相压住: {a!r} × {b!r}")
        raise SystemExit("有图内标注重叠 —— 拒绝出图")
    print(f"  自检：{len(texts)} 条图内标注都在坐标框内、且两两不重叠")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "figures" / "discrimination-ceiling.png"))
    ap.add_argument("--json", default=str(ROOT / "figures" / "discrimination-ceiling.json"))
    args = ap.parse_args()

    lo_n, hi_n = CORRECTED_SITE_YEARS
    p_lo, p_hi = EVENTS / hi_n, EVENTS / lo_n     # p is larger for the smaller N
    p_w = EVENTS / WITHDRAWN_SITE_YEARS

    # ---- guards.  Each of these can fail, and each failure means the figure
    # ---- would be making a claim the inputs do not support.
    assert 0 < EVENTS < lo_n, "p would be >= 1: the population is smaller than the event count"
    assert hi_n < WITHDRAWN_SITE_YEARS, \
        "the corrected population must be SMALLER than the withdrawn one; the correction is missing"
    for label, n in (("corrected", lo_n), ("withdrawn", WITHDRAWN_SITE_YEARS), *WIDER.items()):
        p = EVENTS / n
        # Every curve must fall by a = 1.  A population with p >= 1 (fewer
        # site-years than the single event) would draw a flat line at 1.0 --
        # a curve that cannot fail, which this repository has been burned by.
        assert min(1.0, p / ALARMS[-1]) < 1.0, f"{label}: flat at 1 everywhere (p >= a_max)"
    # ... and the frame must be wide enough to show the WHOLE knee ordering: the
    # primary curve saturates inside it, the widest does not.  Both directions
    # are checked, because a frame that shows only one of them is a picture of a
    # different comparison.  (The first version of this guard demanded that EVERY
    # population saturate at a = 1e-6; the order-of-magnitude ones do not, and it
    # fired.  The guard was mis-specified, not the data -- which is the only
    # reason to keep a guard at all.)
    assert min(1.0, p_hi / ALARMS[0]) == 1.0, "primary curve does not saturate inside the frame"
    assert min(1.0, (EVENTS / max(WIDER.values())) / ALARMS[0]) < 1.0, \
        "the widest population also saturates at the left edge: the frame hides the ordering"
    # Precisely the claim under test: at a fixed alarm rate the ceiling must be
    # strictly smaller for a bigger population.  If this fails, the curves are
    # not ordered like the populations and the figure tells a different story
    # than the arithmetic.  Tested at a = 1 (the only rate where nothing is
    # clipped at 1.0) and required merely non-increasing at a = 0.01, where the
    # two corrected curves are both still saturated and legitimately equal.
    ordered = (lo_n, hi_n, WITHDRAWN_SITE_YEARS, *WIDER.values())
    ceilings = [min(1.0, (EVENTS / n) / ALARMS[-1]) for n in ordered]
    assert all(a > b for a, b in zip(ceilings, ceilings[1:])), \
        f"precision ceiling is not monotone in population size at a=1: {ceilings}"
    ceilings_mid = [min(1.0, (EVENTS / n) / 0.01) for n in ordered]
    assert all(a >= b for a, b in zip(ceilings_mid, ceilings_mid[1:])), \
        f"precision ceiling is not monotone at a=0.01: {ceilings_mid}"

    # ---- the printed evidence, which is what the report has to be compared to --
    print(f"已核实事件数 E = {EVENTS}（朗唐 2026-08-26，报告 §3067）"
          f"  —— E=1 时 p 极不稳：再加一个事件就翻倍\n")
    print("报告 §3067 用的 N（已撤回）       : "
          f"{WITHDRAWN_SITE_YEARS:,} 站年    p = 1/{WITHDRAWN_SITE_YEARS:,} = {p_w:.3e}")
    print("报告 §3108 更正后的 N（本图主曲线）: "
          f"{lo_n}-{hi_n} 站年   p = 1/{hi_n}-1/{lo_n} = {p_lo:.3e}-{p_hi:.3e}")
    print("  ⚠ scripts/discrimination_ceiling.py 的 POPULATIONS 仍是 564*11 = 6,204；")
    print("     更正只写进了 docs/claims.toml（claim xue.derived.discrimination-ceiling.v0）。")
    print("     本图以更正为准，并把撤回值画成淡灰虚线，不静默丢弃。\n")

    print(f"  {'报警率 a':>14}" + "".join(
        f"{lab:>26}" for lab in ("更正后 33", "更正后 44", "撤回 6,204", "喜马拉雅~", "全球~")))
    for a in (0.5, 0.1, 0.01, 1e-3, 1e-4, 1e-5, 1e-6):
        row = "".join(f"{min(1.0, (EVENTS/n)/a):>25.4%} " for n in
                      (lo_n, hi_n, WITHDRAWN_SITE_YEARS, *WIDER.values()))
        a_s = f"{a:.0%}" if a >= 0.01 else f"1/{1/a:,.0f}"
        print(f"  {a_s:>14}{row}")

    print("\n要让一半报警是真的（精确率 0.5），报警率必须 ≤ 2p：")
    for label, n in (("更正后 33 站年", lo_n), ("更正后 44 站年", hi_n),
                     ("撤回 6,204 站年", WITHDRAWN_SITE_YEARS),
                     ("喜马拉雅（数量级）", WIDER["喜马拉雅（~ 数量级估计）"]),
                     ("全球（数量级）", WIDER["全球冰川（~ 数量级估计）"])):
        need = 2 * EVENTS / n
        # 2p*N = 2E regardless of N: the COUNT is always 2 and says nothing.
        # What tightens with a bigger population is the RATE.
        print(f"  {label:<22} 2p = {need:.2e}  = 每 {1/need:,.0f} 个站年报一次")

    print("\n=== 两个实测探测器的报警率，与基率之比 ===")
    ratios = {}
    for name, a, note in DETECTORS:
        r_corr = (a * lo_n, a * hi_n)
        r_with = a * WITHDRAWN_SITE_YEARS
        ratios[name] = {"alarm_rate": a, "x_corrected_n": r_corr, "x_withdrawn_n": r_with}
        print(f"  {name:<12} 报警率 {a:.0%}  上限精确率 "
              f"更正后 {min(1.0, p_lo/a):.3%}–{min(1.0, p_hi/a):.3%} / "
              f"撤回 {min(1.0, p_w/a):.3%}")
        print(f"  {'':<12} 是基率的 {r_corr[0]:,.0f}–{r_corr[1]:,.0f} 倍（更正后） / "
              f"{r_with:,.0f} 倍（撤回）   （{note}）")
    print(f"\n  ⚠ 报告 §3081 的「5,646 倍 / 5,894 倍」是**按撤回的 6,204 站年**算的：")
    print(f"     {DETECTORS[0][1]:.0%}×{WITHDRAWN_SITE_YEARS:,} = "
          f"{ratios[DETECTORS[0][0]]['x_withdrawn_n']:,.0f}  "
          f"{DETECTORS[1][1]:.0%}×{WITHDRAWN_SITE_YEARS:,} = "
          f"{ratios[DETECTORS[1][0]]['x_withdrawn_n']:,.0f}  ✅ 与本仓库重算一致")
    print(f"     但按更正后的 33–44 站年，同一对探测器只有 "
          f"{ratios[DETECTORS[0][0]]['x_corrected_n'][0]:,.0f}–"
          f"{ratios[DETECTORS[0][0]]['x_corrected_n'][1]:,.0f} 倍 / "
          f"{ratios[DETECTORS[1][0]]['x_corrected_n'][0]:,.0f}–"
          f"{ratios[DETECTORS[1][0]]['x_corrected_n'][1]:,.0f} 倍。")
    print("     倍数不是探测器的性质，是 N 的性质 —— 而 N 需要一个本仓库没有的冰川边界。")

    # ---- figure -------------------------------------------------------------
    fig = plt.figure(figsize=(13.8, 8.6), dpi=140)
    ax = fig.add_axes((0.075, 0.175, 0.895, 0.615))

    curve_lo = precision_curve(lo_n)
    curve_hi = precision_curve(hi_n)
    ax.fill_between(ALARMS, curve_hi, curve_lo, color=figstyle.NEUTRAL, alpha=0.20, lw=0,
                    zorder=2, label=f"更正后（报告 §3108）：{lo_n}–{hi_n} 站年（3–4 个连通冰体 × 11 年）")
    ax.plot(ALARMS, curve_lo, color=figstyle.NEUTRAL, lw=2.2, zorder=3)
    ax.plot(ALARMS, curve_hi, color=figstyle.NEUTRAL, lw=1.1, ls=(0, (5, 3)), zorder=3)

    ax.plot(ALARMS, precision_curve(WITHDRAWN_SITE_YEARS), color=figstyle.FAINT, lw=2.0,
            ls=(0, (6, 4)), zorder=2,
            label=f"已撤回（报告 §3067）：{WITHDRAWN_SITE_YEARS:,} 站年 ＝ 564 像元 × 11 年 —— 像元不是独立单位")
    t_withdrawn = ax.annotate("撤回的量级：\n把同一冰川上的\n相邻像元当成站点",
                xy=(2.0e-4, 1.0), xytext=(2.4e-6, 0.22), fontsize=8.6, color=figstyle.FAINT,
                va="top", ha="left",
                bbox=dict(facecolor="white", edgecolor="none", alpha=0.85, pad=1.4),
                arrowprops=dict(arrowstyle="->", color=figstyle.FAINT, lw=1.1,
                                connectionstyle="arc3,rad=0.25"))

    for lab, n in WIDER.items():
        ax.plot(ALARMS, precision_curve(n), color=figstyle.FAINT, lw=1.0, ls=":", zorder=1,
                label=f"{lab}：{n:,} 站年（不是本仓库的测量）")

    # The detectors, on both populations.  The vertical error bar is the 33-44
    # spread itself: drawing a single dot would hide the entire correction.
    #
    # 91% and 95% are 0.02 decades apart -- one pixel on a six-decade log axis --
    # so they get ONE callout between them.  Two labels would print on top of
    # each other and be read as a single measurement.
    for i, (name, a, _note) in enumerate(DETECTORS):
        ys = [min(1.0, p_lo / a), min(1.0, p_hi / a)]     # [N=44 edge, N=33 edge]
        half = 0.5 * (ys[1] - ys[0])
        ax.errorbar([a], [0.5 * (ys[0] + ys[1])], yerr=half,
                    fmt="o", ms=8.5, color=figstyle.BAD, ecolor=figstyle.BAD, capsize=4,
                    zorder=6, label="本仓库实测的两个探测器（更正后总体）" if i == 0 else None)
        ax.plot([a], [min(1.0, p_w / a)], "x", ms=8, mew=2.0, color=figstyle.FAINT, zorder=6)
        if i == 0:
            # The callout lives in the corridor between the corrected band and
            # the withdrawn curve: the only empty band on the right half.  It is
            # narrower than the labels want, which is why they are this short.
            t_detect = ax.annotate(
                f"两个实测探测器都落在这里\n（报警率 {DETECTORS[0][1]:.0%} / {DETECTORS[1][1]:.0%}）\n"
                f"上限 {ys[0]:.1%}–{ys[1]:.1%}",
                xy=(a, 0.5 * (ys[0] + ys[1])), xytext=(0.95, 3.2e-3),
                fontsize=8.8, color=figstyle.BAD, va="center", ha="right",
                bbox=dict(facecolor="white", edgecolor="none", alpha=0.85, pad=1.4),
                arrowprops=dict(arrowstyle="->", color=figstyle.BAD, lw=1.4,
                                connectionstyle="arc3,rad=-0.2"))
    # The withdrawn-value markers are the two grey x's; they are named in the
    # legend rather than annotated, because at this scale they coincide with the
    # red dots in x and there is no room for a second callout.
    ax.plot([], [], "x", ms=8, mew=2.0, color=figstyle.FAINT,
            label=f"同两个探测器，按撤回的 6,204 站年（{min(1.0, p_w/DETECTORS[0][1]):.3%} / "
                  f"{min(1.0, p_w/DETECTORS[1][1]):.3%}）")

    # The decision line the whole result exists to state.
    ax.axhline(0.5, color=figstyle.INK, lw=1.3, ls=(0, (4, 3)), zorder=4)
    ax.axvspan(2 * p_lo, 2 * p_hi, color=figstyle.OK, alpha=0.16, lw=0, zorder=1)
    # The label sits just under the line at the far left, past the dotted
    # order-of-magnitude curves it would otherwise print through.  The first
    # version put it at the left end of the line and the 2p annotation -- also
    # placed near the line -- printed straight through it.
    t_half = ax.text(1.3e-6, 0.44, "要让一半报警是真的，报警率必须 ≤ 2p", fontsize=9.6,
            color=figstyle.INK, va="top", ha="left", fontweight="bold",
            bbox=dict(facecolor="white", edgecolor="none", alpha=0.9, pad=1.6), zorder=5)
    t_2p = ax.annotate(
        f"2p = 1/{1/(2*p_hi):.0f}–1/{1/(2*p_lo):.0f} 站年（更正后）\n"
        f"撤回口径 2p = 1/{1/(2*p_w):,.0f}",
        xy=(2 * p_lo, 0.5), xytext=(0.97, 0.60), fontsize=8.8, color=figstyle.OK,
        va="bottom", ha="right", zorder=5,
        bbox=dict(facecolor="white", edgecolor="none", alpha=0.85, pad=1.4),
        arrowprops=dict(arrowstyle="->", color=figstyle.OK, lw=1.4,
                        connectionstyle="arc3,rad=0.18"))


    t_ratio = ax.text(0.021, 1.9e-6,
            "报警率 ÷ 基率（倍数完全由 N 决定）\n"
            f"  正积温 91%：{ratios['正积温 PDD']['x_corrected_n'][0]:.0f}–"
            f"{ratios['正积温 PDD']['x_corrected_n'][1]:.0f} 倍（更正后）"
            f" / {ratios['正积温 PDD']['x_withdrawn_n']:,.0f} 倍（撤回）\n"
            f"  雨-冰 95%：{ratios['雨-冰阈值 50']['x_corrected_n'][0]:.0f}–"
            f"{ratios['雨-冰阈值 50']['x_corrected_n'][1]:.0f} 倍（更正后）"
            f" / {ratios['雨-冰阈值 50']['x_withdrawn_n']:,.0f} 倍（撤回）",
            fontsize=9.0, color=figstyle.INK, va="bottom", ha="left",
            bbox=dict(boxstyle="round,pad=0.45", facecolor="#f4f5f7",
                      edgecolor=figstyle.GRID, linewidth=0.9))

    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlim(1e-6, 1.0)
    ax.set_ylim(1e-6, 2.0)
    ax.set_xticks(TICKS)
    ax.set_xticklabels([f"1/{1/t:,.0f}" if t < 1 else "1（全报）" for t in TICKS], fontsize=9)
    ax.set_yticks(TICKS)
    # Percent all the way down, not percent for the top three and scientific
    # notation below: the y axis is a probability, and switching notation
    # mid-axis makes two decades of one quantity look like two quantities.
    ax.set_yticklabels([f"{t:.0%}" if t >= 0.01 else f"{t * 100:g}%" for t in TICKS],
                       fontsize=9)
    ax.set_xlabel("报警率 a —— 被标出的总体比例（对数轴）", fontsize=10.5)
    ax.set_ylabel("完美排序下的精确率上限  p/a", fontsize=10.5)
    figstyle.tidy(ax, "both")
    ax.legend(fontsize=8.8, frameon=False, loc="lower left", bbox_to_anchor=(0.0, 0.0),
              ncols=1, handlelength=2.4)
    # The "curve is capped at 1.0" sentence lives in this line rather than in a
    # second top-of-axes note: as a note it printed through the 2p block below it.
    figstyle.provenance(
        ax, "p/a 为本仓库现场重算，召回率 = 1（曲线在 a ≤ p 处封顶于 1.0）· "
            "报警率 RECORDED §3048–3051 · E = 1 RECORDED §3067", x=0.005, y=0.995)

    figstyle.title(
        fig, "精确率被基率封顶：代数成立，数量级不成立",
        "上界 = p/a，p 是基率、a 是报警率 —— 这一行不含大气物理，谁的特征都绕不过。"
        "但代入的「总体」站年数在本仓库被更正过：564 个冰川像元实为 3–4 个连通冰体，"
        "站年从 6,204 降到 33–44。同一个探测器（正积温 91%）的上限因此从 0.018% 抬到 2.5%。")
    figstyle.footer(
        fig, "本图重算的是 p/a 的代数（现场计算，scripts/fig_discrimination_ceiling.py），"
             "N = 33–44 取自已更正的 claim（docs/claims.toml，报告 §3108 实测 scipy.ndimage.label："
             "4-邻接 4 个 / 8-邻接 3 个连通体），撤回值 6,204 按报告 §3067 原样画出；"
             "E = 1 与两个探测器的报警率（91%、95%）为 RECORDED，非本图测量。"
             "边界：**代数成立，数量级不成立** —— 33–44 与 6,204 都不是可辩护的总体，"
             "定义「一条冰川」需要 RGI/GLIMS 冰川边界，本仓库至今未取得该数据；"
             "喜马拉雅与全球两条虚线是数量级估计，不得当作本仓库的测量引用。"
             "本图回答的是「完美排序能到多少」，不是任何实际探测器的精确率（后者更低）。")

    check_text_fits(fig, ax, [t_withdrawn, t_detect, t_half, t_2p, t_ratio])
    for ftext in fig.texts:                      # title block and footer, on the figure
        tb = ftext.get_window_extent(fig.canvas.get_renderer())
        fb = fig.bbox
        assert (tb.x0 >= fb.x0 - 1 and tb.x1 <= fb.x1 + 1 and tb.y0 >= fb.y0 - 1), \
            f"figure-level text runs out of the canvas: {ftext.get_text()[:30]!r}"
    print(f"  自检：图级文字（标题/脚注）{len(fig.texts)} 条均在画布内")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    payload = {
        "events": EVENTS,
        "population_corrected_site_years": list(CORRECTED_SITE_YEARS),
        "population_withdrawn_site_years": WITHDRAWN_SITE_YEARS,
        "population_wider": WIDER,
        "base_rate_corrected": [p_lo, p_hi],
        "base_rate_withdrawn": p_w,
        "alarm_rate_for_half_precision": {"corrected": [2 * p_lo, 2 * p_hi], "withdrawn": 2 * p_w},
        "detectors": ratios,
        "curve": {"alarm_rate": ALARMS.tolist(),
                  "precision_corrected_n33": curve_lo.tolist(),
                  "precision_corrected_n44": curve_hi.tolist(),
                  "precision_withdrawn": precision_curve(WITHDRAWN_SITE_YEARS).tolist()},
        "provenance": {
            "recomputed_here": "p/a 的代数与上表所有精确率",
            "recorded": {"E=1": "报告 §3067", "N=33-44": "报告 §3108 / docs/claims.toml",
                         "N=6,204": "报告 §3067（已撤回）",
                         "报警率 91% / 95%": "报告 §3048–3051",
                         "倍数 5,646 / 5,894": "报告 §3081（按撤回的 6,204 站年）"},
            "boundary": "无 RGI/GLIMS 冰川边界；33–44 与 6,204 都不是可辩护的总体。代数成立，数量级不成立。"},
    }
    Path(args.json).write_text(json.dumps(payload, indent=1, ensure_ascii=False))
    print(f"\n  写入 {out} 和 {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
