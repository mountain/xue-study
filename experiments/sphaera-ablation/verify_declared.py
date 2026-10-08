#!/usr/bin/env python3
"""验证 runs/l500 确实是 extract_nodes 描述的那个 declared 几何。

做法不是查预设表，而是【重跑】：用本地重新生成的 spectrum-declared.adva 走完整流水线，
把得到的 E/O 与 runs/l500/eo.npz 里记录的逐年逐月值【逐点相减】。

若最大绝对差在浮点噪声量级 ⇒ 那次 run 用的就是这个几何，limitation「declared 的配对
是从预设表读的、没有证据」才算关掉。

注意：内联 heredoc 的 f-string 不能含反斜杠 —— 我在这上面栽了四次，故一律写成文件。
"""
import json
from pathlib import Path

import numpy as np

new = json.loads(Path("runs/declared/nat.json").read_text())
ev = [e for e in new["evaluations"] if e["function"] == "spectrum"]
r = np.array([e["result"]["values"] for e in ev], float)
months_new = np.array([e["id"] for e in ev])

old = np.load("runs/l500/eo.npz")
months_old = old["months"].astype(str)

print(f"  重跑 {len(months_new)} 个月，原存 {len(months_old)} 个月")
assert len(months_new) == len(months_old) == 564
assert (months_old == months_new).all(), "月份轴不一致 —— 不是同一批 case"

for i, key in enumerate(("E", "O")):
    a, b = r[:, i], old[key]
    d = np.abs(a - b)
    scale = max(float(b.std()), 1e-30)
    print(f"  {key}: 重跑 sd {a.std():.6f}   原存 sd {b.std():.6f}   "
          f"最大绝对差 {d.max():.3e}   相对 {d.max()/scale:.3e}   "
          f"逐点全等 {bool((a == b).all())}")
    if d.max() > 1e-9 * scale:
        print(f"     *** 差异超出浮点噪声 —— runs/l500 不是这个几何 ***")

np.savez("runs/declared/eo.npz", E=r[:, 0], O=r[:, 1], months=months_new)
print("  已写 runs/declared/eo.npz")
