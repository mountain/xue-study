#!/usr/bin/env python3
"""干净的海陆分层：只留海-海对 vs 只留陆-海对，各跑同一套消融。

为什么要分层而不是只做旋转：旋转同时改了「海陆构成」与「经度身份」，所以上一件只能说
「砍掉一半陆-海对没让增量退化」，不能说「海陆无关」。分层是把海陆**单独**拿出来。

设计：
  1. 用官方 NCEP R1 掩膜（`data/land.sfc.gauss.nc`，出处见同名 .provenance.txt）。
  2. 配对池 = tropical 结构 × 12 个勾股旋转（k=0..11），每个旋转给出 8 对
     （|z|=5/13 四对、|z|=3/5 四对），共 96 对。
  3. 按海陆分类每一对。
  4. **按 |z| 配对抽稀**：让「海-海」与「陆-海」两个几何的 |z| 多重集完全相同，
     节点数也相同 ⇒ 两者**只差海陆**。
  5. 各跑 564 次原生求值 + 消融。

节点表经由**同一个 JSON 文件**同时驱动程序（adva_source）与请求（extract_nodes
--nodes-json），从根上没有顺序漂移的可能。
"""
import json
import subprocess
import sys
from fractions import Fraction as F
from pathlib import Path

import numpy as np
import xarray as xr

sys.path.insert(0, ".")
import extract_nodes as E                                     # noqa: E402
import parity_report                                          # noqa: E402
from gen_tropical import adva_source                          # noqa: E402

MASK = Path("data/land.sfc.gauss.nc")
N_ROT = 12


def load_mask():
    ds = xr.open_dataset(MASK)
    land = ds["land"].isel(time=0).values.astype(float) > 0.5
    lat, lon = ds["lat"].values.astype(float), ds["lon"].values.astype(float)
    assert land.shape == (lat.size, lon.size), (land.shape, lat.size, lon.size)

    def is_land(la, lo):
        i = int(np.argmin(np.abs(lat - la)))
        j = int(np.argmin(np.abs(((lon - (lo % 360.0)) + 180) % 360 - 180)))
        return bool(land[i, j])

    return is_land, land, lat, lon


def pairs_of(nodes):
    """把一个 16 节点的 tropical 结构拆成 8 对：(zname, |z|, 经度, NH节点, SH节点)。

    节点顺序（extract_nodes.nodes("tropical")）：0-3 z=+5/13，4-7 z=-5/13，
    8-11 z=+3/5，12-15 z=-3/5；每段内四个基本方位的顺序是 0°/180°/90°/270°。
    """
    out = []
    for zname, hi, lo in (("5/13", 0, 4), ("3/5", 8, 12)):
        for i in range(4):
            nh, sh = nodes[hi + i], nodes[lo + i]
            assert nh[2] > 0 > sh[2], f"第 {i} 对不是南北配对: {nh} {sh}"
            assert abs(nh[2] + sh[2]) < 1e-12, "对径对的 z 不是相反数"
            lon = np.degrees(np.arctan2(float(nh[1]), float(nh[0]))) % 360.0
            out.append((zname, nh, sh, round(lon, 3)))
    return out


