#!/usr/bin/env python3
"""五个几何的 E/O 统计。去季节按【日历月】分组。

教训：曾按整标签 "1979-01" 分组，但 564 个月份互不相同 ⇒ 每组 1 个样本 ⇒ 全 NaN。
NaN 是脚本错，不是数据的性质。
"""
import numpy as np

FILES = {
    "tropical": "runs/tropical/eo-500.npz",
    "north": "runs/north/eo.npz",
    "south": "runs/south/eo.npz",
    "paired8": "runs/paired8/eo.npz",
}


def deseasonalize(v, mon):
    out = v.astype(float).copy()
    for mm in set(mon):
        k = mon == mm
        out[k] -= v[k].mean()
    return out


def main() -> int:
    hdr = ("几何", "节点", "E sd", "O sd", "O/E", "原始corr", "去季节corr")
    print(f"  {hdr[0]:10s} {hdr[1]:>4s} {hdr[2]:>8s} {hdr[3]:>8s} {hdr[4]:>6s} "
          f"{hdr[5]:>9s} {hdr[6]:>10s}")
    for tag, path in FILES.items():
        z = np.load(path)
        E, O, m = z["E"], z["O"], z["months"].astype(str)
        assert len(m) == 564, f"{tag} 月份数 {len(m)}"
        mon = np.array([s[5:7] for s in m])
        Ea, Oa = deseasonalize(E, mon), deseasonalize(O, mon)
        raw = np.corrcoef(E, O)[0, 1]
        des = np.corrcoef(Ea, Oa)[0, 1]
        assert np.isfinite(des), f"{tag} 去季节相关是 NaN —— 分组键又取错了"
        n = {"tropical": 16, "north": 16, "south": 16, "paired8": 32}[tag]
        print(f"  {tag:10s} {n:4d} {E.std():8.4f} {O.std():8.4f} "
              f"{O.std()/E.std():6.3f} {raw:+9.4f} {des:+10.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
