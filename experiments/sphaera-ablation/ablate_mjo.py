"""把消融的目标从 Niño3.4 换成 MJO 指标 —— 其余完全不动。

指标怎么来的，以及它不是什么
----------------------------
RMM 的构造是：赤道带平均的 **OLR + 850 hPa 纬向风 + 200 hPa 纬向风** 的**联合 EOF**，
取前两个主成分。我们的资料里**没有 OLR**，但有 u850 与 u250，所以：

    PC = 赤道带 (15S–15N) 平均的 [u850', u250'] 联合 EOF 的前两个主成分

**这是 RMM 的【风场部分】，不是 RMM 本身。** 少了 OLR 那一支，对流中心的定位会差。
**而且月平均会滤掉 30–90 天频带的大部分** —— 留下的是 MJO 的**活动包络**，
不是它的相位。故本件问的是「月度 MJO 活动是否可从热带外采样预测」，
**不是**「能否预测 MJO 相位」。这两句不可互换。
"""
from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np

SRC = Path.home() / "climatetensor-inputs/ncep-multivariate"
TRAIN_END = 2009


def combined_eof(band=(15, -15), n_pc=2):
    """赤道带 u850 与 u250 的联合 EOF 主成分。"""
    outs = {}
    for code in ("u850", "u250"):
        d = np.load(SRC / f"{code}.npz")
        v, lat = d["values"].astype(float), d["lat"].astype(float)
        m = (lat >= band[1]) & (lat <= band[0])
        assert m.sum(), code
        # 面积权重：cos(lat)
        w = np.cos(np.deg2rad(lat[m]))[:, None]
        b = (v[:, m] * w).reshape(v.shape[0], -1)
        outs[code] = np.nan_to_num(b)
        outs["time"] = d["time"].astype(str)
    X = np.concatenate([outs["u850"], outs["u250"]], axis=1)
    # 去季节，气候态只用训练期
    tim = outs["time"]; mon = np.array([int(m[5:7]) for m in tim])
    trm = np.array([int(m[:4]) for m in tim]) <= TRAIN_END
    Xa = X.copy()
    for mm in range(1, 13):
        s = trm & (mon == mm)
        Xa[mon == mm] -= X[mon == mm][s].mean(axis=0) if False else X[s].mean(axis=0)
    U, S, Vt = np.linalg.svd(Xa, full_matrices=False)
    pcs = U[:, :n_pc] * S[:n_pc]
    var = (S ** 2) / (S ** 2).sum()
    return pcs, var, tim


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--eo", default="runs/tropical/eo-500.npz")
    ap.add_argument("--lead", type=int, default=2)
    args = ap.parse_args()
    eo = np.load(args.eo); E, O, months = eo["E"], eo["O"], eo["months"].astype(str)
    pcs, var, tim = combined_eof()
    assert (tim == months).all(), "PC 与 E/O 月份轴不一致"
    print(f"  联合 EOF 前两个主成分解释方差: {var[0]*100:.1f}% + {var[1]*100:.1f}% = "
          f"{(var[0]+var[1])*100:.1f}%")
    mon = np.array([int(m[5:7]) for m in months]); yr = np.array([int(m[:4]) for m in months])
    k = args.lead; v = np.arange(len(months) - k); trm = yr <= TRAIN_END

    def des(x):
        o = x.copy()
        for mm in range(1, 13):
            s = trm & (mon == mm); o[mon == mm] -= x[s].mean()
        return o
    Ea, Oa = des(E), des(O)
    tr, te = trm[v], ~trm[v]

    print(f"  {'目标':<14}{'M1 E':>9}{'M2 E+O':>10}{'M2-M1':>9}{'M3 E+PC(t)':>12}{'M4':>9}{'M4-M3':>9}")
    rows = []
    for j in range(2):
        pc = des(pcs[:, j]); ya = pc[v + k]; Pa = pc[v]

        def fe(cols):
            X = np.column_stack([np.ones(int(tr.sum()))] + [c[v][tr] for c in cols])
            b = np.linalg.lstsq(X, ya[tr], rcond=None)[0]
            Xt = np.column_stack([np.ones(int(te.sum()))] + [c[v][te] for c in cols])
            p = Xt @ b
            return float(np.corrcoef(p, ya[te])[0, 1])
        m1, m2 = fe([Ea]), fe([Ea, Oa]); m3, m4 = fe([Ea, Pa]), fe([Ea, Oa, Pa])
        print(f"  MJO-PC{j+1:<9}{m1:>9.4f}{m2:>10.4f}{m2-m1:>+9.4f}{m3:>12.4f}{m4:>9.4f}{m4-m3:>+9.4f}")
        rows.append({"target": f"MJO-PC{j+1}", "M1": m1, "M2": m2, "M2-M1": m2 - m1,
                     "M3": m3, "M4": m4, "M4-M3": m4 - m3})
    print()
    print("  对照（同一预测子，目标不同）：")
    print("    Niño3.4  k=2   M2-M1 = +0.1190   M4-M3 = +0.0050")
    Path("runs/tropical/mjo.json").write_text(json.dumps(
        {"lead": k, "train_end": TRAIN_END, "eof_var": list(map(float, var[:2])),
         "rows": rows}, indent=1, ensure_ascii=False))
    print("\n  已写 runs/tropical/mjo.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
