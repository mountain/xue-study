"""把 R1 月平均风场取到 sphaera-frame 的 16 个声明节点上，转成原生程序要的笛卡尔分量。

为什么需要这一件
----------------
`sphaera-frame` 的原生程序对【数据】是固定的：几何（16 个节点、权重）烤在 .adva 里，
换数据只需换 request.json。所以把真实风场喂进去，唯一要做的就是
「把风插值到那 16 个节点、转成程序要求的笛卡尔 x/y 分量」。

两处必须与结论同时出现的落差
----------------------------
1. **节点纬度不落在 2.5° 网格上。** 声明节点是 z=±3/5, ±4/5 即纬度 ±36.87°, ±53.13°，
   而 R1 月平均的网格是 37.5°/52.5°。本件用**双线性插值**逼近声明纬度，
   但插值不能消除这个落差：程序里烤死的权重对应 z=±3/5,±4/5，
   而采样点实际在 z=±0.6088 / ±0.7986 上。**这是一个 1.5% 量级的几何不匹配，本件不消解它。**
2. **经度恰好落在网格上**（0/90/180/270 都是 2.5° 的整数倍），所以经度方向无需插值。

笛卡尔约定
----------
节点单位位置 r=(cosφcosλ, cosφsinλ, sinφ)。当地东/北单位向量
  e = (−sinλ, cosλ, 0),  n = (−sinφcosλ, −sinφsinλ, cosφ)
故 u_cart = u_east·e + v_north·n，且 r·u_cart = 0（切向，与 check.py 的断言一致）。
原生程序只用 u_x, u_y（丢弃 u_z），因为它算的是 (r×u)_z = x·u_y − y·u_x。
"""
from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np

