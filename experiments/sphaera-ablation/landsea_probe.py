#!/usr/bin/env python3
"""在画界限之前，先量一件事：我们的对径配对到底采到了什么？

坐标事实（来自 extract_nodes）：节点是笛卡尔 (rad,0),(-rad,0),(0,rad),(0,-rad)，
故经度只有 0°/90°/180°/270° 四条子午线。纬度取 ±5/13(22.62°) 与 ±3/5(36.87°) 等。

海陆掩膜：直接复用 sst.npz —— 它的值在陆地上是 NaN，在海上是有限值。
（ablate.py 里那句「掩膜内陆地」的断言就是这个意思。）

问的问题：每个节点所在格点是陆是海？它对径点呢？
若配对大量落在「一端陆、一端海」上，那么对径配对在物理上就是一个【海陆对比采样器】。
"""
import json
from pathlib import Path

import numpy as np

SRC = Path.home() / "climatetensor-inputs/ncep-multivariate"
s = np.load(SRC / "sst.npz")
sst, lat, lon = s["values"].astype(float), s["lat"].astype(float), s["lon"].astype(float)
mask = np.isfinite(sst[0])                       # 第一年月：True=海, False=陆/NaN
print(f"  掩膜来自 sst.npz：{mask.shape}  海 {(mask.sum())} 格  陆/无值 {(~mask).sum()} 格")
print(f"  纬度 {lat[0]}→{lat[-1]}（步长 {abs(lat[1]-lat[0]):.1f}）  "
      f"经度 {lon[0]}→{lon[-1]}（步长 {abs(lon[1]-lon[0]):.1f}）")


def cell(la, lo):
    i = int(np.argmin(np.abs(lat - la)))
    j = int(np.argmin(np.abs(((lon - (lo % 360.0)) + 180) % 360 - 180)))
    return i, j, bool(mask[i, j])


GEOMS = {
    "tropical": [("5/13", 5/13), ("3/5", 3/5)],
    "declared": [("3/5", 3/5), ("4/5", 4/5)],
    "cross":    [("5/13", 5/13), ("4/5", 4/5)],
}
for tag, zs in GEOMS.items():
    print()
    print(f"  === {tag} ===")
    pairs = []
    for zname, z in zs:
        rad = float(np.sqrt(1 - z * z))
        for lon_deg, (x, y) in ((0.0, (rad, 0.0)), (180.0, (-rad, 0.0)),
                                (90.0, (0.0, rad)), (270.0, (0.0, -rad))):
            for sgn, hname in ((1, "N"), (-1, "S")):
                la = np.degrees(np.arcsin(sgn * z))
                i, j, is_ocean = cell(la, lon_deg)
                pairs.append((zname, hname, lon_deg, la, is_ocean))
    # 按 (|z|, 经度) 找对径对：北半球点与南半球同经度点
    idx = {(zn, lo): (h, la, oc) for zn, h, lo, la, oc in pairs}
    kind = {"陆-海": 0, "海-陆": 0, "海-海": 0, "陆-陆": 0}
    for zn, _ in zs:
        for lo in (0.0, 90.0, 180.0, 270.0):
            hN, laN, ocN = idx[(zn, lo)]
            hS, laS, ocS = idx[(zn, lo)]
            # 南半球点在同一个 (zn, lo) 键上被覆盖了，重取
        break
    # 直接重列，不绕弯
    rows = []
    for zname, z in zs:
        rad = float(np.sqrt(1 - z * z))
        for lo in (0.0, 90.0, 180.0, 270.0):
            laN = np.degrees(np.arcsin(z))
            laS = -laN
            _, _, ocN = cell(laN, lo)
            _, _, ocS = cell(laS, lo)
            k = ("海" if ocN else "陆") + "-" + ("海" if ocS else "陆")
            rows.append((zname, lo, laN, ocN, ocS, k))
            kind[k] = kind.get(k, 0) + 1
    for zn, lo, laN, ocN, ocS, k in rows:
        print(f"    |z|={zn:5s} 经度 {lo:5.1f}°  北 {laN:+6.2f}°={'海' if ocN else '陆'}  "
              f"南 {-laN:+6.2f}°={'海' if ocS else '陆'}   → {k}")
    print(f"    汇总：{kind}")
    nl = sum(1 for _, _, _, o, _, _ in rows if not o)
    print(f"    **北半球节点 {nl}/8 在陆上；南半球节点 "
          f"{sum(1 for _, _, _, _, o, _ in rows if not o)}/8 在陆上**")
