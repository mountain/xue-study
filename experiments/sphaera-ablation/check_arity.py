#!/usr/bin/env python3
"""核对每个几何的 request 真的给足了程序要的输入数。

起因两层：
  1. extract_nodes.py:138 把「48 个输入」写成了【硬编码字面量】，paired8（应需 96）也印 48；
     那个标签永远不可能发现不匹配。
  2. 本脚本第一版用 `(use \\w+)` 收集输入名，把 merge 的参数 e1/o1/e2/o2 也算进去了，
     于是每个几何都「不一致」，差恒为 4 —— 是【检查器】错，不是数据错。

现在只认 `u<数字><x|y|z>` 形式的节点输入名，且要求 req 的 case 里真的带这个键。
"""
import json
import re
from pathlib import Path

NODE_IN = re.compile(r"\(use (u\d+[xyz])\)")


def main() -> int:
    bad = 0
    for tag in ("tropical", "dense", "north", "south", "paired8"):
        prog = Path(f"runs/{tag}/spectrum-{tag}.adva")
        req = Path(f"runs/{tag}/req.json")
        if not (prog.exists() and req.exists()):
            print(f"  {tag:9s} 缺文件，跳过")
            continue
        names = sorted(set(NODE_IN.findall(prog.read_text())))
        j = json.loads(req.read_text())
        cases = j["cases"] if isinstance(j, dict) and "cases" in j else j
        inp = cases[0]["inputs"]
        keys = set(inp.keys()) if isinstance(inp, dict) else set(range(len(inp)))
        missing = sorted(set(names) - ({str(k) for k in keys}))
        ok = len(names) == len(keys) and not missing and len(cases) == len({c["id"] for c in cases})
        bad += 0 if ok else 1
        print(f"  {tag:9s} 程序节点输入 {len(names):3d}   req 提供 {len(keys):3d}   "
              f"case {len(cases)}   缺 {len(missing)}   {'一致' if ok else '*** 不一致 ***'}")
        if missing:
            print(f"      req 里没有这些键（前 6）: {missing[:6]}")
    print("  ✓ 全部 arity 一致" if not bad else f"  {bad} 个几何 arity 对不上")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
