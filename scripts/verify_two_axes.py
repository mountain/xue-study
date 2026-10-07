"""独立复核：记账轴与技能轴是否真的不同向（E1b 的主结论）。

为什么要有这一件
----------------
E1b 的判定是 `skill_has_interior_optimum` —— 技能轴有内部极大，因此 E1 的
记账判据是错误的代理，「越细越省 ⇒ 越细越好」不成立。这是这五天里最重的一条结论，
而它**由产出它的同一套代码算出**。

本件不重跑，只读冻结读数（`evidence/` 下两份 `report.json`），
并且**刻意不复用 E1b 报告里的 `two_axes` 那一节** ——
那一节是 E1b 自己做的对比，重读它等于自证。这里从逐阶、逐通道的原始数重算。

本件额外做一件 E1b 没做的事：**问那个「内部极大」是否只是噪声。**
E1b 自己登记了限度「d≥8 之后各阶相对差在 1–6% 量级」「内部极大是很浅的」——
那么 d=16 高于 d=20 这件事，究竟是信号还是抖动？

判据（写在跑之前）
------------------
  记账轴单调递减           → 与 E1 一致
  技能轴非单调且 argmax 内部 → 与 E1b 一致
  两轴方向相反             → 主结论复现
  配对检验（逐通道）：d=16 与 d=20 的技巧差在 13 条通道上**符号一致**
                           → 内部极大不是噪声
                           → 若符号混杂，则「内部极大」不可分辨，
                             主结论要降级为「技能轴非单调，但峰值位置不可辨」
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
E1 = ROOT / "evidence/vocabulary-accounting-e1-v1/report.json"
E1B = ROOT / "evidence/vocabulary-skill-axis-e1b-v3/report.json"


def monotone_decreasing(xs) -> bool:
    return all(b <= a for a, b in zip(xs, xs[1:]))


def main() -> int:
    e1 = json.loads(E1.read_text())
    e1b = json.loads(E1B.read_text())

    # ---- 记账轴：从 E1 的 ladder_summary 重算，不用 E1b 的 two_axes ----
    led = sorted(e1["ladder_summary"], key=lambda r: r["degree"])
    deg = [r["degree"] for r in led]
    tot = [r["L_total_bits"] for r in led]
    coeff = [r["L_coeff_total_bits"] for r in led]
    resid = [r["L_resid_total_bits"] for r in led]

    print("=== 记账轴（源：E1 ladder_summary，重算）===")
    print(f"  degrees {deg}")
    print(f"  L_total {[f'{v:.3e}' for v in tot]}")
    # 三项自洽：这是 E1 自己的内部一致性，先立住再谈别的
    bad = [d for d, t, c, r in zip(deg, tot, coeff, resid) if abs((c + r) - t) > 1e-6]
    print(f"  L_total == L_coeff + L_resid ：{'✓ 全部成立' if not bad else f'✗ {bad}'}")
    acc_mono = monotone_decreasing(tot)
    print(f"  单调递减：{acc_mono}    argmin = d={deg[tot.index(min(tot))]}")

    # E1b 抄录的记账数与 E1 是否一致（两侧独立成文，值得核）
    if "two_axes" in e1b:
        ta = e1b["two_axes"]
        same = all(abs(a - b) < 1e-3
                   for a, b in zip(ta["L_total_bits"],
                                   [t for d, t in zip(deg, tot) if d in ta["degrees_with_both"]]))
        print(f"  E1b 抄录的 L_total_bits 与 E1 相符：{'✓' if same else '✗'}")

    # ---- 技能轴：从 per_degree 重算 ----
    pd = sorted(e1b["per_degree"], key=lambda r: r["degree"])
    sd = [r["degree"] for r in pd]
    sk = [r["skill_mean"] for r in pd]
    print("\n=== 技能轴（源：E1b per_degree，重算）===")
    for d, s in zip(sd, sk):
        print(f"  d={d:>3}  skill={s:.6f}")
    sk_mono = all(b >= a for a, b in zip(sk, sk[1:]))
    amax = sd[sk.index(max(sk))]
    interior = 0 < sk.index(max(sk)) < len(sk) - 1
    print(f"  单调不减：{sk_mono}    argmax = d={amax}    内部：{interior}")

    print("\n=== 两轴是否同向 ===")
    print(f"  记账轴偏向更细（argmin 在阶梯末端）：{deg[tot.index(min(tot))] == max(deg)}")
    print(f"  技能轴偏向更细（argmax 在阶梯末端）：{amax == max(sd)}")
    disagree = (deg[tot.index(min(tot))] == max(deg)) and (amax != max(sd))
    print(f"  ⇒ 两轴不同向：{'✓ 主结论复现' if disagree else '✗ 未复现'}")

    # ---- 本件的增量：内部极大可分辨吗？ ----
    print("\n=== 内部极大的可分辨性（E1b 未做）===")
    idx16, idx20 = sd.index(16), sd.index(20)
    print(f"  全局：skill(16)={sk[idx16]:.6f}  skill(20)={sk[idx20]:.6f}  "
          f"差 {sk[idx16]-sk[idx20]:+.6f}（相对 {(sk[idx16]-sk[idx20])/sk[idx16]*100:+.2f}%）")

    # 逐通道配对：同一通道在同一条流程下算出的两个阶的技巧
    ch16 = pd[idx16].get("per_channel_skill_mean") or {}
    ch20 = pd[idx20].get("per_channel_skill_mean") or {}
    common = sorted(set(ch16) & set(ch20))
    diffs = [ch16[c] - ch20[c] for c in common]
    pos = sum(1 for v in diffs if v > 0)
    neg = sum(1 for v in diffs if v < 0)
    print(f"  逐通道配对（n={len(common)}）：16 高于 20 的有 {pos} 条，低于的有 {neg} 条")
    if diffs:
        print(f"    差的中位 {statistics.median(diffs):+.6f}   均值 {statistics.mean(diffs):+.6f}"
              f"   sd {statistics.stdev(diffs):.6f}")
        # 符号检验：一致为正才算可分辨
        if neg == 0 and pos >= 10:
            print("    ⇒ 符号一致 ⇒ **内部极大不是噪声**，d=16 的高于 d=20 在通道间普遍成立")
        elif pos > 0 and neg > 0:
            print(f"    ⇒ 符号混杂（{pos} 正 / {neg} 负）⇒ "
                  f"**峰值位置在通道间不一致，不可当作已被确定的最优阶**")
        else:
            print("    ⇒ 符号一致为负 ⇒ 与「16 更高」相反的结论")

    # 逐提前期配对，作为第二个独立角度
    ld16 = pd[idx16].get("skill_by_lead") or []
    ld20 = pd[idx20].get("skill_by_lead") or []
    if ld16 and ld20 and len(ld16) == len(ld20):
        dd = [a - b for a, b in zip(ld16, ld20)]
        print(f"  逐提前期配对（n={len(dd)}）：正 {sum(1 for v in dd if v>0)} / "
              f"负 {sum(1 for v in dd if v<0)}   中位差 {statistics.median(dd):+.6f}")

    print("\n=== 限度的复述（必须与结论同时出现）===")
    print("  · 各阶相对差在 1–6% 量级，d=24 的系数数是 d=12 的 3.7 倍却几乎持平")
    print("  · 因此正确的说法是「8 阶以后是平台加一次浅回撤」，不是「16 是明确的最优阶」")
    print("  · 本件度量的是我们自己的呈现方式，不是对自然的发现")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
