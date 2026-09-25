"""Prepare a local reviewable bundle; never connects to an Observable account."""
from pathlib import Path
import csv
import hashlib
import json
import math
import re
import shutil
import textwrap
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / "archive/observable-seasonal-v3"
OUT.mkdir(parents=True, exist_ok=True)
bundle = OUT / "climatetensor-annual-spectrum-v3.zip"
if bundle.exists():
    raise FileExistsError(bundle)

source = (HERE / "docs/annual-spectrum.html").read_text()
cells = ["# 网页迁移：按顺序创建以下 9 个单元\n\n"
         "适用 Observable Notebooks 2.0。先附加同名 `annual-check.json`，然后按各节注明的单元类型粘贴。"
         "下面是单元内容，不要把整个 Markdown 文件粘进一个 JavaScript 单元。\n"]
for i, match in enumerate(re.finditer(r'<script\b([^>]*)>(.*?)</script>', source, re.S), 1):
    language = re.search(r'type="([^"]+)"', match[1])[1]
    name, fence = {"module": ("JavaScript", "javascript"), "text/markdown": ("Markdown", "markdown"),
                   "application/x-tex": ("TeX", "tex")}[language]
    cells.append(f"## 单元 {i}：{name}\n\n```{fence}\n{textwrap.dedent(match[2]).strip()}\n```\n")
    if i == 8:
        (HERE / "calibration-cell.js").write_text(textwrap.dedent(match[2]).strip()+"\n")
(HERE / "cells.md").write_text("\n".join(cells))

contract = json.loads((ROOT / "experiments/typed-spectrum/annual-contract.json").read_text())
eps = contract["perturbation"]["amplitude"]
period = contract["perturbation"]["period_years"]
with (HERE / "docs/synthetic-annual.csv").open("w", newline="") as handle:
    writer = csv.writer(handle)
    writer.writerow(["idealized_year", "baseline", "additive", "amplitude_modulation", "phase_modulation", "training"])
    for i in range(contract["time"]["years"] * contract["time"]["samples_per_year"]):
        t = i / contract["time"]["samples_per_year"]
        phase, slow = 2*math.pi*t, math.cos(2*math.pi*t/period)
        baseline = math.cos(phase)+.3*math.sin(2*phase)
        writer.writerow([t, baseline, baseline+eps*slow, baseline+eps*slow*math.cos(phase),
                         math.cos(phase+eps*slow)+.3*math.sin(2*phase),
                         t < contract["seasonal_fit"]["training_years"]])

files = ["README.md", "cells.md", "calibration-cell.js", "package.json", "package-lock.json", "docs/annual-spectrum.html",
         "docs/annual-check.json", "docs/synthetic-annual.csv"]
for rel in files:
    target = OUT / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(HERE / rel, target)
shutil.copy2(ROOT / "archive/typed-spectrum-v1/annual-demo.html", OUT / "preview.html")
shutil.copy2(HERE / "docs/annual-check.json", OUT / "annual-check.json")
# The standalone preview links to the companion sphere demo, so include its files.
for rel in ["demo.html", "report.json", "synthetic.npz", "era5-representation.npz"]:
    shutil.copy2(ROOT / "archive/typed-spectrum-v1" / rel, OUT / rel)
pack = files+["preview.html", "annual-check.json", "demo.html", "report.json", "synthetic.npz", "era5-representation.npz"]
manifest = {"status": "local reviewable bundle; not uploaded to Observable", "notebook_kit": "2.6.4",
            "account_target": "@mountain", "annual_csv": {"rows": 384, "synthetic": True,
            "time_unit": "idealized equal-length year", "perturbation_period_years": period},
            "files": {p: {"bytes": (OUT/p).stat().st_size,
                           "sha256": hashlib.sha256((OUT/p).read_bytes()).hexdigest()} for p in pack}}
(OUT / "manifest.json").write_text(json.dumps(manifest, indent=2)+"\n")
with zipfile.ZipFile(bundle, "x", compression=zipfile.ZIP_DEFLATED) as zipped:
    for rel in pack+["manifest.json"]:
        zipped.write(OUT/rel, rel)
print(json.dumps({"bundle": str(bundle), "bytes": bundle.stat().st_size, "cells": len(cells)-1, "published": False}))
