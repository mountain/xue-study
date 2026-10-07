"""机械提取 docs/ 下全部「不得」条目，供 `docs/prohibitions.md` 的归类表复核。

为什么要有这一件
----------------
`docs/prohibitions.md` 把 40 条禁则按失效模式归了类。**归类是加工，原文才是判据** ——
所以加工必须可复核：任何人跑一遍本脚本，应当得到同一批 40 条原文。

本脚本**不做归类**（那是人的判断），只做提取与计数，并打印每条出处。
归类若与原文冲突，以原文为准。

用法：
  python3 scripts/collect_prohibitions.py            # 打印全部条目
  python3 scripts/collect_prohibitions.py --count    # 只报计数与分布
"""

from __future__ import annotations

import argparse
import glob
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def collect():
    rows = []
    # EXCLUDE THE DERIVED REGISTER.  `docs/prohibitions.md` is the OUTPUT of
    # this extraction; scanning it makes the register feed on itself -- the
    # first run of this script reported 74 rules where there are 41, because
    # its own 33 table rows counted as sources.
    skip = {"prohibitions"}
    paths = [p for p in (sorted(glob.glob(str(ROOT / "docs/maintenance/*.md")))
                         + sorted(glob.glob(str(ROOT / "docs/*.md"))))
             if Path(p).stem not in skip]
    for p in paths:
        src = Path(p).stem
        for line in Path(p).read_text(encoding="utf-8").splitlines():
            if "不得" not in line:
                continue
            t = re.sub(r"^\s*[-*\d.]+\s*", "", line).strip()
            t = t.replace("**", "")
            # Drop headings and fragments too short to carry a rule.
            if len(t) <= 10 or t.startswith("#"):
                continue
            rows.append((src, t))
    # Same rule quoted twice in one file is one rule.
    seen, out = set(), []
    for s, t in rows:
        k = (s, t[:60])
        if k in seen:
            continue
        seen.add(k)
        out.append((s, t))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", action="store_true")
    args = ap.parse_args()

    rows = collect()
    if args.count:
        print(f"  共 {len(rows)} 条，跨 {len(set(s for s, _ in rows))} 个文件")
        for f, n in Counter(s for s, _ in rows).most_common():
            print(f"    {f:<48}{n:>3} 条")
        return 0

    for i, (s, t) in enumerate(rows, 1):
        print(f"{i:>3}. [{s}]")
        print(f"     {t[:230]}")
    print(f"\n  共 {len(rows)} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
