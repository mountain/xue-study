#!/usr/bin/env python3
"""经度去混：绕 z 轴按勾股角 53.13° 旋转 k 次，重跑同一批几何。

单变量：绕 z 轴转 ⇒ |z|、纬度、环结构、节点数、方位模式**全不动**，**只动子午线**。
k=0 是原始（0/90/180/270°），k=1,2,3 给出三组全新的子午线（模块 rotation.py 已断言）。

要回答两件事：
  1. 现有结论（配对是决定性的、环位有影响）是不是【4 条子午线的产物】？
  2. 旋转会改变海陆构成 —— 于是「海陆对占比」与「增量」的关系变成一次自然实验。

消融解析一律复用 parity_report.ablation（只认锚定的 "RMSE … → … (Δ …)"），
不写第二份 —— 本会话已因宽松正则把 corr 差当成 RMSE 差，出过符号翻转的错误读数。
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")
import extract_nodes as E                                     # noqa: E402
import parity_report                                          # noqa: E402
import rotation as R                                          # noqa: E402
from gen_tropical import adva_source                          # noqa: E402

BASES = ("tropical", "declared")
KS = (1, 2, 3)
SRC = Path.home() / "climatetensor-inputs/ncep-multivariate"


def landsea(nodes):
    """每个节点所在格点是陆是海；返回 (北半球陆点数, 南半球陆点数, 陆-海对数, 海-海对数)。

    掩膜用 sst.npz 的 NaN —— **这是个粗代理**（会把海冰标成陆，2° 网格比风场 2.5° 还粗），
    故这里的结果只能当定性参考，不能当精确占比。
    """
    s = np.load(SRC / "sst.npz")
    lat, lon = s["lat"].astype(float), s["lon"].astype(float)
    m = np.isfinite(s["values"].astype(float)[0])

    def is_ocean(la, lo):
        i = int(np.argmin(np.abs(lat - la)))
        j = int(np.argmin(np.abs(((lon - (lo % 360.0)) + 180) % 360 - 180)))
        return bool(m[i, j])

    # 按 (|z|, 经度) 配成对径对
    pairs = {}
    for x, y, z in nodes:
        la = np.degrees(np.arcsin(float(z)))
        lo = np.degrees(np.arctan2(float(y), float(x))) % 360.0
        key = (round(abs(float(z)), 6), round(lo, 3))
        pairs.setdefault(key, {})["N" if z > 0 else "S"] = is_ocean(la, lo)
    nl = sum(1 for d in pairs.values() if d.get("N") is False)
    sl = sum(1 for d in pairs.values() if d.get("S") is False)
    lo_pairs = sum(1 for d in pairs.values()
                   if d.get("N") is False and d.get("S") is True)
    oo_pairs = sum(1 for d in pairs.values()
                   if d.get("N") is True and d.get("S") is True)
    return nl, sl, lo_pairs, oo_pairs, len(pairs)


def build(base, k):
    tag = f"{base}_rot{k}"
    d = Path("runs") / tag
    d.mkdir(parents=True, exist_ok=True)
    if (d / "eo.npz").exists():
        z = np.load(d / "eo.npz")
        return tag, len(z["E"]), d / "eo.npz"
    rot = R.rotate_nodes(E.nodes(base), k)
    (d / f"spectrum-{tag}.adva").write_text(adva_source(rot))
    subprocess.run([sys.executable, "extract_nodes.py", "--nodes", base, "--rotate", str(k),
                    "--level", "500", "--out", str(d / "req.json")], check=True,
                   stdout=subprocess.DEVNULL)
    subprocess.run(["./target/debug/sphaera-frame-probe",
                    str(d / f"spectrum-{tag}.adva"), str(d / "req.json"),
                    str(d / "nat.json")], check=True, stdout=subprocess.DEVNULL)
    j = json.loads((d / "nat.json").read_text())
    ev = [e for e in j["evaluations"] if e["function"] == "spectrum"]
    r = np.array([e["result"]["values"] for e in ev], float)
    np.savez(d / "eo.npz", E=r[:, 0], O=r[:, 1], months=np.array([e["id"] for e in ev]))
    return tag, len(ev), d / "eo.npz"


def stats(eo, k):
    z = np.load(eo)
    E_, O_, m = z["E"], z["O"], z["months"].astype(str)
    mon = np.array([s[5:7] for s in m])
    a, b = E_.astype(float).copy(), O_.astype(float).copy()
    for mm in set(mon):
        sel = mon == mm
        a[sel] -= E_[sel].mean()
        b[sel] -= O_[sel].mean()
    return float(np.corrcoef(a, b)[0, 1]), O_.std() / E_.std(), parity_report.ablation(str(eo), k)


def main() -> int:
    print("  === 经度旋转扫描：只动子午线 ===")
    print(f"  {'几何':>16s} {'子午线(°)':>28s} {'NH陆':>4s} {'SH陆':>4s} "
          f"{'陆-海':>5s} {'海-海':>5s} {'O/E':>6s} {'去季节corr':>10s} "
          + " ".join(f"{'k='+str(x):>9s}" for x in (1, 2, 4, 6)))
    rows = []
    for base in BASES:
        for k in (0,) + KS:
            if k == 0:
                src = {"tropical": Path("runs/tropical/eo-500.npz"),
                       "declared": Path("runs/declared/eo.npz")}[base]
                tag = base
                nodes = E.nodes(base)
            else:
                tag, n, src = build(base, k)
                nodes = R.rotate_nodes(E.nodes(base), k)
            assert src.exists(), f"{tag} 缺 eo"
            mer = R.meridian_deg(nodes)
            nl, sl, lop, oop, npr = landsea(nodes)
            corr, oe, (d1, d4) = stats(src, 1)[0], stats(src, 1)[1], (None, None)
            ds = [stats(src, kk)[2][0] for kk in (1, 2, 4, 6)]
            corr, oe = stats(src, 1)[0], stats(src, 1)[1]
            cells = " ".join("     —   " if v is None else f"{v:+9.4f}" for v in ds)
            print(f"  {tag:>16s} {str(mer):>28s} {nl:4d} {sl:4d} {lop:5d} {oop:5d} "
                  f"{oe:6.3f} {corr:+10.4f} {cells}")
            rows.append((base, k, nl, sl, lop, oop, corr, ds[0]))
    print()
    print("  === 按底几何看：旋转是否改变了结论 ===")
    for base in BASES:
        sub = [r for r in rows if r[0] == base]
        vals = [r[7] for r in sub if r[7] is not None]
        signs = {("负" if v < 0 else "正") for v in vals}
        print(f"    {base:9s} M2−M1(k=1) 在 k=0..3 上: "
              + "  ".join(f"k={r[1]}:{r[7]:+.4f}" for r in sub if r[7] is not None)
              + f"   → 符号{'一致' if len(signs) == 1 else '【翻转】'}")
        print(f"             陆-海对 {[r[4] for r in sub]}   海-海对 {[r[5] for r in sub]}   "
              f"去季节corr {[round(r[6],3) for r in sub]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
