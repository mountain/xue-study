#!/usr/bin/env python3
"""一张表算完所有几何的 E/O 统计与消融。

为什么是脚本而不是 shell：我在这上面栽过两次 —— 内联 heredoc 里的 f-string
不能含反斜杠，且 ssh 单引号里还要再转义一层，结果是「读到一个被截断的字段
当成真值」。写成文件、传过去、只读它的输出，就没有这一层。

用法：python3 parity_report.py
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

# 几何 -> (eo 文件, 节点预设)。`declared` 不在内：它是 sphaera-frame 声明的几何，另一条线。
GEOMS = {
    "tropical": ("runs/tropical/eo-500.npz", "tropical"),
    "dense": ("runs/dense/eo-500.npz", "dense"),
    "north": ("runs/north/eo.npz", "north"),
    "south": ("runs/south/eo.npz", "south"),
    "north32": ("runs/north32/eo.npz", "north32"),
    "paired8": ("runs/paired8/eo.npz", "paired8"),
    # declared 是 sphaera-frame 声明的几何（z = ±3/5, ±4/5）。它的 .adva 未随 run 留存，
    # 故节点数与配对只能从 extract_nodes.py 的 declared 预设读 —— 这一点在输出里标明。
    "northhi": ("runs/northhi/eo.npz", "northhi"),
    # cross 与 declared 共用 |z|=4/5、与 tropical 共用 |z|=5/13，用来把两个环分开
    "cross": ("runs/cross/eo.npz", "cross"),
    "declared": ("runs/declared/eo.npz", "declared"),
}
# 没有 .adva 留存的 run：节点数/配对从 extract_nodes 的预设表取，并标记出来
NO_ADVA = set()
LEADS = (1, 2, 4, 6)
PY = sys.executable


def deseasonalize(v, mon):
    """按【日历月】去季节。

    曾经按整标签 "1979-01" 分组，但 564 个月份互不相同 ⇒ 每组 1 个样本 ⇒ 全 NaN。
    NaN 是脚本错，不是数据的性质。故这里断言结果有限。
    """
    out = v.astype(float).copy()
    for mm in set(mon):
        k = mon == mm
        out[k] -= v[k].mean()
    return out


def ablation(eo_path, lead):
    """跑 ablate.py 并取回 M2−M1 与 M4−M3 的 RMSE Δ。"""
    r = subprocess.run([PY, "ablate.py", "--eo", eo_path, "--lead", str(lead)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None, None
    deltas = [float(m) for m in
              __import__("re").findall(r"RMSE [0-9.]+ → [0-9.]+  \(Δ ([+-][0-9.]+)\)", r.stdout)]
    if len(deltas) < 2:
        return None, None
    return deltas[0], deltas[1]


def main() -> int:
    print("=== E/O 统计（564 月，去季节按日历月） ===")
    print(f"  {'几何':10s} {'节点':>4s} {'配对':>4s} {'E sd':>8s} {'O sd':>8s} "
          f"{'O/E':>6s} {'原始corr':>9s} {'去季节corr':>10s}")
    rows = {}
    for tag, (path, preset) in GEOMS.items():
        p = Path(path)
        if not p.exists():
            print(f"  {tag:10s} 缺 {path}")
            continue
        z = np.load(p)
        E, O, m = z["E"], z["O"], z["months"].astype(str)
        assert len(m) == 564, f"{tag} 月份数 {len(m)} != 564"
        mon = np.array([s[5:7] for s in m])
        Ea, Oa = deseasonalize(E, mon), deseasonalize(O, mon)
        des = np.corrcoef(Ea, Oa)[0, 1]
        assert np.isfinite(des), f"{tag} 去季节相关是 NaN"
        # 节点数与配对从 .adva 读，不从记忆读
        adva = Path(f"runs/{tag}/spectrum-{tag}.adva")
        if adva.exists():
            txt = adva.read_text()
            n_node = len(set(__import__("re").findall(r"\(use (u\d+[xyz])\)", txt))) // 3
            e = [__import__("fractions").Fraction(s)
                 for s in __import__("re").findall(r"\(scale (-?\d+/\d+) \(use e\)\)", txt)]
            paired = any(v < 0 for v in e) and any(v > 0 for v in e)
            src = "程序"
        else:
            import extract_nodes
            n = extract_nodes.nodes(preset)
            n_node = len(n)
            paired = any(z < 0 for _, _, z in n) and any(z > 0 for _, _, z in n)
            src = "预设表(无.adva)"
        rows[tag] = (n_node, paired, des)
        print(f"  {tag:10s} {n_node:4d} {'有' if paired else '无':>4s} {E.std():8.4f} "
              f"{O.std():8.4f} {O.std()/E.std():6.3f} "
              f"{np.corrcoef(E, O)[0,1]:+9.4f} {des:+10.4f}")

    print()
    print("=== 消融：M2−M1 / M4−M3 的 RMSE Δ（负 = O 有增量） ===")
    print(f"  {'几何':10s} " + " ".join(f"{'k='+str(k):>9s}" for k in LEADS)
          + "   | " + " ".join(f"{'k='+str(k):>9s}" for k in LEADS))
    for tag, (path, _) in GEOMS.items():
        if not Path(path).exists():
            continue
        a, b = [], []
        for k in LEADS:
            m2, m4 = ablation(path, k)
            a.append("     —   " if m2 is None else f"{m2:+9.4f}")
            b.append("     —   " if m4 is None else f"{m4:+9.4f}")
        print(f"  {tag:10s} " + " ".join(a) + "   | " + " ".join(b))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
