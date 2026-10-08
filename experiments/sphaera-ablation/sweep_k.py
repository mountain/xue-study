"""把消融沿提前量 k 扫一遍，热带几何与声明几何并置。"""
import subprocess, sys, re
from pathlib import Path

PY = str(Path.home() / "climatetensor-env/bin/python")

def run(eo, k):
    out = subprocess.run([PY, "ablate.py", "--eo", eo, "--lead", str(k)],
                         capture_output=True, text=True).stdout
    d = {}
    for line in out.splitlines():
        s = line.strip()
        m = re.match(r"^(M\d)\s+\S+\s+(\d+)\s+(\S+)\s+(\S+)\s+(\S+)", s)
        if m:
            d[m.group(1)] = (m.group(3), m.group(5))
    return d

print("  热带几何 500 hPa：corr / 对气候态技巧")
print(f"  {'k':>2} | {'M1 E':>16} | {'M2 E+O':>16} | {'M3 E+SST':>16} | {'M4 E+O+SST':>16} | M4-M3")
for k in range(1, 7):
    d = run("runs/tropical/eo-500.npz", k)
    if "M4" not in d: continue
    f = lambda x: f"{d[x][0]}/{d[x][1]}"
    delta = float(d["M4"][0]) - float(d["M3"][0])
    print(f"  {k:>2} | {f('M1'):>16} | {f('M2'):>16} | {f('M3'):>16} | {f('M4'):>16} | {delta:+.4f}")

print()
print("  对照：声明几何 500 hPa")
print(f"  {'k':>2} | {'M1 E':>16} | {'M2 E+O':>16} | M2-M1")
for k in range(1, 7):
    d = run("runs/l500/eo.npz", k)
    if "M2" not in d: continue
    delta = float(d["M2"][0]) - float(d["M1"][0])
    print(f"  {k:>2} | {d['M1'][0]}/{d['M1'][1]:>8} | {d['M2'][0]}/{d['M2'][1]:>8} | {delta:+.4f}")
