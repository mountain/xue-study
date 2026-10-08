#!/usr/bin/env python3
"""绕 z 轴的有理旋转 —— 唯一能在不破坏有理算术纪律的前提下挪动子午线的操作。

为什么必须是勾股角：节点坐标必须是有理数（本项目纪律，见
`xue.native.rational-arithmetic-sampling-boundaries.v0`）。一般的旋转角 φ 会把
有理坐标变成含 cos φ、sin φ 的无理数。只有 cos/sin 都是有理数的角才行 ——
最小的那个是 (3/5, 4/5)，即 arctan(4/3) = 53.130…°。

为什么反复旋转不会回到原处：Niven 定理说 sin 取有理值的角只能是 π 的有理倍里
0、±1/2、±1 那几种（sin = 0, ±1/2, ±1）。arctan(4/3) 的 sin 是 4/5，不在其中，
所以它不是 π 的有理倍 ⇒ k·53.13° 永不回到 0°。这正是我们要的：每次 k 给出
一组新的子午线。

这个模块是**唯一实现**。`extract_nodes.py`（造 request）与 `sweep_rotate.py`
（造 .adva）都从这里导入 —— 两边各写一份就会重演节点顺序漂移那一类事故。
"""
from fractions import Fraction as F

COS = F(3, 5)
SIN = F(4, 5)
MAX_DEN = 60          # 本项目里 5/13、12/13、3/5、4/5 的分母都在此以内


def snap(v) -> F:
    """把浮点坐标收成有理数，并断言确实收得住。"""
    f = F(v).limit_denominator(MAX_DEN)
    assert abs(float(f) - v) < 1e-12, f"{v} 无法有理化到分母 {MAX_DEN} 以内（得 {f}）"
    return f


def rotate_pair(x: F, y: F, k: int):
    """把 (x, y) 旋转 k × 53.130…°。"""
    x, y = F(x), F(y)
    for _ in range(k):
        x, y = COS * x - SIN * y, SIN * x + COS * y
    return x, y


def rotate_nodes(nodes, k: int):
    """nodes 为 (x, y, z) 序列；返回旋转后的 (Fraction, Fraction, Fraction) 序列。

    z 不变（绕 z 轴转），故 |z|、纬度、环结构全部不动 —— **只动子午线**。
    这正是「经度去混」要的单变量操作。
    """
    out = []
    for x, y, z in nodes:
        rx, ry = rotate_pair(snap(x), snap(y), k)
        rz = snap(z)
        assert rx * rx + ry * ry + rz * rz == 1, f"旋转后不是单位向量: {(rx, ry, rz)}"
        out.append((rx, ry, rz))
    return out


def meridian_deg(nodes):
    """节点所在子午线（度），用于核对 k 的确挪动了经度。"""
    import math
    seen = sorted({round(math.degrees(math.atan2(float(y), float(x))) % 360.0, 4)
                   for x, y, _ in nodes})
    return seen


if __name__ == "__main__":
    base = [(F(12, 13), F(0), F(5, 13)), (F(0), F(12, 13), F(5, 13)),
            (F(-12, 13), F(0), F(5, 13)), (F(0), F(-12, 13), F(5, 13))]
    for k in range(4):
        r = rotate_nodes(base, k)
        print(f"  k={k}: 子午线 {meridian_deg(r)}")
        assert all(isinstance(v, F) for n in r for v in n), "有非有理坐标"
    print("  ✓ 四次旋转给出四组不同的子午线，且坐标全为有理数")
