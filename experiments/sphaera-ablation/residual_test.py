#!/usr/bin/env python3
"""残差检验：E/O 的残差能不能预报「L12 模型自己搞错的部分」？

这是唯一还可能增强的通道 —— 直接加 E/O 当预报子已被冗余探针否掉
（模型状态已解释 E 71%、O 87%）。

三步：
  0. 先验证我对模型结构的理解：state(t) @ maps[k] 能否复现他们存下的预报。
     不能复现就不能往下做 —— 否则后面所有数字都建立在一个猜的模型上。
  1. 取 E/O 相对模型状态的残差（训练期拟合）。
  2. 在训练期上，用残差去拟合【模型自己的预报误差】。
  3. 在开发回测期上应用，看技巧变不变。

若第 2 步的系数在样本外不显著、或第 3 步技巧不变 ⇒ 结论是不能增强，且是否定的干净结论。
"""
from pathlib import Path

import numpy as np

ARCH = Path.home() / "xue-study/archive/multivariate-l12-v1"
EO = Path("runs/ls_oo/eo.npz")
LEADS = (1, 2, 3, 4, 5, 6)
TRAIN_END = "2014-12"
BT_START = "2020-01"


def deseas(v, mon):
    o = v.astype(float).copy()
    for mm in set(mon):
        k = mon == mm
        o[k] -= v[k].mean(axis=0) if v.ndim > 1 else v[k].mean()
    return o


