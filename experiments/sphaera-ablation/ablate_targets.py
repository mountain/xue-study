"""把同一个消融套到多个目标上：O 的增量是不是只在 Niño3.4 上出现（或只在海温上）。

目标选取原则
------------
热带几何采样的是 ±22.62° 与 ±36.87° 的切向风。故目标应落在**采样能看见的纬度带**里。
- 高原框 28–36N / 80–100E 正好落在带内，而且是**本项目自己的对象**（地面气压）。
- 再取几个环流量与地面量作对照。

每个通道用**它自己的** lat/lon（本项目栽过「拿一个源的掩膜套另一个源」的坑）。
"""
from __future__ import annotations
import argparse, json, re, subprocess, sys
from pathlib import Path
import numpy as np

PY = str(Path.home() / "climatetensor-env/bin/python")
SRC = Path.home() / "climatetensor-inputs/ncep-multivariate"
TRAIN_END = 2009

# 通道 -> (区域框 south,north,west,east 或 None=全球)
TARGETS = {
    "sp   高原 28-36N/80-100E":  ("sp",   (28, 36, 80, 100)),
    "t2m  高原 28-36N/80-100E":  ("t2m",  (28, 36, 80, 100)),
    "z500 高原 28-36N/80-100E":  ("z500", (28, 36, 80, 100)),
    "msl  高原 28-36N/80-100E":  ("msl",  (28, 36, 80, 100)),
    "sp   全球":                 ("sp",   None),
    "z500 全球":                 ("z500", None),
}


def series(code, box):
    d = np.load(SRC / f"{code}.npz")
    v, lat, lon = d["values"].astype(float), d["lat"].astype(float), d["lon"].astype(float)
    if box is None:
        s = np.nanmean(v.reshape(v.shape[0], -1), axis=1)
    else:
        s_, n_, w_, e_ = box
        mla = (lat >= s_) & (lat <= n_)
        mlo = (lon >= w_) & (lon <= e_)
        assert mla.sum() and mlo.sum(), (code, box, mla.sum(), mlo.sum())
        b = v[:, mla][:, :, mlo]
        s = np.nanmean(b.reshape(b.shape[0], -1), axis=1)
    return s, d["time"].astype(str), (lat, lon, box)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--eo", default="runs/tropical/eo-500.npz")
    ap.add_argument("--lead", type=int, default=2)
    args = ap.parse_args()
    eo = np.load(args.eo)
    E, O, months = eo["E"], eo["O"], eo["months"].astype(str)
    mon_all = np.array([int(m[5:7]) for m in months])
    yr_all = np.array([int(m[:4]) for m in months])

    print(f"  预测子：{args.eo}   k={args.lead}   训练 ≤ {TRAIN_END}")
    print(f"  {'目标':<28}{'M1 E':>9}{'M2 E+O':>10}{'M2-M1':>9}{'M3 E+SST':>10}{'M4':>9}{'M4-M3':>9}")
    rows = []
    for name, (code, box) in TARGETS.items():
        y_all, tim, _ = series(code, box)
        assert (tim == months).all(), f"{code} 月份轴不一致"
        k = args.lead
        v = np.arange(len(y_all) - k)
        trm_all = yr_all <= TRAIN_END

        def des(x):
            o = x.copy()
            for m in range(1, 13):
                s = trm_all & (mon_all == m)
                o[mon_all == m] -= x[s].mean()
            return o
        # 去季节在【全长】上做，之后才取子集 —— 否则掩膜长度对不上。
        yda = des(y_all)
        Ea, Oa = des(E), des(O)
        ya = yda[v + k]
        tr, te = trm_all[v], ~trm_all[v]

        def fe(cols):
            X = np.column_stack([np.ones(int(tr.sum()))] + [c[v][tr] for c in cols])
            b = np.linalg.lstsq(X, ya[tr], rcond=None)[0]
            Xt = np.column_stack([np.ones(int(te.sum()))] + [c[v][te] for c in cols])
            p = Xt @ b
            return float(np.corrcoef(p, ya[te])[0, 1])
        m1, m2 = fe([Ea]), fe([Ea, Oa])
        # 持续性基线：目标自身在 t 时刻的值。用【全长】去季节后的序列再取子集。
        Pa = yda[v]
        m3 = fe([Ea, Pa]); m4 = fe([Ea, Oa, Pa])
        print(f"  {name:<28}{m1:>9.4f}{m2:>10.4f}{m2-m1:>+9.4f}{m3:>10.4f}{m4:>9.4f}{m4-m3:>+9.4f}")
        rows.append({"target": name, "code": code, "box": box, "M1": m1, "M2": m2,
                     "M2_minus_M1": m2 - m1, "M3": m3, "M4": m4, "M4_minus_M3": m4 - m3})
    Path("runs/tropical/targets.json").write_text(json.dumps(
        {"eo": args.eo, "lead": args.lead, "train_end": TRAIN_END, "rows": rows},
        indent=1, ensure_ascii=False))
    print("\n  已写 runs/tropical/targets.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
