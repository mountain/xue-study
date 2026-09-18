"""Separate representativeness error from model error, by measuring it directly.

THE PROBLEM
-----------
"GFS tmp2m against 5,354 stations: median -0.10 K, sd 2.17" is not a statement
about the model.  That 2.17 K contains at least four things:

    instrument error        ~0.5 K, declared (WMO/CIMO)
    representativeness      a 0.25 deg cell is ~28 km; a station is a point
    model error             the forecast being wrong about the cell's mean
    timing / sampling       the observation is not at the frame's valid instant

Scoring against the instrument's 0.5 K makes the model look broken; scoring
against 2.17 K makes it look fine.  Both verdicts are about the choice, not the
model.  So the terms have to be measured rather than assumed.

HOW REPRESENTATIVENESS IS MEASURED HERE
---------------------------------------
Two stations inside the SAME model cell see the SAME model value.  Any
difference between what they report is therefore not the model's doing -- it is
the spread of the real atmosphere inside one cell, plus each instrument's own
error.  So:

    var(within-cell station pair) = var(representativeness) + 2*var(instrument)

Stations must be compared AT THE SAME TIME.  Comparing a 09Z report with a 12Z
one measures the diurnal cycle, which is several kelvin and would swamp
everything.  Observations are therefore grouped by (cell, hour) and only
same-hour pairs are used.

THE LIMIT OF THIS ESTIMATE, STATED UP FRONT
-------------------------------------------
Airports cluster near cities. Two stations in one 0.25 deg cell are typically a
few km apart, not spread across the full ~28 km.  So this measures the
variability of the cell's INHABITED CORNER, and is a LOWER BOUND on the
representativeness error of the cell as a whole.  It is a floor, not the value.

Usage:
  python3 scripts/representativeness.py [--cell 0.25] [--json /tmp/repr.json]
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DECLARED_SIGMA_K = 0.5          # WMO/CIMO synoptic temperature
F_ICAO, F_TIME, F_T, F_LAT, F_LON = 0, 4, 5, 1, 2


def haversine_km(a_lat, a_lon, b_lat, b_lon) -> float:
    r = 6371.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp = p2 - p1
    dl = math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", default=str(ROOT / "archive"))
    ap.add_argument("--cell", type=float, default=0.25,
                    help="model cell size in degrees (GFS pgrb2.0p25 = 0.25)")
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    # cell -> hour -> station key -> (lat, lon, T)
    cells = defaultdict(lambda: defaultdict(dict))
    n_obs = 0
    for f in sorted(glob.glob(str(Path(args.archive) / "airport" / "*" / "index"))):
        d = json.loads(Path(f).read_text())
        for r in d.get("stations", []):
            if len(r) <= 12 or r[F_T] is None or not r[F_TIME]:
                continue
            n_obs += 1
            lat, lon = r[F_LAT], r[F_LON]
            # The model grid runs north-to-south from +90 and east from -180.
            row = math.floor((90.0 - lat) / args.cell)
            col = math.floor((lon + 180.0) / args.cell)
            hour = r[F_TIME][:13]          # YYYY-MM-DDTHH
            cells[(row, col)][hour][r[F_ICAO]] = (lat, lon, float(r[F_T]))

    diffs, sep = [], []
    n_cells_multi = 0
    for (row, col), hours in cells.items():
        got = False
        for hour, st in hours.items():
            if len(st) < 2:
                continue
            got = True
            vals = list(st.values())
            for i in range(len(vals)):
                for j in range(i + 1, len(vals)):
                    diffs.append(vals[i][2] - vals[j][2])
                    sep.append(haversine_km(vals[i][0], vals[i][1],
                                            vals[j][0], vals[j][1]))
        if got:
            n_cells_multi += 1

    if not diffs:
        print("  同一格点同一时刻没有成对测站，无法估计")
        return 1

    # var(difference) = 2 * var(single station's deviation), and that deviation
    # is representativeness + instrument.
    var_diff = statistics.variance(diffs)
    var_one = var_diff / 2.0
    repr_plus_inst = math.sqrt(var_one)
    repr_only = math.sqrt(max(var_one - DECLARED_SIGMA_K ** 2, 0.0))

    print(f"  观测 {n_obs} 条；同格点同时刻有成对测站的格点 {n_cells_multi} 个")
    print(f"  同格点同时刻测站对 n = {len(diffs)}")
    print(f"  测站间距 中位 {statistics.median(sep):.2f} km  "
          f"P90 {sorted(sep)[int(len(sep)*0.9)]:.2f} km  最大 {max(sep):.2f} km")
    print(f"  格点尺寸 {args.cell}° ≈ {args.cell*111:.0f} km")
    print()
    print(f"  同格点同时刻温差: 中位 {statistics.median(diffs):+.2f} K  "
          f"sd {math.sqrt(var_diff):.2f} K")
    print(f"  → 单站偏差 sd = {repr_plus_inst:.2f} K  （= 代表性 + 仪器）")
    print(f"  → 扣掉仪器 {DECLARED_SIGMA_K} K 后，代表性 sd = {repr_only:.2f} K")
    print()
    print(f"  === 三项分解（以本会话实测的总散布 sd 2.14 K 为总量）===")
    total = 2.14
    model_only = math.sqrt(max(total ** 2 - repr_only ** 2 - DECLARED_SIGMA_K ** 2, 0.0))
    print(f"    总散布         {total:.2f} K")
    print(f"    代表性(实测下限) {repr_only:.2f} K  ({100*repr_only**2/total**2:.0f}% 的方差)")
    print(f"    仪器(declared)  {DECLARED_SIGMA_K:.2f} K  ({100*DECLARED_SIGMA_K**2/total**2:.0f}%)")
    print(f"    模式(余项)      {model_only:.2f} K  ({100*model_only**2/total**2:.0f}%)")
    print()
    print("  边界：机场集中在大城市，同格点两站通常相距几公里而非横跨整个格点，")
    print(f"  实测间距中位 {statistics.median(sep):.1f} km。**所以这是下限，不是该格点的真实代表性误差。**")

    if args.json:
        Path(args.json).write_text(json.dumps({
            "cell_deg": args.cell, "n_pairs": len(diffs), "n_obs": n_obs,
            "median_sep_km": statistics.median(sep), "max_sep_km": max(sep),
            "sd_diff_k": math.sqrt(var_diff), "repr_plus_instr_k": repr_plus_inst,
            "repr_k": repr_only, "declared_instr_k": DECLARED_SIGMA_K,
            "total_scatter_k": total, "model_residual_k": model_only,
        }, indent=1, ensure_ascii=False))
        print(f"\n  已写 {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
