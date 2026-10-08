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

    mon = np.array([s[5:7] for s in dates])
    mint = np.array([int(s[5:7]) for s in dates]) - 1
    tr = dates <= TRAIN_END
    bt = dates >= BT_START
    print(f"  训练 {tr.sum()}（≤{TRAIN_END}）  开发回测 {bt.sum()}（≥{BT_START}）")

    # ---- 第 0 步：按 model.py 里的真实公式复现 ----
    # 前几版全错在这一点上：predict() 吃的是【编码后】的状态
    #     encode(c, months) = (c - climatology[months]) / scale
    #     predict(x, targets, vectors, maps)[k-1] = (x[targets-k] @ vectors) @ maps[k-1]
    #     decode(x, months) = x * scale + climatology[months]
    # 我一直用原始场 coef @ vec，既没 encode 也没 decode。
    print()
    print("  === 第 0 步：按 model.py 的公式复现 backtest.npz ===")
    project = np.load(ARCH / "backtest.npz", allow_pickle=True)
    stored = project["joint"].astype(float)
    bt_idx = np.where(bt)[0]
    scale = m["scale"].astype(float)
    assert scale.shape == (coef.shape[1],), scale.shape
    print(f"    scale: 范围 [{scale.min():.4g}, {scale.max():.4g}]"
          f"  coefficients sd 中位数 {np.median(coef.std(axis=0)):.4g}")
    x_enc = (coef - clim[mint]) / scale                     # 编码态
    print(f"    编码态 x: {x_enc.shape}  通道 sd 中位数 {np.median(x_enc.std(axis=0)):.4g}")
    print(f"    stored 通道 sd 中位数 {np.median(stored.std(axis=0)):.4g}")

    ok_all = True
    for k in LEADS:
        enc = np.stack([(x_enc[i - k] @ vec) @ maps[k - 1] for i in bt_idx])
        # backtest.npz 存的是【解码后】的预报（train.py: physical = state.decode(p, months[test])），
        # 而 maps 是编码 -> 编码。所以还差一步 decode，用【目标月】的气候态。
        mine = enc * scale + clim[mint[bt_idx]]
        d = np.abs(mine - stored[k - 1]).max()
        ref = max(np.abs(stored[k - 1]).max(), 1e-30)
        rel = d / ref
        flag = "一致" if rel < 1e-9 else ("接近" if rel < 1e-3 else "**不一致**")
        ok_all &= rel < 1e-6
        print(f"    k={k}: 最大绝对差 {d:.4g}  相对 stored 峰值 {rel:.3g}  {flag}")

    # 硬门：前置检查没过就【不许】输出技巧表。
    if not ok_all:
        print()
        print("  【停止】第 0 步未通过：无法从 model.npz/backtest.npz 复现 L12 的预报。")
        print("  残差检验的基线不可信 ⇒ 不输出技巧表。")
        return 2
    print("    ⇒ 结构理解验证通过（预测公式与归档逐点一致）")

    S = x_enc @ vec                                  # (564, 64) 编码态的投影

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
        # 全程在【编码空间】里比：train.py 的 aggregate 用的就是 x[test]，
        # 而 backtest.npz 存的是解码后的 physical。上一版混了两个空间，
        # 于是基线技巧成了 -1.3e9 —— 又一个「看起来像数字」的垃圾值。
        base = np.stack([(x_enc[i - k] @ vec) @ maps[k - 1] for i in bt_idx])
        y = x_enc[bt_idx]
        def skill(pred):
            # 编码空间的气候态恒为 0（encode 已减掉了 climatology）
            return 1 - ((y - pred) ** 2).sum() / (y ** 2).sum()
        s0 = skill(base)

        # 训练期拟合修正系数：用模型在训练期的误差
        tr_idx = np.where(tr)[0]
        tr_idx = tr_idx[tr_idx + k < n]
        err_tr = x_enc[tr_idx + k] - np.stack([(x_enc[i] @ vec) @ maps[k - 1]
                                               for i in tr_idx])
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
