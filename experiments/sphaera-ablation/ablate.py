"""消融：新观测通道 O 是否携带 E 之外的信息，关于【两个月后的热带海温】。

设计（三条，写在前）
--------------------
1. **去季节**。E、O、SST 三者都有强季节循环（已实测：E 在 6–8 月最负、O 在 11–1 月最高）。
   不去季节，模型只会学到年循环，消融会变成同义反复。做法：各自减去【训练期】的月气候态。
2. **时序外样本**。训练期只用来定气候态与回归系数，评分只在测试期。气候态也必须
   只用训练期算 —— 否则是把未来信息漏进基线。
3. **嵌套比较**，逐层加：
     M0  ŷ = 0                       （气候态；异常空间里的零）
     M1  ŷ = a·E'
     M2  ŷ = a·E' + b·O'             ← 消融的判据：M2 是否优于 M1
     M3  ŷ = a·E' + c·SST'(t)        （加持续性基线）
     M4  ŷ = a·E' + b·O' + c·SST'(t) ← 加了持续性之后 O 还在不在

   **M2 vs M1 是主判据；M4 vs M3 是「在慢变量基线上是否仍有增量」——后者才是
   `sphaera-frame` 那句「after conditioning on ... slow-variable baselines」。**

   O 与 E 的相关系数是 +0.583，故必须同时报两者的**偏**贡献，不能只看单变量 R²。
"""
from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np

TRAIN_END = "2009-12"      # 训练 1979-01..2009-12（372 月），测试 2010-01..2025-12


def deseasonalize(x, mon, train_mask):
    """减去【训练期】的月气候态。"""
    out = x.copy()
    for m in range(1, 13):
        s = train_mask & (mon == m)
        out[mon == m] -= x[s].mean()
    return out


def ols(X, y):
    return np.linalg.lstsq(X, y, rcond=None)[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--eo", default="runs/run-001/eo.npz")
    ap.add_argument("--inputs", default=str(Path.home() / "climatetensor-inputs/ncep-multivariate"))
    ap.add_argument("--lead", type=int, default=2)
    args = ap.parse_args()

    eo = np.load(args.eo)
    E, O, months = eo["E"], eo["O"], eo["months"].astype(str)
    s = np.load(Path(args.inputs) / "sst.npz")
    sst, lat, lon = s["values"].astype(float), s["lat"].astype(float), s["lon"].astype(float)
    assert (s["time"].astype(str) == months).all(), "SST 与 E/O 的月份轴不一致"

    # Niño 3.4：5S–5N, 190–240E（经度 0–360 约定，故用源自己的 lon）
    mla = (lat >= -5) & (lat <= 5)
    mlo = (lon >= 190) & (lon <= 240)
    assert mla.sum() and mlo.sum(), (mla.sum(), mlo.sum())
    box = sst[:, mla][:, :, mlo]
    n34 = np.nanmean(box.reshape(box.shape[0], -1), axis=1)
    print(f"  Niño 3.4 掩膜 {int(mla.sum())}×{int(mlo.sum())} = {int(mla.sum()*mlo.sum())} 格")
    assert np.isfinite(n34).all(), f"Niño3.4 序列含 NaN：{int((~np.isfinite(n34)).sum())} 个（掩膜内陆地）"
    print(f"  Niño3.4 无 NaN，范围 [{n34.min():.2f}, {n34.max():.2f}] °C")

    mon = np.array([int(m[5:7]) for m in months])
    yr = np.array([int(m[:4]) for m in months])
    train = np.array([m <= TRAIN_END for m in months])

    # 目标：t+lead 的 Niño3.4；可用的 t 到最后 lead 个月之前
    k = args.lead
    valid = np.arange(len(months) - k)
    y = n34[valid + k]
    E0, O0, N0 = E[valid], O[valid], n34[valid]
    monv, trainv = mon[valid], train[valid]

    # 去季节（气候态只用训练期）
    Ea = deseasonalize(E0, monv, trainv)
    Oa = deseasonalize(O0, monv, trainv)
    Na = deseasonalize(N0, monv, trainv)
    ya = deseasonalize(y, monv, trainv)      # 注意：用同一个「月份」标签去季节

    tr, te = trainv, ~trainv
    print(f"  训练 {tr.sum()} 月，测试 {te.sum()} 月；目标 = t+{k} 的 Niño3.4 异常")

    def fit_eval(cols, name):
        X = np.column_stack([np.ones(int(tr.sum()))] + [c[tr] for c in cols]) if cols else np.ones((int(tr.sum()), 1))
        b = ols(X, ya[tr])
        Xt = np.column_stack([np.ones(int(te.sum()))] + [c[te] for c in cols]) if cols else np.ones((int(te.sum()), 1))
        p = Xt @ b
        r = np.corrcoef(p, ya[te])[0, 1]
        rmse = float(np.sqrt(np.mean((p - ya[te]) ** 2)))
        # 与零（气候态）比较
        rmse0 = float(np.sqrt(np.mean(ya[te] ** 2)))
        return {"model": name, "n_par": len(b), "corr": float(r), "rmse": rmse,
                "rmse_clim": rmse0, "skill_vs_clim": 1 - rmse / rmse0}

    rows = [fit_eval([], "M0 气候态"),
            fit_eval([Ea], "M1 E"),
            fit_eval([Ea, Oa], "M2 E+O"),
            fit_eval([Ea, Na], "M3 E+SST"),
            fit_eval([Ea, Oa, Na], "M4 E+O+SST")]

    print(f"\n  {'模型':<16}{'参数':>5}{'test corr':>12}{'test RMSE':>12}{'对气候态技巧':>15}")
    for r in rows:
        print(f"  {r['model']:<16}{r['n_par']:>5}{r['corr']:>12.4f}{r['rmse']:>12.4f}"
              f"{r['skill_vs_clim']:>15.4f}")

    m1, m2 = rows[1], rows[2]
    m3, m4 = rows[3], rows[4]
    print(f"\n  === 主判据 M2−M1（O 在 E 之上的增量）===")
    print(f"    corr {m1['corr']:.4f} → {m2['corr']:.4f}  (Δ {m2['corr']-m1['corr']:+.4f})")
    print(f"    RMSE {m1['rmse']:.4f} → {m2['rmse']:.4f}  (Δ {m2['rmse']-m1['rmse']:+.4f})")
    print(f"  === 次判据 M4−M3（加了持续性之后 O 还在不在）===")
    print(f"    corr {m3['corr']:.4f} → {m4['corr']:.4f}  (Δ {m4['corr']-m3['corr']:+.4f})")
    print(f"    RMSE {m3['rmse']:.4f} → {m4['rmse']:.4f}  (Δ {m4['rmse']-m3['rmse']:+.4f})")

    out = {"lead": k, "train_end": TRAIN_END, "n_train": int(tr.sum()), "n_test": int(te.sum()),
           "target": "ERSSTv5 Nino3.4 (5S-5N, 190-240E), deseasonalized with train-period climatology",
           "rows": rows}
    Path("runs/run-001/ablation.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    np.savez("runs/run-001/ablation.npz", Ea=Ea, Oa=Oa, Na=Na, ya=ya, train=trainv)
    print("\n  已写 runs/run-001/ablation.json 与 ablation.npz")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