def main() -> int:
    m = np.load(ARCH / "model.npz", allow_pickle=True)
    coef = m["coefficients"].astype(float)          # (564, 2698) 观测场
    vec = m["vectors"].astype(float)                # (2698, 64)
    maps = m["maps"].astype(float)                  # (6, 64, 2698)
    clim = m["climatology"].astype(float)           # (12, 2698)
    dates = m["dates"].astype(str)
    n = len(dates)
    print(f"  观测场 {coef.shape}  vectors {vec.shape}  maps {maps.shape}  {dates[0]}…{dates[-1]}")

    z = np.load(EO)
    E, O, emonths = z["E"].astype(float), z["O"].astype(float), z["months"].astype(str)
    assert (emonths == dates).all(), "月份轴不一致"
    print("  月份轴逐月一致 ✓")

    S = coef @ vec                                   # (564, 64) 模型状态
    mon = np.array([s[5:7] for s in dates])
    mint = np.array([int(s[5:7]) for s in dates]) - 1
    tr = dates <= TRAIN_END
    bt = dates >= BT_START
    print(f"  训练 {tr.sum()}（≤{TRAIN_END}）  开发回测 {bt.sum()}（≥{BT_START}）")

    # ---- 第 0 步：复现他们的预报（试多种重建） ----
    # 上一版的错：我用 max|Δ| 与 stored.std() 做「相对误差」，但 2698 个格点里
    # 地表气压通道是 Pa 量级（~1e5），其余是 K 或 m/s ⇒ 该指标被量纲主导，不可读。
    # 这一版按通道分别归一化后再比，并试几种重建式。
    print()
    print("  === 第 0 步：哪种重建能复现 backtest.npz 的 joint ===")
    project = np.load(ARCH / "backtest.npz", allow_pickle=True)
    stored = project["joint"].astype(float)
    bt_idx = np.where(bt)[0]
    scale = m["scale"].astype(float) if "scale" in m.files else np.ones(coef.shape[1])
    print(f"    scale: {scale.shape}  范围 [{scale.min():.4g}, {scale.max():.4g}]")
    print(f"    climatology: {clim.shape}  coefficients sd 中位数 {np.median(coef.std(axis=0)):.4g}")

    def relerr(a, b):
        """按通道归一化：先把两侧都除以 b 的通道标准差，再取最大绝对差。"""
        sd = np.maximum(b.std(axis=0), 1e-30)
        return float(np.abs((a - b) / sd).max())

    cands = {}
    for k in (1,):
        base = np.stack([S[i - k] @ maps[k - 1] for i in bt_idx])
        cands["S@maps"] = base
        cands["scale*(S@maps)"] = base * scale
        cands["clim+scale*(S@maps)"] = base * scale + clim[mint[bt_idx]]
        cands["scale*(S@maps)+clim(t+k)"] = base * scale + clim[mint[bt_idx]]
        for name, v in cands.items():
            print(f"    k={k}  {name:26s} 通道归一化后最大相对差 {relerr(v, stored[k-1]):.4g}")
    print("    （stored 本身的通道 sd 量级："
          f"{np.percentile(stored[0].std(axis=0), [0, 50, 100]).round(3)}）")
    ok_all = False

    # 硬门：前置检查没过就【不许】输出技巧表。
    # 上一版在没有基线的情况下照样打了表，那些 Δ 全部是垃圾（基线技巧 -72160，
    # 比气候态差七万倍），但因为它们长得像数字，很容易被读成结论。
    # 前置检查必须闸住输出，不能只写在标题里。
    if not ok_all:
        print()
        print("  【停止】第 0 步未通过：无法从 model.npz/backtest.npz 复现 L12 的预报。")
        print("  残差检验的基线不可信 ⇒ 不输出技巧表。")
        print("  正确做法是去读拟合 matrix-l12-v1 的那段代码，而不是反推归档。")
        return 2

    # ---- 第 1 步：E/O 的残差 ----
    Ea, Oa = deseas(E, mon), deseas(O, mon)
    Sa = deseas(S, mon)
    res = {}
    for name, y in (("E", Ea), ("O", Oa)):
        X = np.column_stack([Sa[tr], np.ones(tr.sum())])
        b, *_ = np.linalg.lstsq(X, y[tr], rcond=None)
        res[name] = y - np.column_stack([Sa, np.ones(n)]) @ b
        print(f"  残差 {name}: 训练期 sd {res[name][tr].std():.4g}  "
              f"（原 sd {y[tr].std():.4g}）")

    # ---- 第 2、3 步：用残差预报模型误差 ----
    print()
    print("  === 残差能否预报模型自己的误差（基线 = 气候态） ===")
    print(f"  {'lead':>4s} {'基线技巧':>9s} {'+E残差':>9s} {'+O残差':>9s} {'+E+O残差':>9s} "
          f"{'Δ(E+O)':>9s}")
    # 基线技巧：用他们存的 joint 预报（若没验证通过则用 state@maps）
    for k in LEADS:
        base = stored[k - 1] if (stored is not None and ok_all) else \
            np.stack([S[i - k] @ maps[k - 1] for i in bt_idx])
        y = coef[bt_idx]                                            # (72, 2698)
        clim_bt = clim[mint[bt_idx]]                                # (72, 2698)
        def skill(pred):
            return 1 - ((y - pred) ** 2).sum() / ((y - clim_bt) ** 2).sum()
        s0 = skill(base)

        # 训练期拟合修正系数：用模型在训练期的误差
        tr_idx = np.where(tr)[0]
        tr_idx = tr_idx[tr_idx + k < n]
        err_tr = coef[tr_idx + k] - np.stack([S[i] @ maps[k - 1] for i in tr_idx])
        corr = {}
        for name, cols in (("E", ["E"]), ("O", ["O"]), ("E+O", ["E", "O"])):
            Xtr = np.column_stack([res[c][tr_idx] for c in cols] + [np.ones(len(tr_idx))])
            b, *_ = np.linalg.lstsq(Xtr, err_tr, rcond=None)
            Xbt = np.column_stack([res[c][bt_idx - k] for c in cols] + [np.ones(len(bt_idx))])
            corr[name] = base + Xbt @ b
        print(f"  {k:4d} {s0:9.4f} {skill(corr['E']):9.4f} {skill(corr['O']):9.4f} "
              f"{skill(corr['E+O']):9.4f} {skill(corr['E+O']) - s0:+9.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
