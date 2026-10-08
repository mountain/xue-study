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
# 高纬环：与 declared 同一批 |z|（3/5, 4/5），即【不下探到 5/13】
RINGS_HI = ((F(3, 5), F(4, 5)), (F(4, 5), F(3, 5)))

E_RE = re.compile(r"\(scale (-?\d+/\d+) \(use e\)\)")
O_RE = re.compile(r"\(scale (\d+/\d+) \(use o\)\)")


# 四个基本方位 + 四个勾股对角方位（与 dense / north32 的方位集合一致）
AZ4 = ((F(1), F(0)), (F(-1), F(0)), (F(0), F(1)), (F(0), F(-1)))
AZ8 = AZ4 + ((F(4, 5), F(3, 5)), (F(-4, 5), F(-3, 5)),
             (F(3, 5), F(4, 5)), (F(-3, 5), F(-4, 5)))


def ring_nodes(rings, negate=False, azimuths=AZ4):
    """把 rings 展开成节点；azimuths 里的 (a, b) 是相对半径的比例。"""
    out = []
    for z, rad in rings:
        if negate:
            z = -z
        for a, b in azimuths:
            out.append((a * rad, b * rad, z))
    return out


def paired(rings, azimuths=AZ4):
    """把每个环与它的对径副本都放进去 ⇒ 配对恢复。

    **顺序必须与 extract_nodes.nodes("paired8") 逐节点一致**：request 是按索引
    u{i}x/u{i}y/u{i}z 供数的，顺序错了就会把风值喂给错的节点。
    曾把这里重构成 `ring_nodes(...) + ring_nodes(negate=True, ...)`，顺序由
    环内交织（+,−,+,−, …）变成先全正后全负 —— 与 extract_nodes 不再一致。
    下面 main() 里的交叉断言就是为这类漂移准备的。
    """
    out = []
    for z, rad in rings:
        for zz in (z, -z):
            for a, b in azimuths:
                out.append((a * rad, b * rad, zz))
    return out


def coeffs(text):
    return (sorted(F(s) for s in E_RE.findall(text)),
            sorted(F(s) for s in O_RE.findall(text)))


def main() -> int:
    north = ring_nodes(RINGS_NORTH)
    south = ring_nodes(RINGS_NORTH, negate=True)
    pair8 = paired(RINGS_NORTH)
    north32 = ring_nodes(RINGS_NORTH, azimuths=AZ8)
    northhi = ring_nodes(RINGS_HI, azimuths=AZ8)

    for name, n in (("north", north), ("south", south), ("paired8", pair8),
                    ("north32", north32), ("northhi", northhi)):
        assert all(x * x + y * y + z * z == 1 for x, y, z in n), f"{name} 有非单位向量"
    assert all(z > 0 for _, _, z in north), "north 不全是北半球"
    assert all(z < 0 for _, _, z in south), "south 不全是南半球"
    assert len(north) == 16 and len(south) == 16 and len(pair8) == 32
    assert len(north32) == 32 and len(northhi) == 16

    t_north = adva_source(north)
    t_south = adva_source(south)
    t_pair8 = adva_source(pair8)
    t_n32 = adva_source(north32)
    t_hi = adva_source(northhi)

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

    # 环数对照的核心断言：north32 与 paired8 的 |z| 多重集【逐值逐重数相同】，
    # 节点数也相同（32）⇒ 两者只差配对。
    def zmult(n):
        c = {}
        for _, _, z in n:
            c[abs(z)] = c.get(abs(z), 0) + 1
        return c

    assert zmult(north32) == zmult(pair8), f"|z| 多重集不同：{zmult(north32)} vs {zmult(pair8)}"
    assert len(north32) == len(pair8) == 32
    assert all(z > 0 for _, _, z in north32), "north32 里有非北半球节点"
    e32, o32 = coeffs(t_n32)
    assert all(v > 0 for v in e32), "north32 的 sign(z) 不全是 +1（配对没被撤干净）"
    assert set(o32) == {v / 2 for v in set(oN)}, f"north32 的 O 系数 {set(o32)} 不是 north 的一半"
    print(f"  ✓ north32 vs paired8：节点数同为 32，|z| 多重集逐值逐重数相同 "
          f"{ {str(k): v for k, v in sorted(zmult(north32).items())} }")
    print(f"      north32 E 系数全正 {set(e32)}（无配对）；paired8 E 系数有正有负 {set(eP)}（有配对）")

    # 2×2 的补格断言：northhi 与 declared 的 |z| 多重集相同、节点数相同，只差配对，
    # 且两者【都不下探到 |z| = 5/13】。
    DECLARED = paired(RINGS_HI)              # declared 预设：z = ±3/5, ±4/5，8 环 × 4 方位 = 16 节点
    assert len(northhi) == len(DECLARED) == 16
    assert zmult(northhi) == zmult(DECLARED), f"{zmult(northhi)} vs {zmult(DECLARED)}"
    assert min(abs(z) for _, _, z in northhi) > F(5, 13), "northhi 竟然下探到了 5/13"
    assert min(abs(z) for _, _, z in DECLARED) > F(5, 13)
    ehi, ohi = coeffs(t_hi)
    assert all(v > 0 for v in ehi), "northhi 的 sign(z) 不全是 +1"
    print(f"  ✓ northhi vs declared：节点数同为 16，|z| 多重集相同 "
          f"{ {str(k): v for k, v in sorted(zmult(northhi).items())} }，都不下探到 5/13")
    print(f"      唯一差别：northhi 无配对（E 系数 {set(ehi)}）；declared 有配对")

    # 交叉断言（本该一开始就有）：生成器的节点表必须与 extract_nodes.nodes() 逐节点一致。
    # request 按索引 u{i}x/u{i}y/u{i}z 供数，顺序漂移 = 把风值喂给错的节点，而且不会报错。
    import extract_nodes
    for tag, mine in (("north", north), ("south", south), ("paired8", pair8),
                      ("north32", north32), ("northhi", northhi)):
        theirs = [(float(x), float(y), float(z)) for x, y, z in extract_nodes.nodes(tag)]
        minef = [(float(x), float(y), float(z)) for x, y, z in mine]
        assert len(minef) == len(theirs), f"{tag}: 节点数 {len(minef)} vs {len(theirs)}"
        for i, (a, b) in enumerate(zip(minef, theirs)):
            # 容差只放浮点表示差（Fraction→float vs 直接浮点，差 1 ULP，如
            # 0.48 vs 0.4800000000000001）。换序造成的差是 0.1~1 量级，仍会被抓到。
            d = max(abs(u - v) for u, v in zip(a, b))
            assert d < 1e-12, (f"{tag}: 第 {i} 个节点差 {d:.3g}：{a} vs {b} —— "
                               f"生成器与 extract_nodes 漂移了，request 会把风值喂给错的节点")
    print("  ✓ 五个几何的节点表与 extract_nodes.nodes() 逐节点一致（顺序也一致）")

    out = Path("runs")
    for tag, text, n in (("south", t_south, south), ("paired8", t_pair8, pair8),
                         ("north32", t_n32, north32), ("northhi", t_hi, northhi)):
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