# 与 check.py geometry() 同序：+3/5, −3/5, +4/5, −4/5；每环四个方位 (+x,−x,+y,−y)
def nodes(preset="declared"):
    """节点表。`declared` 是 sphaera-frame 声明的；`tropical` 是本实验的热带变体。

    两者【不是同一个几何】，引用时必须分开说。热带变体受【有理算术】限制：
    节点必须是单位向量且坐标有理，故 z 只能取勾股数，能到的最小 |z| 是 5/13
    （纬度 22.62°）—— **无法更靠近赤道**。
    """
    if preset == "declared":
        rings = ((3/5, 4/5), (-3/5, 4/5), (4/5, 3/5), (-4/5, 3/5))
    elif preset == "tropical":
        rings = ((5/13, 12/13), (-5/13, 12/13), (3/5, 4/5), (-3/5, 4/5))
    elif preset == "north":
        # 证伪几何：四个环全取北半球 ⇒ sign(z) 恒为 +1 ⇒ E 退化为纯水平项。
        # 这是上一件写下的证伪点：若宇称分解是 E/O 区分的来源，撤掉对径配对应当让它退化。
        rings = ((5/13, 12/13), (12/13, 5/13), (3/5, 4/5), (4/5, 3/5))
    elif preset == "dense":
        # 8 个方位（4 基本 + 4 勾股对角）× 4 环 = 32 节点。
        # 与 gen_dense.py 的 NODES **必须同序**。
        rings = ((5/13, 12/13), (-5/13, 12/13), (3/5, 4/5), (-3/5, 4/5))
        out = []
        for z, rad in rings:
            for x, y in ((rad, 0.0), (-rad, 0.0), (0.0, rad), (0.0, -rad),
                         (4*rad/5, 3*rad/5), (-4*rad/5, -3*rad/5),
                         (3*rad/5, 4*rad/5), (-3*rad/5, -4*rad/5)):
                out.append((x, y, z))
        return out
    else:
        raise SystemExit(f"unknown preset {preset}")
    out = []
    for z, rad in rings:
        for x, y in ((rad, 0.0), (-rad, 0.0), (0.0, rad), (0.0, -rad)):
            out.append((x, y, z))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inputs", default=str(Path.home() / "climatetensor-inputs/ncep-multivariate"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--level", type=int, default=850)
    ap.add_argument("--nodes", default="declared", choices=("declared","tropical","dense","north"))
    args = ap.parse_args()
    src = Path(args.inputs)
    tag = f"u{args.level}"
    u = np.load(src / f"u{args.level}.npz")
    v = np.load(src / f"v{args.level}.npz")
    meta = json.loads((src / f"v{args.level}.json").read_text())
    months = meta["months"]
    # 用【源自己的坐标】，不假设网格 —— 本项目早先因为拿一个源的掩膜套另一个源栽过。
    ua, va = u["values"], v["values"]
    lat, lon = u["lat"].astype(float), u["lon"].astype(float)
    print(f"  u{args.level} {ua.shape}  v{args.level} {va.shape}  月 {months[0]}…{months[1]} ({ua.shape[0]})")
    print(f"  源自带网格: lat {lat[0]}→{lat[-1]} ({lat.size}, 步长 {abs(lat[1]-lat[0]):.1f})  "
          f"lon {lon[0]}→{lon[-1]} ({lon.size}, 步长 {abs(lon[1]-lon[0]):.1f})")
    assert ua.shape[1:] == (lat.size, lon.size), (ua.shape, lat.size, lon.size)
    assert np.allclose(u["lat"], v["lat"]) and np.allclose(u["lon"], v["lon"]), "u/v 网格不一致"

    N = nodes(args.nodes)
    phi = np.array([np.arcsin(z) for _, _, z in N])          # 声明纬度（弧度）
    lam = np.array([np.arctan2(y, x) for x, y, _ in N])
    print(f"  声明纬度 {np.degrees(phi).round(2)}")
    print(f"  网格最近纬度 {[lat[np.argmin(abs(lat-np.degrees(p)))] for p in phi]}")

    def bilinear(field2d, pla, plo):
        # 纬度递减，经度递增
        fi = np.interp(-pla, -lat, np.arange(lat.size))
        fj = np.interp(plo % 360.0, lon, np.arange(lon.size))
        i0, j0 = int(np.floor(fi)), int(np.floor(fj))
        i1, j1 = min(i0 + 1, lat.size - 1), (j0 + 1) % lon.size
        di, dj = fi - i0, fj - j0
        return ((1-di)*(1-dj)*field2d[i0, j0] + (1-di)*dj*field2d[i0, j1]
                + di*(1-dj)*field2d[i1, j0] + di*dj*field2d[i1, j1])

    cases, series = [], []
    for k in range(ua.shape[0]):
        inp = {}
        for j, ((x, y, z), p, l) in enumerate(zip(N, phi, lam)):
            ue = bilinear(ua[k], np.degrees(p), np.degrees(l))
            vn = bilinear(va[k], np.degrees(p), np.degrees(l))
            ee = np.array([-np.sin(l), np.cos(l), 0.0])
            nn = np.array([-np.sin(p)*np.cos(l), -np.sin(p)*np.sin(l), np.cos(p)])
            w = ue*ee + vn*nn
            # 断言切向（与 check.py 一致）；插值后仍有舍入，故用容差
            assert abs(x*w[0] + y*w[1] + z*w[2]) < 1e-9, (k, j)
            inp[f"u{j}x"], inp[f"u{j}y"], inp[f"u{j}z"] = float(w[0]), float(w[1]), float(w[2])
        cases.append({"id": _month(months[0], k), "function": "spectrum", "inputs": inp})
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    # THE FULL FUNCTION SET, NOT JUST "spectrum".  The probe runs hard-coded
    # controls that evaluate `compiled["turn-i"]` regardless of what the request
    # asks for, so declaring only "spectrum" panics with `no entry found for
    # key`.  Declaring all exports compiles them; only `spectrum` gets cases.
    exports = ["spectrum", "turn-i", "twice-i", "conjugate", "p-after-i",
               "i-after-p", "shear", "unshear", "chart-i", "norm",
               "chart-norm", "old-then-i"]
    json.dump({"functions": exports, "cases": cases}, out.open("w"))
    print(f"  已写 {out}   {len(cases)} 个 case × 48 个输入")
    return 0


def _month(start: str, k: int) -> str:
    """start like "1979-01"; label the k-th month after it."""
    y, m = int(start[:4]), int(start[5:7])
    m0 = m - 1 + k
    return f"{y + m0 // 12:04d}-{m0 % 12 + 1:02d}"


if __name__ == "__main__":
    raise SystemExit(main())
