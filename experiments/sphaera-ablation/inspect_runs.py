#!/usr/bin/env python3
"""看各 run 目录里到底存了什么：eo 文件、request 的节点数、程序里的 E 系数。

不猜 —— 「run-001 是哪个几何」这类问题必须从 request 与程序里读出来。
"""
import json
import re
from fractions import Fraction
from pathlib import Path

import numpy as np

E_RE = re.compile(r"\(scale (-?\d+/\d+) \(use e\)\)")
NODE_RE = re.compile(r"\(use (u\d+[xyz])\)")

for d in ("run-001", "l250", "l500", "l850", "tropical", "dense",
          "north", "south", "north32", "paired8"):
    base = Path(f"runs/{d}")
    eos = sorted(base.glob("eo*.npz"))
    reqs = sorted(base.glob("req*.json")) + sorted(base.glob("request*.json"))
    advas = sorted(base.glob("*.adva"))
    n_in = None
    if reqs:
        j = json.loads(reqs[0].read_text())
        cases = j["cases"] if isinstance(j, dict) and "cases" in j else j
        inp = cases[0]["inputs"]
        n_in = len(inp)
    nodes = None
    esign = None
    if advas:
        txt = advas[0].read_text()
        nodes = len(set(NODE_RE.findall(txt))) // 3 or None
        e = [Fraction(s) for s in E_RE.findall(txt)]
        if e:
            esign = ("全正" if all(v > 0 for v in e) else
                     "全负" if all(v < 0 for v in e) else "有正有负")
            nodes = nodes or len(e)
    print(f"  {d:9s} eo={','.join(p.name for p in eos) or '无':16s} "
          f"req输入={n_in if n_in is not None else '无':>4} "
          f"=>{n_in//3 if n_in else '?':>3}节点  "
          f"adva={advas[0].name if advas else '无':22s} "
          f"E系数={esign or '?'}  文件={sorted(p.name for p in base.iterdir())[:5]}")
