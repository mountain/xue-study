"""把方位由 4 个加密到 8 个 —— 但只能加密到【勾股角】上。

有理算术的第二个约束
--------------------
单位圆上的有理点是 (x,y)=((1-t²)/(1+t²), 2t/(1+t²))，t 有理。故方位角只能取
2·atan(t)：0°(t=0)、36.87°(t=1/3)、53.13°(t=1/2)、90°(t=1)…… **均匀加密需要 √2，不合法。**

本件取 8 个方位：4 个基本方位 + 4 个勾股对角 (±4/5,±3/5)、(±3/5,±4/5)。
这不是均匀加密，是**在合法集合内能取到的最自然的一档**。这个不均匀性本身就是结果的一部分。
"""
from __future__ import annotations
import sys, math
from fractions import Fraction as F
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from gen_tropical import adva_source

RINGS = ((F(5, 13), F(12, 13)), (F(-5, 13), F(12, 13)),
         (F(3, 5), F(4, 5)), (F(-3, 5), F(4, 5)))

def azimuths(rad):
    return [(rad, F(0)), (-rad, F(0)), (F(0), rad), (F(0), -rad),
            (F(4, 5) * rad, F(3, 5) * rad), (F(-4, 5) * rad, F(-3, 5) * rad),
            (F(3, 5) * rad, F(4, 5) * rad), (F(-3, 5) * rad, F(-4, 5) * rad)]

NODES = []
for z, rad in RINGS:
    for x, y in azimuths(rad):
        NODES.append((x, y, z))

if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(adva_source(NODES))
    print(f"  已写 {out}   {len(NODES)} 个节点")
    for j, (x, y, z) in enumerate(NODES):
        print(f"    {j:>3}  lat {math.degrees(math.asin(float(z))):+6.2f}°  "
              f"lon {math.degrees(math.atan2(float(y), float(x))):+7.2f}°")
