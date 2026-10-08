#!/bin/bash
# 三个层次各跑一遍：抽取 → 原生求值 → 消融
set -u
cd "$(dirname "$0")"
PY=~/climatetensor-env/bin/python
SRC=~/xue-study/experiments/sphaera-frame/runs/run-001/spectrum.adva
for L in 250 500 850; do
  echo "==================== ${L} hPa ===================="
  D=runs/l${L}
  mkdir -p "$D"
  $PY extract_nodes.py --level $L --out "$D/request.json" 2>&1 | grep -E "自带网格|已写|声明纬度" | head -3
  rm -f "$D/native.json"
  ./target/debug/sphaera-frame-probe "$SRC" "$D/request.json" "$D/native.json" || { echo "  求值失败"; continue; }
  $PY - "$D" <<'PYEOF'
import json, sys, numpy as np
d = sys.argv[1]
j = json.load(open(f"{d}/native.json"))
ev = [e for e in j["evaluations"] if e["function"] == "spectrum"]
res = np.array([e["result"]["values"] for e in ev], float)
np.savez(f"{d}/eo.npz", E=res[:,0], O=res[:,1], months=np.array([e["id"] for e in ev]))
print(f"  原生 {len(ev)} 次求值  E sd {res[:,0].std():.5f}  O sd {res[:,1].std():.5f}  corr {np.corrcoef(res[:,0],res[:,1])[0,1]:+.4f}")
PYEOF
  $PY ablate.py --eo "$D/eo.npz" 2>&1 | grep -E "^  M[0-4]|主判据|次判据|corr 0|RMSE 0" | head -12
done
