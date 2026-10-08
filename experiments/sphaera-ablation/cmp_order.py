#!/usr/bin/env python3
"""按函数下标结构化解析 .adva，打印每个节点的 (E系数, O系数, y缩放)。

上一版把两个独立正则的结果 zip 起来 —— 下标根本没对齐，打出过 y=4/5 配 o=3/104
这种自相矛盾的行（|z|=12/13 的半径应是 5/13，不是 4/5）。检查器自己错的时候，
它给的「证据」比没有更坏。这一版按 weightsK / sampleK 的 K 配对。
"""
import re
import sys
from fractions import Fraction

W = re.compile(r"\(def weights(\d+) \(fn.*?\(scale (-?\d+/\d+) \(use e\)\)"
               r" \(scale (\d+/\d+) \(use o\)\)", re.S)
S = re.compile(r"\(def sample(\d+) \(fn.*?\(scale (-?\d+(?:/\d+)?) \(use y\)\)", re.S)


def parse(path):
    txt = open(path).read()
    w = {int(k): (Fraction(e), Fraction(o)) for k, e, o in W.findall(txt)}
    s = {int(k): Fraction(y) for k, y in S.findall(txt)}
    assert set(w) == set(s), f"weights 与 sample 的下标不一致: {sorted(set(w)^set(s))}"
    out = []
    for k in sorted(w):
        e, o = w[k]
        out.append((k, e, o, s[k]))
    return out


def main():
    a, b = sys.argv[1], sys.argv[2]
    na, nb = len(parse(a)), len(parse(b))
    print(f"  {a}: {na} 节点    {b}: {nb} 节点")
    pa, pb = parse(a), parse(b)
    # E 系数 = sign(z)/N，O 系数 = |z|/N ⇒ 由二者可反解 sign(z) 与 |z|
    def key(t):
        _, e, o, y = t
        return (str(e), str(o), str(y))
    diff = [i for i in range(min(na, nb)) if key(pa[i]) != key(pb[i])]
    print(f"  逐下标不同: {len(diff)} / {min(na,nb)}  {diff[:8]}")
    if diff:
        print(f"  {'i':>3s}  {'ref E':>7s} {'ref O':>7s} {'ref y':>7s}   {'loc E':>7s} {'loc O':>7s} {'loc y':>7s}")
        for i in diff[:10]:
            _, e1, o1, y1 = pa[i]; _, e2, o2, y2 = pb[i]
            print(f"  {i:3d}  {str(e1):>7s} {str(o1):>7s} {str(y1):>7s}   {str(e2):>7s} {str(o2):>7s} {str(y2):>7s}")
    print(f"  (E,O,y) 三元组多重集一致: {sorted(map(key,pa)) == sorted(map(key,pb))}")


main()