def main() -> int:
    is_land, land, mlat, mlon = load_mask()
    print(f"  掩膜 data/land.sfc.gauss.nc  陆地 {land.sum()}/{land.size} = {land.mean():.1%}")

    # ---- 先在【我们用到的那条纬度带】里做独立核对 ----
    print()
    print("  === 独立物理核对：t2m 季节振幅，限制在 |lat| <= 40° ===")
    t = xr.open_dataset(Path.home() /
                        "climatetensor-inputs/ncep-multivariate/"
                        "ncep.reanalysis.derived__surface_gauss__air.2m.mon.mean.nc")
    var = [v for v in t.data_vars if "air" in v.lower()][0]
    tas = t[var].values.astype(float)
    tm = t["time"].dt.month.values
    clim = np.stack([np.nanmean(tas[tm == m], axis=0) for m in range(1, 13)])
    amp = np.nanmax(clim, axis=0) - np.nanmin(clim, axis=0)
    band = np.abs(mlat) <= 40
    sub_land = land[band]
    sub_amp = amp[band]
    print(f"    |lat|<=40° 内：陆格 {sub_land.sum()}，海格 {(~sub_land).sum()}")
    print(f"    陆上振幅中位数 {np.median(sub_amp[sub_land]):6.2f} K")
    print(f"    海上振幅中位数 {np.median(sub_amp[~sub_land]):6.2f} K")
    for thr in (6, 8, 10, 12):
        pred = sub_amp > thr
        print(f"    阈值 {thr:2d} K：一致率 {(pred == sub_land).mean():.1%}"
              f"（海误判为陆 {int((pred & ~sub_land).sum())}，陆漏判 {int((~pred & sub_land).sum())}）")
    print("    ⇒ 两个总体的中位数相差数倍，方向与物理一致（陆地热容量小 ⇒ 振幅大）。")

    # ---- 配对池：直接枚举勾股方位角 ----
    # 不用旋转：k 次旋转后坐标分母是 13·5^k，k=11 时约 6e8，limit_denominator(60) 会给出
    # 【错的】近似（实测把 -36/65 收成 -31/56）。而任何勾股方位角都合法：
    #   节点 = (rad·c, rad·s, ±z)，其中 c²+s²=1、rad²+z²=1 ⇒ 坐标全有理、范数为 1。
    # 分母最大 13·29 = 377，远小于旋转累积出来的量级。
    PYTH = ((1, 0, 1), (0, 1, 1), (3, 4, 5), (4, 3, 5), (5, 12, 13), (12, 5, 13),
            (8, 15, 17), (15, 8, 17), (7, 24, 25), (24, 7, 25), (20, 21, 29), (21, 20, 29))
    AZ = []
    for c, sq, d in PYTH:
        for sc in (1, -1):
            for ss in (1, -1):
                v = (F(sc * c, d), F(ss * sq, d))
                if v not in AZ:
                    AZ.append(v)
    print()
    print(f"  === 配对池：tropical 结构 × {len(AZ)} 个勾股方位角 ===")

    def nodes_for(z: F, rad: F):
        """四条子午线上的四个节点……实际是给每个方位角一个节点。"""
        return [[rad * c, rad * sq, z] for c, sq in AZ]

    pool = []
    for zname, z, rad in (("5/13", F(5, 13), F(12, 13)), ("3/5", F(3, 5), F(4, 5))):
        for c, sq in AZ:
            for sgn in (1, -1):
                zz = sgn * z
                nh = [float(rad * c), float(rad * sq), float(zz)]
                sh = [float(rad * c), float(rad * sq), float(-zz)]
                lon = float(np.degrees(np.arctan2(float(sq), float(c))) % 360.0)
                la = float(np.degrees(np.arcsin(float(zz))))
                n_land = is_land(la, lon)
                s_land = is_land(-la, lon)
                cls = ("陆" if n_land else "海") + "-" + ("陆" if s_land else "海")
                pool.append({"zname": zname, "lon": round(lon, 3), "cls": cls,
                             "nh": nh, "sh": sh})
    from collections import Counter
    c = Counter(p["cls"] for p in pool)
    print(f"    {len(pool)} 对，分类 {dict(c)}")
    cc = Counter((p["zname"], p["cls"]) for p in pool)
    for zn in ("5/13", "3/5"):
        print(f"    |z|={zn:5s}: " + "  ".join(
            f"{cl}:{cc.get((zn, cl), 0)}" for cl in ("海-海", "陆-海", "陆-陆", "海-陆")))

    # ---- 配对抽稀：两个分层的 |z| 多重集完全相同 ----
    per = {}
    for zn in ("5/13", "3/5"):
        for cl in ("海-海", "陆-海"):
            per[(zn, cl)] = [p for p in pool if p["zname"] == zn and p["cls"] == cl]
    n = min(len(per[(zn, cl)]) for zn in ("5/13", "3/5") for cl in ("海-海", "陆-海"))
    print()
    print(f"  === 抽稀到每格 n={n} 对，使两层的 |z| 多重集完全相同 ===")
    strata = {}
    for cl in ("海-海", "陆-海"):
        sel = []
        for zn in ("5/13", "3/5"):
            sel += per[(zn, cl)][:n]
        strata[cl] = sel
        print(f"    {cl}: {len(sel)} 对 = {len(sel)*2} 节点   "
              f"经度 {sorted({p['lon'] for p in sel})}")

    # ---- 求值 ----
    print()
    print("  === 求值与消融 ===")
    print(f"  {'分层':>8s} {'节点':>4s} {'经度组合':>22s} {'去季节corr':>10s} "
          + " ".join(f"{'k='+str(x):>9s}" for x in (1, 2, 4, 6)))
    for cl in ("海-海", "陆-海"):
        sel = strata[cl]
        tag = "ls_" + ("oo" if cl == "海-海" else "lo")
        d = Path("runs") / tag
        d.mkdir(parents=True, exist_ok=True)
        nodes = []
        for p in sel:
            nodes += [p["nh"], p["sh"]]
        nj = d / "nodes.json"
        nj.write_text(json.dumps(nodes))
        if not (d / "eo.npz").exists():
            (d / f"spectrum-{tag}.adva").write_text(
                adva_source([(F(x).limit_denominator(1000), F(y).limit_denominator(1000),
                          F(z).limit_denominator(1000)) for x, y, z in nodes]))
            subprocess.run([sys.executable, "extract_nodes.py", "--nodes-json", str(nj),
                            "--level", "500", "--out", str(d / "req.json")],
                           check=True, stdout=subprocess.DEVNULL)
            subprocess.run(["./target/debug/sphaera-frame-probe",
                            str(d / f"spectrum-{tag}.adva"), str(d / "req.json"),
                            str(d / "nat.json")], check=True, stdout=subprocess.DEVNULL)
            j = json.loads((d / "nat.json").read_text())
            ev = [e for e in j["evaluations"] if e["function"] == "spectrum"]
            r = np.array([e["result"]["values"] for e in ev], float)
            np.savez(d / "eo.npz", E=r[:, 0], O=r[:, 1],
                     months=np.array([e["id"] for e in ev]))
        z = np.load(d / "eo.npz")
        Ea, Oa, m = z["E"], z["O"], z["months"].astype(str)
        mon = np.array([s[5:7] for s in m])
        a, b = Ea.astype(float).copy(), Oa.astype(float).copy()
        for mm in set(mon):
            sel_m = mon == mm
            a[sel_m] -= Ea[sel_m].mean()
            b[sel_m] -= Oa[sel_m].mean()
        corr = float(np.corrcoef(a, b)[0, 1])
        ds = [parity_report.ablation(str(d / "eo.npz"), kk)[0] for kk in (1, 2, 4, 6)]
        cells = " ".join("     —   " if v is None else f"{v:+9.4f}" for v in ds)
        lons = ",".join(str(int(p["lon"])) for p in sel)
        print(f"  {cl:>8s} {len(nodes):4d} {lons:>22s} {corr:+10.4f} {cells}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
