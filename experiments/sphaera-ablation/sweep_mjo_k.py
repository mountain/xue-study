"""把 O 的增量沿提前量 k 画出来 —— 让「同期响应」从一句话变成一个形状。

判据（写在跑之前）
------------------
若热带外采样只是**同期**响应，则：
  · M2−M1 在 k=0 处最大（同期最强耦合）
  · 随 k 增大单调衰减
  · 而 M4−M3（加了持续性之后）应当**处处接近零**
若不是这个形状（例如 k=2 出现峰、或随 k 上升），则「同期」这个说法要改。
"""
import re, subprocess
from pathlib import Path

PY = str(Path.home() / "climatetensor-env/bin/python")
KS = [0, 1, 2, 3, 6, 12]

def run(k):
    out = subprocess.run([PY, "ablate_mjo.py", "--eo", "runs/tropical/eo-500.npz",
                          "--lead", str(k)], capture_output=True, text=True).stdout
    rows = {}
    for line in out.splitlines():
        m = re.match(r"^\s*(MJO-PC\d)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+([+-][\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+([+-][\d.]+)", line)
        if m:
            rows[m.group(1)] = (float(m.group(2)), float(m.group(3)), float(m.group(4)),
                                float(m.group(5)), float(m.group(6)), float(m.group(7)))
    return rows

print("  MJO-PC1：O 的增量随提前量")
print(f"  {'k':>3}{'M1 E':>10}{'M2 E+O':>10}{'M2-M1':>10}{'M3 E+PC':>10}{'M4':>10}{'M4-M3':>10}")
p1 = []
for k in KS:
    r = run(k)
    if "MJO-PC1" not in r: continue
    a, b, d, e, f, g = r["MJO-PC1"]
    p1.append((k, d, g))
    print(f"  {k:>3}{a:>10.4f}{b:>10.4f}{d:>+10.4f}{e:>10.4f}{f:>10.4f}{g:>+10.4f}")

print()
print("  MJO-PC2：O 的增量随提前量")
print(f"  {'k':>3}{'M1 E':>10}{'M2 E+O':>10}{'M2-M1':>10}{'M3 E+PC':>10}{'M4':>10}{'M4-M3':>10}")
p2 = []
for k in KS:
    r = run(k)
    if "MJO-PC2" not in r: continue
    a, b, d, e, f, g = r["MJO-PC2"]
    p2.append((k, d, g))
    print(f"  {k:>3}{a:>10.4f}{b:>10.4f}{d:>+10.4f}{e:>10.4f}{f:>10.4f}{g:>+10.4f}")

print()
for tag, rows in (("PC1", p1), ("PC2", p2)):
    if not rows: continue
    mx = max(rows, key=lambda t: t[1])
    mono = all(b[1] <= a[1] + 1e-9 for a, b in zip(rows, rows[1:]))
    print(f"  {tag}: M2-M1 最大在 k={mx[0]}（{mx[1]:+.4f}）；随 k 单调不增: {mono}")
    print(f"       M4-M3 范围 [{min(r[2] for r in rows):+.4f}, {max(r[2] for r in rows):+.4f}]")
