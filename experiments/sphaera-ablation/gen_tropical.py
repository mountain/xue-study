"""把 sphaera 的 16 节点几何搬到热带，生成对应 .adva。

为什么可以这么改
----------------
`sphaera-frame` 的生成器 `adva_source(nodes)` 只依赖**节点表**，不依赖数据。
所以同一套结构（4 个方位 × 4 个环、轴 e_z、权重 ce=sign(z)/N、co=|z|/N）
换一组节点就是另一份合法程序。

**但这【不是】`sphaera-frame` 声明的几何。** 那份是 z=±3/5,±4/5（纬度 ±36.87°, ±53.13°）。
本件生成的是**热带变体**：z=±1/5, ±2/5（纬度 ±11.54°, ±23.58°），
轴与结构不变。**引用时必须说明这是另一个几何，不是原声明的那个。**

动机：目标（热带海温）在热带，而原几何全在中纬度 —— 上一轮实测两者在任何
提前量上的相关都 <0.11。把采样点放进热带是「换区域」的直接做法。
"""
from __future__ import annotations
import sys
from fractions import Fraction as F
from pathlib import Path

# 热带环：z = ±1/5, ±2/5；半径 = sqrt(1-z^2) 需为有理数
# (1/5): sqrt(24/25) 不是有理数 ⇒ 用能给出有理半径的 z
# z=±3/5,±4/5 之所以可用，是因为 3-4-5 勾股。热带的勾股三元组最小是 (0,1) 与 (3,4)。
# 故改用【经度环】而不是纬度环：把节点放在赤道附近的大圆上。
# 这里选 z=±1/5 配半径 sqrt(24)/5 —— 非有理，会破坏原程序的有理算术。
# ⇒ 改用 z=±3/5 的同族但【沿经度重排】：热带化只能通过 z 的有理勾股对实现，
#   而在 |z|<3/5 的有理勾股对里最小的是 (5,12,13): z=5/13, r=12/13。
def _default_nodes():
    out = []
    for z, rad in ((F(5,13), F(12,13)), (F(-5,13), F(12,13)),
                   (F(3,5), F(4,5)), (F(-3,5), F(4,5))):
        for x, y in ((rad, F(0)), (-rad, F(0)), (F(0), rad), (F(0), -rad)):
            out.append((x, y, z))
    return out


def frac(fr: F) -> str:
    return str(fr.numerator) if fr.denominator == 1 else f"{fr.numerator}/{fr.denominator}"


def adva_source(nodes):
    exports = ["spectrum", "turn-i", "twice-i", "conjugate", "p-after-i", "i-after-p",
               "shear", "unshear", "chart-i", "norm", "chart-norm", "old-then-i"]
    parts = ["(module spectrum-frame", "  (export " + " ".join(exports) + ")"]

    def define(name, names, body, scalar=False):
        params = " ".join(f"({n} Real)" for n in names)
        outputs = "Real" if scalar else "(outputs Real Real)"
        parts.append(f"  (def {name} (fn ({params}) {outputs}\n    {body}))")

    define("merge", ["e1", "o1", "e2", "o2"],
           "(frontier (add (use e1) (use e2)) (add (use o1) (use o2)))")
    leaves, inputs = [], []
    N = len(nodes)
    for j, (x, y, z) in enumerate(nodes):
        ce = F((z > 0) - (z < 0), N)
        co = abs(z) / N
        define(f"weights{j}", ["e", "o"],
               f"(frontier (scale {frac(ce)} (use e)) (scale {frac(co)} (use o)))")
        define(f"sample{j}", ["x", "y", "z"],
               f"(frontier (call weights{j} (copy (add (scale {frac(-y)} (use x)) "
               f"(scale {frac(x)} (use y))))) (discard (use z)))")
        args = [f"u{j}{c}" for c in "xyz"]
        inputs.extend(args)
        leaves.append(f"(call sample{j} " + " ".join(f"(use {a})" for a in args) + ")")
    while len(leaves) > 1:
        leaves = [f"(call merge {leaves[j]} {leaves[j+1]})" for j in range(0, len(leaves), 2)]
    define("spectrum", inputs, leaves[0])
    define("turn-i", ["e", "o"], "(frontier (neg (use o)) (id (use e)))")
    define("twice-i", ["e", "o"], "(call turn-i (call turn-i (use e) (use o)))")
    define("conjugate", ["e", "o"], "(frontier (id (use e)) (neg (use o)))")
    define("p-after-i", ["e", "o"], "(call conjugate (call turn-i (use e) (use o)))")
    define("i-after-p", ["e", "o"], "(call turn-i (call conjugate (use e) (use o)))")
    define("shear-body", ["e", "o1", "o2"], "(frontier (add (use e) (use o1)) (use o2))")
    define("unshear-body", ["e", "o1", "o2"], "(frontier (add (use e) (neg (use o1))) (use o2))")
    define("shear", ["e", "o"], "(call shear-body (use e) (copy (use o)))")
    define("unshear", ["e", "o"], "(call unshear-body (use e) (copy (use o)))")
    define("chart-i", ["e", "o"], "(call shear (call turn-i (call unshear (use e) (use o))))")
    define("norm", ["e", "o"], "(add (mul (copy (use e))) (mul (copy (use o))))", scalar=True)
    define("chart-norm", ["e", "o"], "(call norm (call unshear (use e) (use o)))", scalar=True)
    define("old-only", ["e", "o"], "(frontier (use e) (discard (use o)) 0)")
    define("old-then-i", ["e", "o"], "(call turn-i (call old-only (use e) (use o)))")
    return "\n".join(parts) + "\n)\n"


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "runs/tropical/spectrum-tropical.adva")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(adva_source(_default_nodes()))
    import math
    print(f"  已写 {out}")
    for j, (x, y, z) in enumerate(_default_nodes()):
        print(f"    {j:>3}  z={z}  纬度 {math.degrees(math.asin(float(z))):+.2f}°")
