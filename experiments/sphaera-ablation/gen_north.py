#!/usr/bin/env python3
"""生成证伪几何：四个环全取北半球 ⇒ sign(z) 恒为 +1 ⇒ E 退化为纯水平项。

见 docs/maintenance/2026-10-08-parity-falsification-north-only-nodes.md。
环的取法与 tropical 不同：南半球的 ±5/13、±3/5 去掉后，可用的 |z| 只剩
≥ 5/13 的勾股值，故补入 12/13 与 4/5（半径 5/13、3/5）。
所以这不是「tropical 去掉一半」，而是一个不同的节点集 —— 差异不能全部归给对径配对。
"""
from fractions import Fraction as F
from pathlib import Path

from gen_tropical import adva_source

# (z, 半径) —— 四个环全部在北半球，且都是勾股合法值
RINGS = ((F(5, 13), F(12, 13)), (F(12, 13), F(5, 13)),
         (F(3, 5), F(4, 5)), (F(4, 5), F(3, 5)))


def nodes():
    out = []
    for z, rad in RINGS:
        for x, y in ((rad, F(0)), (-rad, F(0)), (F(0), rad), (F(0), -rad)):
            out.append((x, y, z))
    return out


def main() -> int:
    n = nodes()
    assert len(n) == 16, len(n)
    assert all(z > 0 for _, _, z in n), "有非北半球的节点"
    assert all(x * x + y * y + z * z == 1 for x, y, z in n), "不是单位向量"
    out = Path("runs/north")
    out.mkdir(parents=True, exist_ok=True)
    text = adva_source(n)
    assert "(scale -1/16 (use e))" not in text, "出现了负的 sign(z) 系数，配对没被撤掉"
    (out / "spectrum-north.adva").write_text(text)
    print(f"  已写 {out}/spectrum-north.adva   {len(n)} 节点，z 全为正，且程序里无 -1/16")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
