#!/usr/bin/env python3
"""从已有的原生输出里直接量南北不对称 —— 不新增任何求值。

为什么这能量到：单向（只取北半球或只取南半球）节点集让 sign(z) 恒同号，于是
    E = (1/N) Σ sign(z)·c_j  塌缩成  (1/N) Σ c_j —— 就是【该半球的平均切向风】。
所以 north 的 E 是北半球层、south 的 E 是南半球层，两者都是现成的。

对照设计：
  corr(NH1, NH2)  两个【都在北半球】的测度之间的相关 —— 同半球该有多一致
  corr(NH, SH)    跨半球相关 —— 若大气南北对称，它应当和上面一样高
  corr(NH, SH) 远低于 corr(NH1, NH2) ⇒ 南北不对称是【数据里的实体】，不是措辞

再补上与 Niño3.4 的关系，看南北之差是否比任一半球单独更有信息。

内联 f-string 不能含反斜杠（本会话栽过多次），故一律写成文件。
"""
import numpy as np

FILES = {
    "north": "runs/north/eo.npz",        # NH 层，|z|={5/13,12/13,3/5,4/5}，16 节点
    "northhi": "runs/northhi/eo.npz",    # NH 层，|z|={3/5,4/5}，2 环 × 8 方位
    "north32": "runs/north32/eo.npz",    # NH 层，|z| 同 north，4 环 × 8 方位
    "south": "runs/south/eo.npz",        # SH 层，|z| 同 north
}
TRAIN_END = "2000-12"


def deseas(v, mon):
    out = v.astype(float).copy()
    for mm in set(mon):
        k = mon == mm
        out[k] -= v[k].mean()
    return out


def load(tag):
    z = np.load(FILES[tag])
    m = z["months"].astype(str)
    mon = np.array([s[5:7] for s in m])
    return deseas(z["E"], mon), deseas(z["O"], mon), m, mon


def main() -> int:
    E, O, months, mon = {}, {}, None, None
    for tag in FILES:
        E[tag], O[tag], months, mon = load(tag)
    n = len(months)
    assert n == 564
    print(f"  月份 {n}，{months[0]} … {months[-1]}")
    print()
    print("  === 各通道的去季节 sd 与两两相关（E 通道 = 该半球的平均切向风） ===")
    print("      通道        sd      " + "".join(f"{t:>10s}" for t in FILES))
    for a in FILES:
        row = "".join(f"{np.corrcoef(E[a], E[b])[0,1]:+10.4f}" for b in FILES)
        print(f"      E[{a:8s}] {E[a].std():7.4f}  {row}")
    print()
    print("  对照读法：")
    nh = [t for t in FILES if t != "south"]
    within = [np.corrcoef(E[a], E[b])[0, 1] for i, a in enumerate(nh) for b in nh[i+1:]]
    cross = [np.corrcoef(E[t], E["south"])[0, 1] for t in nh]
    print(f"      同半球（NH×NH，{len(within)} 对）相关 {min(within):+.4f} … {max(within):+.4f}，"
          f"均值 {np.mean(within):+.4f}")
    print(f"      跨半球（NH×SH，{len(cross)} 对）相关 {min(cross):+.4f} … {max(cross):+.4f}，"
          f"均值 {np.mean(cross):+.4f}")
    print()
    print("  === 与 Niño3.4 的关系（去季节，训练期气候态） ===")
    from pathlib import Path
    s = np.load(Path.home() / "climatetensor-inputs/ncep-multivariate/sst.npz")
    sst, lat, lon = s["values"].astype(float), s["lat"].astype(float), s["lon"].astype(float)
    mla, mlo = (lat >= -5) & (lat <= 5), (lon >= 190) & (lon <= 240)
    box = sst[:, mla][:, :, mlo]
    n34 = np.nanmean(box.reshape(box.shape[0], -1), axis=1)
    Na = deseas(n34, mon)
    print(f"      Niño3.4 sd（去季节）{Na.std():.4f}")
    for tag in ("north", "northhi", "north32", "south"):
        for k in (1, 2):
            valid = np.arange(n - k)
            r = np.corrcoef(E[tag][valid], Na[valid + k])[0, 1]
            print(f"      corr(E[{tag:8s}], Niño3.4 @k={k}) = {r:+.4f}")
    # 南北之差：E_north - E_south 是真正的「南北对比」
    diff = E["north"] - E["south"]
    print()
    print(f"      E[north] − E[south] 的去季节 sd {diff.std():.4f}"
          f"（两半球各自 sd {E['north'].std():.4f} / {E['south'].std():.4f}）")
    for k in (1, 2):
        valid = np.arange(n - k)
        print(f"      corr(E[north] − E[south], Niño3.4 @k={k}) = "
              f"{np.corrcoef(diff[valid], Na[valid + k])[0,1]:+.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
