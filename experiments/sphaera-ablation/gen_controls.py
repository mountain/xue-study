#!/usr/bin/env python3
"""生成两个单变量对照几何，并在【系数层】断言它们确实只动了一个变量。

证伪件（`docs/maintenance/2026-10-08-parity-falsification-north-only-nodes.md`）留下的
限制 #3：`north` 与 `tropical` 之间混着两处变化 —— 对径配对被撤掉，**且 z 取值集合也变了**
（少了 ±3/5、±5/13，多了 12/13、4/5）。所以那次读数不能干净地归给配对。

本脚本造两个对照，各自把 |z| 集合**钉死成与 north 完全相同**（5/13, 12/13, 3/5, 4/5）：

  south    16 节点，z = −(5/13, 12/13, 3/5, 4/5)。|z| 与节点数与方位都与 north 相同，
           只有【半球】相反；配对在两者里**都不存在** ⇒ north vs south 只动半球。
  paired8  32 节点，z = ±(5/13, 12/13, 3/5, 4/5)。|z| 集合与 north 完全相同，
           但**把对径副本加回来** ⇒ 配对恢复 ⇒ north vs paired8 只动配对。
           唯一附带变化是节点数 16→32；而方位加密造成的 16→32 已被 dense 实验证明无效。

程序层的系数关系（从 sphaera-frame 的生成器读出并在此断言）：
  E 系数 = sign(z)/N      O 系数 = |z|/N
故 south 的 O 系数多重集**必须与 north 逐值相同**（|z| 被钉死），E 系数**必须是 north 的取负**。
这条断言是本脚本的核心：它证明「只动一个变量」不是说法，是程序里的事实。
"""
from fractions import Fraction as F
from pathlib import Path
import re

from gen_tropical import adva_source

RINGS_NORTH = ((F(5, 13), F(12, 13)), (F(12, 13), F(5, 13)),
               (F(3, 5), F(4, 5)), (F(4, 5), F(3, 5)))

E_RE = re.compile(r"\(scale (-?\d+/\d+) \(use e\)\)")
O_RE = re.compile(r"\(scale (\d+/\d+) \(use o\)\)")


def cardinal(rings, negate=False):
    out = []
    for z, rad in rings:
        if negate:
            z = -z
        for x, y in ((rad, F(0)), (-rad, F(0)), (F(0), rad), (F(0), -rad)):
            out.append((x, y, z))
    return out


def paired(rings):
    """把每个环与它的对径副本都放进去 ⇒ 配对恢复。"""
    out = []
    for z, rad in rings:
        for zz in (z, -z):
            for x, y in ((rad, F(0)), (-rad, F(0)), (F(0), rad), (F(0), -rad)):
                out.append((x, y, zz))
    return out


def coeffs(text):
    return (sorted(F(s) for s in E_RE.findall(text)),
            sorted(F(s) for s in O_RE.findall(text)))


def main() -> int:
    north = cardinal(RINGS_NORTH)
    south = cardinal(RINGS_NORTH, negate=True)
    pair8 = paired(RINGS_NORTH)

    for name, n in (("north", north), ("south", south), ("paired8", pair8)):
        assert all(x * x + y * y + z * z == 1 for x, y, z in n), f"{name} 有非单位向量"
    assert all(z > 0 for _, _, z in north), "north 不全是北半球"
    assert all(z < 0 for _, _, z in south), "south 不全是南半球"
    assert len(north) == 16 and len(south) == 16 and len(pair8) == 32

    t_north = adva_source(north)
    t_south = adva_source(south)
    t_pair8 = adva_source(pair8)

    eN, oN = coeffs(t_north)
    eS, oS = coeffs(t_south)
    eP, oP = coeffs(t_pair8)

    # 核心断言一：south 的 O 系数与 north 逐值相同 ⇒ |z| 集合被钉死
    assert oS == oN, f"south 的 O 系数 {oS} != north 的 {oN} —— |z| 没被钉死"
    print(f"  ✓ south 与 north 的 O 系数【逐值相同】：{sorted(set(oN), key=str)}"
          f"  ⇒ |z| 集合同为 {{5/13, 12/13, 3/5, 4/5}}")

    # 核心断言二：south 的 E 系数是 north 的取负 ⇒ 只翻了半球
    assert eS == sorted(-v for v in eN), f"south 的 E 系数 {eS} 不是 north {eN} 的取负"
    assert all(v < 0 for v in eS), "south 的 sign(z) 不全是 −1"
    print(f"  ✓ south 的 E 系数是 north 的取负（{set(eN)} → {set(eS)}）⇒ 只动了半球")

    # 核心断言三：paired8 恢复了配对（E 系数同时有正有负），|z| 结构仍是同一批值 ×2
    assert any(v > 0 for v in eP) and any(v < 0 for v in eP), "paired8 没有恢复配对"
    assert set(oP) == {v / 2 for v in set(oN)}, f"paired8 的 O 系数 {set(oP)} 不是 north 的一半"
    print(f"  ✓ paired8 的 E 系数同时有正负（配对已恢复），O 系数 = north 的 1/2（N 由 16 → 32）")

    out = Path("runs")
    for tag, text, n in (("south", t_south, south), ("paired8", t_pair8, pair8)):
        d = out / tag
        d.mkdir(parents=True, exist_ok=True)
        (d / f"spectrum-{tag}.adva").write_text(text)
        print(f"  已写 {d}/spectrum-{tag}.adva   {len(n)} 节点")

    # north 的程序不该被本脚本改动：只读检查
    ref = out / "north" / "spectrum-north.adva"
    if ref.exists():
        assert ref.read_text() == t_north, "north 的程序与 regen 不一致 —— 生成器漂了"
        print("  ✓ north 的程序与本次 regen 逐字节一致（生成器没漂）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
