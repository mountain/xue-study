#!/usr/bin/env python3
"""逐节点核对 declared 与 tropical 是否只差 |z| 对。

「结构相同、只换一组数」不能靠几何描述说了算。这里从两份 .adva 里读出每个节点的
(E 系数, O 系数, 方位模式) ：

  E 系数 = sign(z)/N      O 系数 = |z|/N
  方位模式 = 切线投影里半径落在哪个坐标上（由 sample 行的
             `(add (scale A (use x)) (scale B (use y)))` 读出）

若两边的【符号序列】与【方位模式序列】完全相同、节点数相同、每个 |z| 的重数相同，
而 |z| 的取值集合不同，那才是单变量对照。

前两版都栽在正则上（多写一个右括号 / 用 str.replace 打补丁时转义没对上），
故本版把实际格式抄进注释里：
  (def sample0 (fn ((x Real) (y Real) (z Real)) (outputs Real Real)
    (frontier (call weights0 (copy (add (scale 0 (use x)) (scale 4/5 (use y))))) (discard (use z)))))
"""
import re
from collections import Counter
from fractions import Fraction
from pathlib import Path

W = re.compile(r"\(def weights(\d+) \(fn.*?\(scale (-?\d+(?:/\d+)?) \(use e\)\)"
               r" \(scale (\d+(?:/\d+)?) \(use o\)\)", re.S)
S = re.compile(r"\(def sample(\d+) \(fn.*?"
               r"\(add \(scale (-?\d+(?:/\d+)?) \(use x\)\)"
               r" \(scale (-?\d+(?:/\d+)?) \(use y\)\)", re.S)
N = 16


def read_nodes(path: Path):
    txt = path.read_text()
    w = {int(k): (Fraction(e), Fraction(o)) for k, e, o in W.findall(txt)}
    s = {int(k): (Fraction(x), Fraction(y)) for k, x, y in S.findall(txt)}
    missing = sorted(set(w) - set(s))
    extra = sorted(set(s) - set(w))
    assert not missing and not extra, f"weights/sample 下标不配对: 缺 {missing} 多 {extra}"
    out = []
    for k in sorted(w):
        e, o = w[k]
        x, y = s[k]
        pat = ("x" if x != 0 else "") + ("y" if y != 0 else "")
        out.append((e, abs(o) * N, pat))
    return out


def main() -> int:
    a = read_nodes(Path("runs/declared/spectrum-declared.adva"))
    b = read_nodes(Path("runs/tropical/spectrum-tropical.adva"))
    print(f"  declared {len(a)} 节点   tropical {len(b)} 节点")
    assert len(a) == len(b) == 16, "节点数不同 ⇒ 不是单变量对照"

    pa = [(e > 0, pat) for e, _, pat in a]
    pb = [(e > 0, pat) for e, _, pat in b]
    assert pa == pb, f"符号/方位模式序列不同 ⇒ 不是单变量对照\n   declared {pa}\n   tropical {pb}"
    print(f"  符号+方位模式序列相同（各 16 项全同），前 6 项: {pa[:6]}")

    za = sorted({z for _, z, _ in a})
    zb = sorted({z for _, z, _ in b})
    ca, cb = Counter(z for _, z, _ in a), Counter(z for _, z, _ in b)
    print(f"  declared 的 |z| {[str(v) for v in za]}  重数 {[v for _, v in sorted(ca.items())]}")
    print(f"  tropical 的 |z| {[str(v) for v in zb]}  重数 {[v for _, v in sorted(cb.items())]}")
    print(f"  共有 {[str(v) for v in sorted(set(za) & set(zb))]}；"
          f"只差 {[str(v) for v in sorted(set(za) ^ set(zb))]}")
    assert set(ca.values()) == set(cb.values()) == {8}, "重数不同 ⇒ 环数或方位数不同"
    assert za != zb, "|z| 集合相同 ⇒ 没有可比的差异"

    print()
    print("  结论：节点数相同、符号序列相同、方位模式序列相同、每个 |z| 的重数相同（各 8 次）；")
    print("        唯一差别是 |z| 的取值对 {3/5,4/5} → {5/13,3/5}，即纬度整体下移一档。")
    print("        ⇒ declared vs tropical 【是】单变量对照。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
