#!/usr/bin/env python3
"""把「两环配对」族扫完：{5/13, 3/5, 4/5, 12/13} 的全部 4 选 2 组合。

回答的问题是：**是不是所有 O(3) 合法的配对配置都一样好？**（已经知道不是 —— declared 是
合法配对却无增量。本扫描把这个族整体铺开，看强度是否随环位单调。）

关键做法：程序用 `adva_source(extract_nodes.nodes("pair2:..."))` 生成，
**与请求用的是同一份节点表**，从根上排除生成器/请求构造器之间的顺序漂移。
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")
import extract_nodes as E                                  # noqa: E402
from gen_tropical import adva_source                        # noqa: E402

ALL_PAIRS = ["5/13,3/5", "5/13,4/5", "3/5,4/5",
             "5/13,12/13", "3/5,12/13", "4/5,12/13"]
# 已有 run 目录的对照（不重算）
EXISTING = {"5/13,3/5": "tropical", "5/13,4/5": "cross", "3/5,4/5": "declared"}
# tropical 的 eo 是按层次分开存的
EO_NAME = {"tropical": "eo-500.npz", "dense": "eo-500.npz"}


from fractions import Fraction as F                            # noqa: E402


def frac_nodes_checked(pair):
    """按 pair2 的规则用 Fraction 重建节点表，并断言与 extract_nodes 的输出【逐节点同序一致】。

    adva_source 要 Fraction（它写的是 1/16 这样的精确分数），而 extract_nodes 返回 float。
    所以不能直接把 extract_nodes 的输出喂进去；但也不能各写一套 —— 那样就回到顺序漂移的老问题。
    这里的断言就是防这个。
    """
    out = []
    for zs in pair.split(","):
        z = F(zs)
        rad = F(round((1 - z * z) ** 0.5, 12)).limit_denominator(60)
        assert rad * rad + z * z == 1, f"{zs} 不是勾股 |z|（rad={rad}）"
        for zz in (z, -z):
            out += [(rad, F(0), zz), (-rad, F(0), zz), (F(0), rad, zz), (F(0), -rad, zz)]
    theirs = E.nodes("pair2:" + pair)
    assert len(out) == len(theirs), f"节点数 {len(out)} vs {len(theirs)}"
    for i, ((a, b, c), (x, y, z2)) in enumerate(zip(out, theirs)):
        dmax = max(abs(float(a) - x), abs(float(b) - y), abs(float(c) - z2))
        assert dmax < 1e-12, f"第 {i} 个节点差 {dmax:.3g} —— 两套构造漂移了"
    return out


def tag_of(pair):
    return "p2_" + pair.replace("/", "").replace(",", "_")


def build(pair):
    tag = tag_of(pair)
    d = Path("runs") / tag
    d.mkdir(parents=True, exist_ok=True)
    # 探针拒绝覆盖已有的 nat.json（code 17）。已算过的就不重算。
    if (d / "nat.json").exists() and (d / "eo.npz").exists():
        z = np.load(d / "eo.npz")
        return tag, len(z["E"]), float(z["E"].std()), float(z["O"].std())
    nodes = frac_nodes_checked(pair)
    (d / f"spectrum-{tag}.adva").write_text(adva_source(nodes))
    subprocess.run([sys.executable, "extract_nodes.py", "--pair2", pair,
                    "--level", "500", "--out", str(d / "req.json")], check=True)
    subprocess.run(["./target/debug/sphaera-frame-probe",
                    str(d / f"spectrum-{tag}.adva"), str(d / "req.json"),
                    str(d / "nat.json")], check=True)
    j = json.loads((d / "nat.json").read_text())
    ev = [e for e in j["evaluations"] if e["function"] == "spectrum"]
    r = np.array([e["result"]["values"] for e in ev], float)
    months = np.array([e["id"] for e in ev])
    np.savez(d / "eo.npz", E=r[:, 0], O=r[:, 1], months=months)
    return tag, len(ev), float(r[:, 0].std()), float(r[:, 1].std())


# 不自己写第二份解析：ablate.py 会打【四行】含 Δ —— 两行 corr、两行 RMSE。
# 宽松正则 \(Δ ...\) 抓到的是前两行 = corr 差，而我一度把它们当成 RMSE 差贴进表里，
# 于是 declared 从 +0.0069 变成 −0.1763、cross 从 −0.0117 变成 +0.0950，且符号翻转。
# 现已改为直接复用 parity_report 的锚定实现（只认 "RMSE … → … (Δ …)"）。
import parity_report                                          # noqa: E402


def ablate(eo, lead):
    return parity_report.ablation(str(eo), lead)


def main() -> int:
    for pair in ALL_PAIRS:
        if pair in EXISTING:
            print(f"  {pair:12s} 已有 -> runs/{EXISTING[pair]}")
            continue
        tag, n, se, so = build(pair)
        print(f"  {pair:12s} 已求值 -> runs/{tag}   {n} 次  E sd {se:.4f}  O sd {so:.4f}")

    print()
    print("  " + "=" * 78)
    print("  两环配对族全表（564 月，去季节按日历月；M2−M1 为 RMSE Δ，负 = O 有增量）")
    print("  " + "=" * 78)
    hdr = f"  {'|z| 对':>14s} {'纬度(下/上)':>14s} {'O/E':>6s} {'去季节corr':>10s} " \
          + " ".join(f"{'k='+str(k):>9s}" for k in (1, 2, 4, 6))
    print(hdr)
    rows = []
    for pair in ALL_PAIRS:
        src = Path("runs") / EXISTING.get(pair, tag_of(pair))
        eo = src / EO_NAME.get(EXISTING.get(pair, ""), "eo.npz")
        if not eo.exists():
            print(f"  {pair:>14s} 缺 eo")
            continue
        z = np.load(eo)
        E_, O_, m = z["E"], z["O"], z["months"].astype(str)
        mon = np.array([s[5:7] for s in m])
        da = E_.astype(float).copy()
        db = O_.astype(float).copy()
        for mm in set(mon):
            k = mon == mm
            da[k] -= E_[k].mean()
            db[k] -= O_[k].mean()
        corr = float(np.corrcoef(da, db)[0, 1])
        ds = [ablate(eo, k)[0] for k in (1, 2, 4, 6)]
        lo, hi = pair.split(",")
        lat_lo = np.degrees(np.arcsin(float(__import__("fractions").Fraction(lo))))
        lat_hi = np.degrees(np.arcsin(float(__import__("fractions").Fraction(hi))))
        cells = " ".join("     —   " if v is None else f"{v:+9.4f}" for v in ds)
        print(f"  {pair:>14s} {lat_lo:6.1f}/{lat_hi:5.1f}° {O_.std()/E_.std():6.3f} "
              f"{corr:+10.4f} {cells}")
        rows.append((lat_lo, ds[0], corr))
    print()
    print("  按【下环纬度】排序（看强度是否随环位单调）：")
    for lat, d1, corr in sorted(rows):
        v = "—" if d1 is None else f"{d1:+.4f}"
        print(f"    下环 {lat:5.1f}°   M2−M1(k=1) {v}   去季节corr {corr:+.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
