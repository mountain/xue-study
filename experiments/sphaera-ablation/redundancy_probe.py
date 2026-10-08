#!/usr/bin/env python3
"""E/O 是不是已经在 L12 模型自己的状态里？

L12 的状态是 64 维（`vectors` 2698×64 的联合 EOF 基），而它**自己就吃 500 hPa 风的整场**
（`wind500_vectors` 336×64）。我们的 E/O 是同一数据源（NCEP R1 500 hPa 月平均风）
在 64 个海-海配对点上的一个 2 维投影。

⇒ 若 E/O 能被那 64 维状态线性解释得很好，那把它加进去就不可能带来技巧
（模型已经看得见它）。这是【先做】的一步：不做它就去跑回测，等于拿算力赌一个大概率冗余。
"""
import json
from pathlib import Path

import numpy as np

ARCH = Path.home() / "xue-study/archive/multivariate-l12-v1"
EO = Path("runs/ls_oo/eo.npz")


def main() -> int:
    m = np.load(ARCH / "model.npz", allow_pickle=True)
    coef = m["coefficients"]                      # (564, 2698)
    vec = m["vectors"]                            # (2698, 64)
    dates = m["dates"].astype(str)
    print(f"  L12: coefficients {coef.shape}  vectors {vec.shape}  dates {dates[0]}…{dates[-1]}")

    z = np.load(EO)
    E, O, months = z["E"], z["O"], z["months"].astype(str)
    print(f"  ls_oo: E/O 各 {len(E)} 个月  {months[0]}…{months[-1]}")

    assert len(dates) == len(months) == 564, (len(dates), len(months))
    assert (dates == months).all(), "月份轴不一致 —— 不能直接比"
    print("  月份轴逐月一致 ✓")

    # 64 维状态
    state = coef @ vec                            # (564, 64)
    print(f"  64 维状态：{state.shape}  sd 中位数 {np.median(state.std(axis=0)):.4g}")

    # 去季节（按日历月），两边都去 —— 否则季节循环会把 R² 抬到虚高
    mon = np.array([s[5:7] for s in months])
    def deseas(v):
        o = v.astype(float).copy()
        for mm in set(mon):
            k = mon == mm
            o[k] -= v[k].mean(axis=0) if v.ndim > 1 else v[k].mean()
        return o
    S = deseas(state)
    Ea, Oa = deseas(E), deseas(O)

    def r2(y, X):
        X = np.column_stack([X, np.ones(len(X))])
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        resid = y - X @ beta
        return 1 - resid.var() / y.var()

    # 只用训练期拟合，在开发回测期上评（与 skill 报告的分段一致）
    tr = np.array([s <= "2014-12" for s in months])
    te = np.array([s >= "2020-01" for s in months])
    print(f"  训练 {tr.sum()} 个月（≤2014-12）  开发回测 {te.sum()} 个月（≥2020-01）")

    print()
    print("  === E/O 能被模型的 64 维状态解释多少？（训练期拟合，回测期评） ===")
    for name, y in (("E", Ea), ("O", Oa)):
        Xtr, Xte = S[tr], S[te]
        b, *_ = np.linalg.lstsq(np.column_stack([Xtr, np.ones(tr.sum())]), y[tr], rcond=None)
        pred = np.column_stack([Xte, np.ones(te.sum())]) @ b
        r2_te = 1 - ((y[te] - pred) ** 2).sum() / ((y[te] - y[tr].mean()) ** 2).sum()
        print(f"    {name}: 训练期 R² {r2(y[tr], Xtr):.4f}   回测期 R² {r2_te:.4f}")

    # 反向：64 维状态能被 E/O 解释多少（做对比，说明不是单方向的）
    print()
    print("  === 对照：反过来，E/O 能解释多少？（说明方向性） ===")
    # 上一版这里写错了：循环变量 y 根本没用上，设计矩阵写死 [Ea, Oa]，
    # 于是两行打的是同一个数。那个数只能读作「E+O 合起来」。
    for name, cols in (("E", [Ea]), ("O", [Oa]), ("E+O", [Ea, Oa])):
        Xtr = np.column_stack([c[tr] for c in cols] + [np.ones(tr.sum())])
        Xte = np.column_stack([c[te] for c in cols] + [np.ones(te.sum())])
        b, *_ = np.linalg.lstsq(Xtr, S[tr], rcond=None)
        pred = Xte @ b
        ss = ((S[te] - pred) ** 2).sum() / ((S[te] - S[tr].mean(axis=0)) ** 2).sum()
        print(f"    用 {name:4s} 解释 64 维状态：回测期 1-RRSS = {1 - ss:.4f}")

    # 直接看模型自己的 500 风通道与 E/O 的关系
    print()
    print("  === E/O 与模型 wind500 通道（它是整场）的相关 ===")
    cj = json.loads(str(m["channels_json"]))
    print(f"    通道列表: {[c if isinstance(c, str) else c.get('name') for c in cj][:14]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
