"""Draw the error budget: what the comparison measured, and what its verdict is worth.

WHAT IS BEING TESTED
--------------------
Two sentences have been written in this repository about the same comparison
(GFS tmp2m against airport station temperature), and both are true and neither
is a fact about the model:

  1. The 2.14 K scatter is not the model's error.  It contains the instrument
     (declared 0.5 K), the representativeness of a 0.25 deg cell against a point
     station, and the model.  Measuring the middle term needs no model at all:
     two stations inside ONE cell see the SAME model value, so their difference
     is atmosphere-inside-the-cell plus two instrument errors, and nothing else.
  2. "Does the forecast agree with the observation" moves between 36.2% and
     94.5% on the same comparison, depending only on what is counted as error.
     Both columns come from the report's table; the wider one is the observed
     scatter used as its own yardstick, which is why it lands near 95%.

The figure's job is to keep those two apart and to say which numbers this
repository measured and which it read.

WHAT COULD NOT BE RECOMPUTED, AND WHY
-------------------------------------
The 36.2% / 94.5% row is at lead 7 on the model's 0.25 deg store.  All three
archived gfs runs' stores now return HTTP 404 upstream ("only the newest is
kept"), so that comparison cannot be repeated here; those two numbers are
RECORDED (report section 3242) and are drawn as recorded.  The observed total
scatter 2.14 K is RECORDED for the same reason (section 2971).

What IS recomputed here, over the archive as it now stands:
  * the within-cell pair statistics and the three-term decomposition, by running
    scripts/representativeness.py (its own code path, via --json and its table);
  * the elevation stratification, plus a count this repository needs and that
    script does not print -- how many DISTINCT station pairs the pair counts
    are made of.  A pair-observation is not an independent object; the same
    mistake (counting pixels as glaciers) is already on the record;
  * a local replication of the verdict swing against the archived tmp2m poster,
    at lead 0 and 0.5 deg.  It is a DIFFERENT comparison, labelled as such, and
    it exists so the reader can see the mechanism rather than take it on trust.

Usage:
  uv run --with numpy --with matplotlib python scripts/fig_error_budget.py
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt                                      # noqa: E402

import figstyle                                                      # noqa: E402
import poster_field as pf                                            # noqa: E402
import representativeness as R                                       # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
figstyle.use()

# ---- numbers carried from the report, marked as carried ---------------------
# Every one of these is RECORDED, not observed here, and each carries the line
# it came from so a reader can check it instead of trusting a figure.
REC = {
    "total_scatter_k": {"value": 2.14, "ref": "报告 §2943 节表（第 2971 行；7 时效 n=4770，block_pair 路径）"},
    "lead7_n": {"value": 4196, "ref": "报告 §3242 节表（第 3257 行）"},
    "lead7_median_k": {"value": -0.30, "ref": "报告 §3242 节表（第 3257 行）"},
    "lead7_sd_k": {"value": 2.13, "ref": "报告 §3242 节表（第 3257 行）"},
    "lead7_pct_2sigma_instr": {"value": 36.2, "ref": "报告 §3242 节表（第 3257 行）"},
    "lead7_pct_2sigma_wide": {"value": 94.5, "ref": "报告 §3242 节表（第 3257 行）"},
    "repr_k_old": {"value": 0.96, "ref": "报告 §3449 节（第 3471 行）"},
    "shares_old_pct": {"value": (20.0, 5.0, 75.0), "ref": "报告 §3449 节（第 3477–3481 行）"},
    "n_obs_old": {"value": 16_347, "ref": "报告 §3449 节（第 3466 行）"},
    "n_pairs_old": {"value": 478, "ref": "报告 §3449 节（第 3466 行）"},
    "bands_old": {"value": (242, 154, 44, 34, 2), "ref": "报告 §3507 节表（第 3513–3517 行）"},
    "high_band_pairs_old": {"value": 2, "ref": "报告 §3507 节（第 3517 / 3524 行）"},
}
DECLARED_INSTR_K = R.DECLARED_SIGMA_K        # WMO/CIMO synoptic temperature
CELLS = (0.25, 0.5)
HIGH_LO, HIGH_HI = 2000, 10000
# The report's structural point needs a place, not just an elevation: airports
# at 2000 m exist in Colorado.  So the count is also taken inside the one box
# this study cares about, with a control box where pairs DO exist -- a zero is
# only evidence if the same code finds a non-zero somewhere.
PLATEAU_BOX = (80.0, 92.0, 26.0, 32.0)       # west, east, south, north
CONTROL_BOX = (-109.0, -102.0, 35.0, 41.0)   # Colorado, USA

BAND_RE = re.compile(
    r"^\s*(\d+)-(\d+)\s+(\d+)\s+(?P<sd>—|[\d.]+)\s+(?P<repr>—|[\d.]+)\s+"
    r"(?P<sep>—|[\d.]+)(?P<short>\s*样本不足)?\s*$")


def run_representativeness(cell: float) -> tuple[dict, list[dict], str]:
    """Run scripts/representativeness.py and take its JSON and its own table.

    Importing the module would not do: the pair logic lives inside its `main()`,
    so the only way to use ITS code path rather than a second copy of it is to
    run it.  The band table is printed but not written to JSON, so it is parsed
    -- and the parse is asserted to have found every band, because a silent
    regex miss would draw a panel with bars that mean nothing.
    """
    cmd = [sys.executable, str(ROOT / "scripts" / "representativeness.py"),
           "--cell", str(cell), "--json", f"/tmp/fig_error_budget_repr_{cell}.json"]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if out.returncode != 0:
        raise SystemExit(f"representativeness.py --cell {cell} failed:\n{out.stderr}")
    raw = json.loads(Path(f"/tmp/fig_error_budget_repr_{cell}.json").read_text())
    bands = []
    for line in out.stdout.splitlines():
        m = BAND_RE.match(line)
        if not m:
            continue
        bands.append({
            "lo": int(m.group(1)), "hi": int(m.group(2)), "n": int(m.group(3)),
            "sd_diff_k": None if m.group("sd") == "—" else float(m.group("sd")),
            "repr_k": None if m.group("repr") == "—" else float(m.group("repr")),
            "median_sep_km": None if m.group("sep") == "—" else float(m.group("sep")),
            "insufficient": bool(m.group("short")),
        })
    assert len(bands) == 5, (
        f"parsed {len(bands)} elevation bands out of representativeness.py stdout, "
        "expected 5 -- its print format changed and this panel would be empty")
    n_sum = sum(b["n"] for b in bands)
    # Both directions, because both failures have happened in this repository: a
    # selection that takes nothing and a selection that takes everything.
    assert 0 < n_sum <= raw["n_pairs"], \
        f"band counts {n_sum} must be a subset of the {raw['n_pairs']} pairs"
    assert n_sum >= 0.9 * raw["n_pairs"], \
        f"bands cover only {n_sum}/{raw['n_pairs']} pairs: the parse is dropping rows"
    return raw, bands, out.stdout


def distinct_station_pairs(cell: float) -> dict:
    """How many DIFFERENT station pairs the pair counts are made of.

    This is not a second implementation of the within-cell statistic -- every
    sd and every representativeness value in this figure comes from
    representativeness.py's own output.  It answers a question that script does
    not ask: a pair observed at 15 successive hours counts as 15 pairs there,
    and as ONE object.  The same substitution (564 pixels -> 564 "glaciers") is
    already on this repository's record, one level down.

    `haversine_km` and the record indices come from that module, and the total
    is asserted to equal its own pair count, so the two groupings cannot drift
    apart without the assertion firing.
    """
    cells = defaultdict(lambda: defaultdict(dict))
    for f in sorted(glob.glob(str(ROOT / "archive" / "airport" / "*" / "index"))):
        for r in json.loads(Path(f).read_text()).get("stations", []):
            if len(r) <= 12 or r[R.F_T] is None or not r[R.F_TIME]:
                continue
            row = math.floor((90.0 - r[R.F_LAT]) / cell)
            col = math.floor((r[R.F_LON] + 180.0) / cell)
            cells[(row, col)][r[R.F_TIME][:13]][r[R.F_ICAO]] = (
                r[R.F_LAT], r[R.F_LON], float(r[R.F_T]), r[R.F_ELEV] or 0.0)

    bands = {b: {"obs": 0, "pairs": defaultdict(int), "sep": []}
             for b in [(0, 100), (100, 500), (500, 1000), (1000, 2000), (2000, 10000)]}
    total = 0
    high = {}
    for (row, col), hours in cells.items():
        for hour, st in hours.items():
            if len(st) < 2:
                continue
            v = list(st.items())
            for i in range(len(v)):
                for j in range(i + 1, len(v)):
                    total += 1
                    e = 0.5 * (v[i][1][3] + v[j][1][3])
                    for lo, hi in bands:
                        if lo <= e < hi:
                            key = tuple(sorted((v[i][0], v[j][0])))
                            b = bands[(lo, hi)]
                            b["obs"] += 1
                            b["pairs"][key] += 1
                            b["sep"].append(R.haversine_km(v[i][1][0], v[i][1][1],
                                                           v[j][1][0], v[j][1][1]))
                            if lo == HIGH_LO:
                                mlat = 0.5 * (v[i][1][0] + v[j][1][0])
                                mlon = 0.5 * (v[i][1][1] + v[j][1][1])
                                high[key] = (mlat, mlon, e)
                            break
    return {"total": total, "bands": bands, "high": high}


def in_box(lat: float, lon: float, box) -> bool:
    west, east, south, north = box
    return south <= lat <= north and west <= lon <= east


def normal_share(median: float, sd: float, threshold: float) -> float:
    """P(|d| < threshold) for a normal with this median and sd, in percent.

    Used to ask whether the recorded verdicts carry information about the model
    or are simply one distribution read at two thresholds.  It is a check
    because it can disagree: if the recorded 36.2% and 94.5% were not the two
    tails of one normal, this would not land on them and the panel's sentence
    would be wrong.
    """
    er = math.erf
    hi = 0.5 * (1.0 + er((threshold - median) / (sd * math.sqrt(2.0))))
    # Both tails take the SAME form.  The first version subtracted the erf here,
    # which silently turned the lower tail into the upper one and produced a
    # 10.0% where 36.1% was expected -- the assertion below caught it.
    lo = 0.5 * (1.0 + er((-threshold - median) / (sd * math.sqrt(2.0))))
    return 100.0 * (hi - lo)


def local_comparison(archive: Path) -> list[dict]:
    """Replicate the verdict swing on what IS archived: tmp2m posters, lead 0.

    A poster is the run's first frame decimated to 0.5 deg, so this is lead 0 at
    0.5 deg -- a different comparison from the recorded lead-7/0.25 deg table,
    and it is labelled as one.  Observations are deduplicated by station at the
    run's valid hour: a station reporting the same :00 minute appears in several
    consecutive batches, and counting it once per batch is the same
    non-independence this figure is about.
    """
    rows = []
    for item in pf.runs_with(archive, "gfs", "tmp2m"):
        meta = json.loads((archive / "gfs" / item / "item.json").read_text())
        run_hour = meta["properties"]["xue:runTime"][:13]
        obs = {}
        for f in sorted(glob.glob(str(archive / "airport" / "*" / "index"))):
            for r in json.loads(Path(f).read_text()).get("stations", []):
                if len(r) <= 12 or r[R.F_T] is None or not r[R.F_TIME]:
                    continue
                if r[R.F_TIME][:13] == run_hour:
                    obs[r[R.F_ICAO]] = r
        p = pf.load(archive, "gfs", item, "tmp2m")
        d = []
        for r in obs.values():
            ri = int(round((pf.ROW0_LAT - r[R.F_LAT]) / pf.STEP))
            ci = int(round((r[R.F_LON] - pf.COL0_LON) / pf.STEP))
            if not (0 <= ri < p.shape[0] and 0 <= ci < p.shape[1]) or not p.valid[ri, ci]:
                continue
            d.append(float(p.values[ri, ci]) - float(r[R.F_T]))
        if not d:
            continue
        d = np.array(d)
        rows.append({"item": item, "run_hour": run_hour, "n": int(d.size),
                     "median_k": float(np.median(d)), "sd_k": float(d.std(ddof=1)),
                     "values": d})
    return rows


def check_text_fits(fig, checks) -> None:
    """Refuse to ship a figure whose own labels run off their own axes.

    A wrong label position is invisible in the numbers: the first version of
    panel 2 printed its threshold annotations on top of its own tick labels and
    ran the gaussian note past the right frame, while every value was correct.
    So the drawn text is measured, not eyeballed -- this check fails loudly.
    """
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    # Text.get_window_extent, not t.get_window_extent: on an Annotation the
    # latter unions the text with its ARROW, so every arrow that crosses the
    # panel reported clashes that were not there.
    boxes_of = lambda ts: [(t, matplotlib.text.Text.get_window_extent(t, renderer))
                           for t in ts]
    over = []
    for ax, texts in checks:
        box = ax.get_window_extent(renderer)
        for t, tb in boxes_of(texts):
            l, r, b, u = box.x0 - tb.x0, tb.x1 - box.x1, box.y0 - tb.y0, tb.y1 - box.y1
            if max(l, r, b, u) > 1.0:             # 1 px tolerance for hinting
                over.append((t.get_text().splitlines()[0][:28], l, r, b, u))
    if over:
        for txt, l, r, b, u in over:
            print(f"  ✗ 标注越出坐标框 {txt!r}: 左{l:+.0f} 右{r:+.0f} 下{b:+.0f} 上{u:+.0f} px")
        raise SystemExit("有图内标注越出坐标框 —— 拒绝出图（一张被裁掉半个标签的图比没有图更糟）")
    # Annotations must also not sit on each other.  This is the failure that is
    # easiest to miss by eye and impossible to see in the numbers: two labels on
    # one line read as one label with a wrong value.
    clashes = []
    for ax, texts in checks:
        boxes = boxes_of(texts)
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i][1], boxes[j][1]
                if a.x0 < b.x1 - 1 and b.x0 < a.x1 - 1 and a.y0 < b.y1 - 1 and b.y0 < a.y1 - 1:
                    clashes.append((boxes[i][0].get_text().splitlines()[0][:22],
                                    boxes[j][0].get_text().splitlines()[0][:22]))
    if clashes:
        for a, b in clashes:
            print(f"  ✗ 两条标注互相压住: {a!r} × {b!r}")
        raise SystemExit("有图内标注重叠 —— 拒绝出图")
    print(f"  自检：{sum(len(t) for _a, t in checks)} 条图内标注都在坐标框内、且两两不重叠")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", default=str(ROOT / "archive"))
    ap.add_argument("--out", default=str(ROOT / "figures" / "error-budget.png"))
    ap.add_argument("--json", default=str(ROOT / "figures" / "error-budget.json"))
    args = ap.parse_args()
    archive = Path(args.archive)

    total_k = REC["total_scatter_k"]["value"]
    r25, bands25, _ = run_representativeness(0.25)
    r50, bands50, _ = run_representativeness(0.5)
    d25 = distinct_station_pairs(0.25)
    d50 = distinct_station_pairs(0.5)

    # The two groupings must agree on how many pairs there are, or the distinct
    # count below is describing a different set of pairs than the sd above.
    for cell, raw, dd in ((0.25, r25, d25), (0.5, r50, d50)):
        assert dd["total"] == raw["n_pairs"], (
            f"cell {cell}: independent pairing found {dd['total']} pairs, "
            f"representativeness.py reports {raw['n_pairs']}")

    repr_k = r25["repr_k"]
    model_k = math.sqrt(max(total_k ** 2 - repr_k ** 2 - DECLARED_INSTR_K ** 2, 0.0))
    shares = [100 * repr_k ** 2 / total_k ** 2, 100 * DECLARED_INSTR_K ** 2 / total_k ** 2,
              100 * model_k ** 2 / total_k ** 2]
    # A decomposition with no residual means one term ate the total: the
    # "mode dominates" reading would then be an artefact of the arithmetic.
    assert total_k ** 2 - repr_k ** 2 - DECLARED_INSTR_K ** 2 > 0, \
        "no residual variance left for the model: the decomposition is ill-posed"
    assert shares[2] > 50.0 and shares[0] > 10.0, \
        f"shares {shares} no longer support 'the model dominates, repr is a lower bound'"

    print("=" * 78)
    print("一、同一格点内测站对：代表性误差的下限（scripts/representativeness.py 现场重跑）")
    print("=" * 78)
    print(f"  观测 {r25['n_obs']:,} 条（报告 §3466 记 {REC['n_obs_old']['value']:,} 条）")
    print(f"  同格点同时刻测站对 n = {r25['n_pairs']:,}"
          f"（报告 §3466 记 {REC['n_pairs_old']['value']:,} 对）")
    print(f"  间距中位 {r25['median_sep_km']:.2f} km  最大 {r25['max_sep_km']:.2f} km"
          f"（格点 0.25° ≈ 28 km）")
    print(f"  温差 sd {r25['sd_diff_k']:.2f} K → 单站偏差 {r25['repr_plus_instr_k']:.2f} K"
          f" → 扣掉仪器 {DECLARED_INSTR_K:.2f} K 后 代表性 = {repr_k:.2f} K")
    print(f"\n  ⚠ 与报告不一致（不是错误，是归档长大了）：报告 §3449 那次只覆盖约 3 批 airport，"
          f"本仓库现有 {len(glob.glob(str(archive / 'airport' / '*' / 'index')))} 批；")
    print(f"     同一段代码、同一份判据，n 从 {REC['n_pairs_old']['value']:,} 涨到 "
          f"{r25['n_pairs']:,}，代表性从 {REC['repr_k_old']['value']:.2f} K 变为 {repr_k:.2f} K。")
    print(f"     报告的数字按 RECORDED 引用（§3466/§3471），本图的分解用现场重算值。")

    print(f"\n  三项分解（总量仍取 RECORDED 的 {total_k:.2f} K，因为 0.25° store 上游已 404）")
    print(f"    总散布            {total_k:.2f} K   {REC['total_scatter_k']['ref']}")
    print(f"    代表性（实测下限）  {repr_k:.2f} K    {shares[0]:.0f}% 的方差"
          f"   （报告 §3478 记 {REC['repr_k_old']['value']:.2f} K / "
          f"{REC['shares_old_pct']['value'][0]:.0f}%）")
    print(f"    仪器（declared）    {DECLARED_INSTR_K:.2f} K    {shares[1]:.0f}%"
          f"   （WMO/CIMO 规格值，不是本仓库的测量）")
    print(f"    模式（余项）        {model_k:.2f} K    {shares[2]:.0f}%"
          f"   （报告 §3480 记 1.85 K / {REC['shares_old_pct']['value'][2]:.0f}%）")
    lin = repr_k + DECLARED_INSTR_K + model_k
    print(f"\n  注意：√({repr_k:.2f}² + {DECLARED_INSTR_K:.2f}² + {model_k:.2f}²) = "
          f"{math.sqrt(repr_k**2 + DECLARED_INSTR_K**2 + model_k**2):.2f} K ＝ 总散布，"
          f"而分段之和是 {lin:.2f} K。")
    print("  这就是「sigma 按平方和相加、份额是方差」的全部内容。"
          "但**这个等式不是检验** —— 模式项本来就是余项，等式必然成立；")
    print("  它只能说明分解自洽，不能说明分解正确。能失败的检验在下面。")

    print("\n" + "=" * 78)
    print("二、判决取决于误差标准（36.2% / 94.5% 的复核）")
    print("=" * 78)
    n7, med7, sd7 = (REC["lead7_n"]["value"], REC["lead7_median_k"]["value"],
                     REC["lead7_sd_k"]["value"])
    comb_instr_repr = math.hypot(DECLARED_INSTR_K, repr_k)
    th_a, th_b, th_c = 2 * DECLARED_INSTR_K, 2 * comb_instr_repr, 2 * sd7
    share_b = normal_share(med7, sd7, th_b)
    pred_a = normal_share(med7, sd7, th_a)
    pred_c = normal_share(med7, sd7, th_c)
    print(f"  记录的那一行：时效 7 h，n = {n7:,}，中位 {med7:+.2f} K，散布 sd {sd7:.2f} K"
          f"   {REC['lead7_n']['ref']}")
    print(f"  {'误差标准':<34}{'阈值 2σ':>10}{'占记录的判决':>14}{'同一分布的正态预测':>20}")
    rows_verdict = [
        ("① 只用仪器 0.5 K（declared）", th_a, REC["lead7_pct_2sigma_instr"]["value"], pred_a),
        ("② 仪器 + 实测代表性 %.2f K" % repr_k, th_b, None, share_b),
        ("③ 用数据自身散布 %.2f K 当尺子" % sd7, th_c, REC["lead7_pct_2sigma_wide"]["value"], pred_c),
    ]
    for name, th, recorded, pred in rows_verdict:
        rec_s = f"{recorded:.1f}%（§3242 表）" if recorded is not None else "无记录（本仓库推算）"
        print(f"  {name:<34}{th:>9.2f} K{rec_s:>22}{pred:>19.1f}%")
    print(f"\n  三个阈值相对记录自身散布 {sd7:.2f} K 是 "
          f"{th_a/sd7:.2f}σ / {th_b/sd7:.2f}σ / {th_c/sd7:.2f}σ —— "
          f"③ 恒等于「±2 个标准差」，所以它必然接近 95%，")
    print("     与模式准不准无关。**这就是「判决是关于选择、不是关于模式」的算术内容。**")
    ok_a = abs(pred_a - REC["lead7_pct_2sigma_instr"]["value"]) < 3.0
    ok_c = abs(pred_c - REC["lead7_pct_2sigma_wide"]["value"]) < 3.0
    print(f"\n  可失败的检验：把记录的 n/中位/sd 当作一个正态分布，")
    print(f"    ① 预测 {pred_a:.1f}% 对记录 {REC['lead7_pct_2sigma_instr']['value']:.1f}%  → "
          + ("通过（差 %.1f 点）" % abs(pred_a - REC["lead7_pct_2sigma_instr"]["value"])
             if ok_a else "**不通过**：判决不能只用分布形状解释"))
    print(f"    ③ 预测 {pred_c:.1f}% 对记录 {REC['lead7_pct_2sigma_wide']['value']:.1f}%  → "
          + ("通过（差 %.1f 点，即 ③ 只是「±2σ」的定义）"
             % abs(pred_c - REC["lead7_pct_2sigma_wide"]["value"])
             if ok_c else "**不通过**：③ 不是自指的阈值"))
    assert ok_a and ok_c, (
        "the two recorded verdicts are NOT the two tails of one distribution: the "
        "figure's explanation of the swing would be wrong and must be rewritten")

    print("\n  ⚠ 报告 §3242 的 36.2% / 94.5% **本仓库无法重算**：")
    print("     该比对在 7 时效、0.25° store 上做，而归档的三次 gfs 运行"
          "（2026091718/1800/1806）的 store 上游现均返回 HTTP 404")
    print("     （上游只保留最新一次运行）。故 36.2% / 94.5% / n=4196 / sd 2.13 "
          "按 RECORDED 引用（§3242 节表第 3257 行），本图不把它们画成现场结果。")

    # ---- the local replication, which IS observed here ----------------------
    local = local_comparison(archive)
    usable = [x for x in local if x["n"] >= 100]
    print("\n  本仓库现场可重算的**邻近版本**（0 时效 · tmp2m poster 0.5°）—— "
          "**不是同一个比对**：")
    print(f"  {'运行':<16}{'n':>7}{'中位':>8}{'sd':>7}"
          f"{'① 2σ仪器':>10}{'② 2σ仪器+代表':>15}{'③ 2σ自身散布':>14}")
    local_rows = []
    for x in local:
        a = 100.0 * float(np.mean(np.abs(x["values"]) < th_a))
        th_b_local = 2 * math.hypot(DECLARED_INSTR_K, r50["repr_k"])
        b = 100.0 * float(np.mean(np.abs(x["values"]) < th_b_local))
        c = 100.0 * float(np.mean(np.abs(x["values"]) < 2 * x["sd_k"]))
        flag = "" if x["n"] >= 100 else "   ← 样本不足，不计入比较"
        print(f"  {x['item']:<16}{x['n']:>7}{x['median_k']:>8.2f}{x['sd_k']:>7.2f}"
              f"{a:>9.1f}%{b:>14.1f}%{c:>13.1f}%{flag}")
        local_rows.append({"item": x["item"], "run_hour": x["run_hour"], "n": x["n"],
                           "median_k": x["median_k"], "sd_k": x["sd_k"],
                           "pct_2sigma_instr": a, "pct_2sigma_instr_repr": b,
                           "pct_2sigma_own_scatter": c})
    assert usable, "no archived run has a large enough lead-0 sample to replicate the swing"
    ref = max(usable, key=lambda x: x["n"])
    ref_local = [r for r in local_rows if r["item"] == ref["item"]][0]

    print("\n" + "=" * 78)
    print("三、按海拔分层：能不能回答「高海拔的代表性误差有多大」")
    print("=" * 78)
    print(f"  {'海拔带 m':<16}{'0.25° 对观测':>13}{'不同测站对':>11}{'代表性sd':>10}"
          f"{'间距中位':>10}   |  {'0.5° 对观测':>12}{'不同对':>8}{'代表性sd':>10}")
    band_rows = []
    for b25, b50 in zip(bands25, bands50):
        key = (b25["lo"], b25["hi"])
        nb25 = d25["bands"][key]
        nb50 = d50["bands"][key]
        sep25 = (float(np.median(nb25["sep"])) if nb25["sep"] else float("nan"))
        print(f"  {b25['lo']:>5}-{b25['hi']:<10}{b25['n']:>13}{len(nb25['pairs']):>11}"
              f"{(b25['repr_k'] if b25['repr_k'] is not None else float('nan')):>10.2f}"
              f"{sep25:>10.1f}   |  {b50['n']:>12}{len(nb50['pairs']):>8}"
              f"{(b50['repr_k'] if b50['repr_k'] is not None else float('nan')):>10.2f}")
        band_rows.append({
            "lo": b25["lo"], "hi": b25["hi"],
            "n_pair_obs_025": b25["n"], "n_distinct_pairs_025": len(nb25["pairs"]),
            "repr_k_025": b25["repr_k"], "median_sep_km_025": sep25,
            "n_pair_obs_050": b50["n"], "n_distinct_pairs_050": len(nb50["pairs"]),
            "repr_k_050": b50["repr_k"], "median_sep_km_050": b50["median_sep_km"],
            "insufficient_here": b25["n"] < 15 or len(nb25["pairs"]) < 15,
        })
    top25 = band_rows[-1]
    print(f"\n  ⚠ 高带（2000–10000 m）的 {top25['n_pair_obs_025']} 次配对观测 "
          f"＝ **{top25['n_distinct_pairs_025']} 对不同测站**"
          f"（{'、'.join('–'.join(k) for k in sorted(d25['high']))}）")
    print(f"     报告 §3517/3524 记的是「2 对」—— 与这里的不同测站对数**一致**。")
    print(f"     所以 n 从 2 涨到 {top25['n_pair_obs_025']} 不是观测变多，"
          f"是同一对测站被拍了 {max(d25['bands'][(HIGH_LO, HIGH_HI)]['pairs'].values())} 次：")
    print("     **配对观测不是独立对象** —— 与 564 像元不是 564 条冰川是同一个错。")
    print(f"     故本图对该带只画空槽「样本不足」，不引用它印出的 "
          f"{top25['repr_k_025']:.2f} K。")

    plateau = [k for k, (la, lo, _e) in d25["high"].items() if in_box(la, lo, PLATEAU_BOX)]
    control = [k for k, (la, lo, _e) in d25["high"].items() if in_box(la, lo, CONTROL_BOX)]
    assert len(plateau) == 0 and len(control) > 0, (
        f"box logic is not discriminating: plateau {len(plateau)}, control {len(control)} "
        "-- a zero only means something if the same test finds a non-zero elsewhere")
    print(f"\n  2000 m 以上 {len(d25['high'])} 对不同测站的位置："
          f"高原框 {PLATEAU_BOX[0]:.0f}-{PLATEAU_BOX[1]:.0f}E/"
          f"{PLATEAU_BOX[2]:.0f}-{PLATEAU_BOX[3]:.0f}N 内 **{len(plateau)} 对**；"
          f"对照框（科罗拉多）内 {len(control)} 对")
    print("     → 0 不是「没测到」，是「那里没有测站」：机场在山谷和城市里。")
    print(f"  间距混杂：0.25° 高带间距中位 {top25['median_sep_km_025']:.1f} km 给 "
          f"{top25['repr_k_025']:.2f} K，0.5° 高带间距中位 "
          f"{d50['bands'][(HIGH_LO, HIGH_HI)]['sep'] and float(np.median(d50['bands'][(HIGH_LO, HIGH_HI)]['sep'])):.1f} km "
          f"给 {bands50[-1]['repr_k']:.2f} K。")
    print("     同一批测站，改格点尺寸就改结论 —— 量到的是【间距】，不是【海拔】。")

    # ---- figure -------------------------------------------------------------
    # Layout note: panel 1 needs TWO vertical scales.  The first version drew the
    # sigma segments on the 0-100 percent axis, which rendered them as a sliver
    # three percent tall -- exactly the opposite of what that bar is for.
    fig = plt.figure(figsize=(14.8, 10.2), dpi=140)
    gs = fig.add_gridspec(2, 2, height_ratios=[1.0, 0.88], hspace=0.30, wspace=0.19,
                          left=0.060, right=0.985, top=0.850, bottom=0.145)
    C_REPR, C_INSTR, C_MODEL = figstyle.NEUTRAL, figstyle.WARN, figstyle.BAD
    parts_k = [repr_k, DECLARED_INSTR_K, model_k]
    cols = [C_REPR, C_INSTR, C_MODEL]

    # LEFT: the same three terms as a share of variance and as a sigma.  The two
    # bars are deliberately NOT the same picture: the sigma segments are drawn to
    # sigma scale, so they overrun the total, and the dashed line shows by how
    # much.  Shares are of variance, sigmas add in quadrature -- one sentence,
    # two bars.
    ax1 = fig.add_subplot(gs[0, 0])
    ax1b = ax1.twinx()
    bottom_pct = bottom_k = 0.0
    for s, v, c in zip(shares, parts_k, cols):
        ax1.bar(0, s, 0.46, bottom=bottom_pct, color=c, zorder=3, edgecolor="white",
                linewidth=1.2)
        ax1.text(0, bottom_pct + s / 2, f"{s:.0f}%", fontsize=9.2, va="center", ha="center",
                 color="white", fontweight="bold", zorder=5)
        ax1b.bar(1.0, v, 0.46, bottom=bottom_k, color=c, zorder=3, edgecolor="white",
                 linewidth=1.2)
        if v / 3.5 > 0.09:                 # only label a segment tall enough to hold text
            ax1b.text(1.0, bottom_k + v / 2, f"{v:.2f}", fontsize=9.2, va="center",
                      ha="center", color="white", fontweight="bold", zorder=5)
        bottom_pct += s
        bottom_k += v
    ax1b.axhline(total_k, color=figstyle.INK, lw=1.5, ls=(0, (4, 2)), zorder=6)
    # 3% above the line: sitting exactly on it, the dashes ran through the glyphs
    ax1b.text(1.28, total_k * 1.03, f"总散布 {total_k:.2f} K（RECORDED §2971 行）",
              fontsize=8.2, va="bottom", ha="left", color=figstyle.INK,
              fontweight="bold", zorder=7)
    key = [
        (f"■ 代表性 {repr_k:.2f} K（实测下限）{shares[0]:.0f}% 方差", C_REPR),
        (f"■ 仪器 {DECLARED_INSTR_K:.2f} K（declared）{shares[1]:.0f}%", C_INSTR),
        (f"■ 模式 {model_k:.2f} K（余项）{shares[2]:.0f}%", C_MODEL),
    ]
    for j, (txt, c) in enumerate(key):
        ax1.text(1.34, 96 - 9 * j, txt, fontsize=8.4, color=c, va="top", ha="left")
    ax1.text(1.34, 50,
             "σ 按平方和相加：\n"
             f"√({repr_k:.2f}²+{DECLARED_INSTR_K:.2f}²+{model_k:.2f}²)\n"
             f"  ＝ {math.sqrt(sum(v ** 2 for v in parts_k)):.2f} K ＝ 总散布\n"
             f"分段之和 {sum(parts_k):.2f} K 不是总散布\n"
             f"（报告 §3478 记 {REC['repr_k_old']['value']:.2f} K / "
             f"{REC['shares_old_pct']['value'][0]:.0f}%）",
             fontsize=8.0, color=figstyle.DIM, va="top", ha="left")
    ax1.set_xlim(-0.5, 2.55)
    ax1.set_ylim(0, 100)
    ax1b.set_ylim(0, 3.5)
    ax1b.set_yticks([0, 1, 2, 3])
    ax1b.set_ylabel("σ  K", fontsize=9.5)
    # tidy() would hide the right spine, and on a twin axis that spine is the
    # only scale the sigma bar has.  So the top one is hidden by hand instead.
    ax1b.spines["top"].set_visible(False)
    ax1.set_xticks([0, 1.0])
    ax1.set_xticklabels(["① 方差占比 %\n（三段之和 = 100%）",
                         "② σ  K\n（三段按平方和相加）"], fontsize=8.8)
    ax1.set_ylabel("方差占比 %", fontsize=9.5)
    ax1.set_title("三项分解：同一次比对，两种读法", fontsize=11)
    figstyle.tidy(ax1)

    # RIGHT: the verdict against the standard it is scored by.  Filled bars are
    # what the report recorded; the open circle on each is this repository's own
    # replication on a DIFFERENT comparison; the dotted lines are what one normal
    # with the recorded median and sd predicts -- the reason the swing is
    # arithmetic rather than news about the model.
    ax2 = fig.add_subplot(gs[0, 1])
    xs = np.arange(3)
    rec_vals = [REC["lead7_pct_2sigma_instr"]["value"], share_b,
                REC["lead7_pct_2sigma_wide"]["value"]]
    t_pct, t_th = [], []
    for i, (v, th) in enumerate(zip(rec_vals, (th_a, th_b, th_c))):
        filled = i != 1
        ax2.bar(i, v, 0.58, color=figstyle.INK if filled else "none", zorder=3,
                edgecolor=figstyle.INK, linewidth=1.5,
                hatch=None if filled else "///", alpha=0.9 if filled else 1.0)
        t_pct.append(ax2.text(i, v + 2.6, f"{v:.1f}%", ha="center", va="bottom",
                              fontsize=11, fontweight="bold", color=figstyle.INK, zorder=6))
        t_th.append(ax2.text(i, v * 0.5, f"阈值 2σ\n= {th:.2f} K\n= {th / sd7:.2f}σ",
                             ha="center", va="center", fontsize=8.4, zorder=6,
                             color="white" if filled else figstyle.INK,
                             bbox=None if filled else dict(facecolor="white",
                                                           edgecolor="none", alpha=0.9,
                                                           pad=1.4)))
    ax2.plot(xs, [ref_local["pct_2sigma_instr"], ref_local["pct_2sigma_instr_repr"],
                  ref_local["pct_2sigma_own_scatter"]], "o", ms=9.5, mfc="white",
             mec=figstyle.OK, mew=2.2, zorder=7)
    ax2.axhline(pred_c, color=figstyle.WARN, lw=1.2, ls=(0, (5, 3)), zorder=2)
    ax2.axhline(pred_a, color=figstyle.WARN, lw=1.2, ls=(0, (5, 3)), zorder=2)
    t_gauss = ax2.text(2.88, 40,
             "细虚线：把记录的中位/sd 当正态分布\n"
             "后得到的预测\n"
             f"① 预测 {pred_a:.1f}%，记录 {rec_vals[0]:.1f}%（差 "
             f"{abs(pred_a - rec_vals[0]):.1f} 点）\n"
             f"③ 预测 {pred_c:.1f}%，记录 {rec_vals[2]:.1f}%（差 "
             f"{abs(pred_c - rec_vals[2]):.1f} 点）\n"
             "→ 两个判决是同一个分布的两个尾巴",
             fontsize=8.0, color=figstyle.WARN, va="top", ha="left", zorder=6,
             # the 35.8% dotted line runs through this block otherwise
             bbox=dict(facecolor="white", edgecolor="none", alpha=0.85, pad=1.6))
    handles = [plt.Rectangle((0, 0), 1, 1, facecolor=figstyle.INK, alpha=0.9),
               plt.Rectangle((0, 0), 1, 1, facecolor="white", edgecolor=figstyle.INK,
                             hatch="///", linewidth=1.2),
               plt.Line2D([], [], marker="o", ls="none", ms=8, mfc="white",
                          mec=figstyle.OK, mew=2.0)]
    ax2.legend(handles, ["报告 §3242 表记录（7 时效）", "本仓库解析推算（无记录）",
                         f"现场重算（0 时效，n={ref_local['n']:,}）"],
               fontsize=7.6, frameon=False, loc="upper left", bbox_to_anchor=(0.0, 1.0))
    ax2.set_xlim(-0.62, 4.85)
    ax2.set_ylim(0, 112)
    ax2.set_xticks(xs)
    ax2.set_xticklabels(["① 只用仪器\n（观测自身误差）",
                         "② 仪器 + 实测代表性\n（本仓库量到的）",
                         "③ 用数据自身散布\n当尺子（自指）"], fontsize=8.6)
    ax2.set_xlabel("实心＝报告 §3242 表记录（7 时效·0.25°）｜"
                   "空圈＝本仓库现场重算（0 时效·0.5°，非同一比对）", fontsize=8.0)
    ax2.set_ylabel("与观测一致的配对占比 %", fontsize=9.5)
    ax2.set_title("判决是关于误差标准的选择，不是关于模式", fontsize=11)
    figstyle.tidy(ax2)

    # BOTTOM: the stratification, and the slot that has to stay empty.  The
    # counts sit INSIDE the bars: printed under the axis they collided with the
    # band labels, which is how a figure starts misreading itself.
    ax3 = fig.add_subplot(gs[1, :])
    xb = np.arange(len(band_rows))
    slot_i = [i for i, b in enumerate(band_rows) if b["insufficient_here"]]
    assert len(slot_i) == 1, (
        f"{len(slot_i)} bands are flagged insufficient; this panel's message is that "
        "exactly the high band is, and if that changed the figure has to change")
    slot = band_rows[slot_i[0]]
    ax3.bar([i for i in xb if i not in slot_i],
            [b["repr_k_025"] for i, b in enumerate(band_rows) if i not in slot_i],
            0.46, color=C_REPR, zorder=3, label="0.25° 格点：代表性 sd（下限）")
    ax3.bar(slot_i[0], 0.55, 0.46, color="none", edgecolor=figstyle.WARN, linewidth=1.6,
            hatch="///", zorder=4)
    ax3.text(slot_i[0], 0.27, "样本不足", ha="center", va="center", fontsize=9.6,
             color=figstyle.WARN, fontweight="bold", zorder=5,
             bbox=dict(facecolor="white", edgecolor="none", alpha=0.9, pad=1.4))
    t_slot = ax3.text(slot_i[0], 0.66, f"{slot['n_pair_obs_025']} 次配对观测\n＝仅 "
                              f"{slot['n_distinct_pairs_025']} 对不同测站",
             ha="center", va="bottom", fontsize=8.0, color=figstyle.WARN, zorder=5)
    t_counts = []
    for i, b in enumerate(band_rows):
        if i in slot_i:
            continue
        # Written INSIDE the bar top: above it, these values collided with the
        # 0.5-degree markers, which is the one thing on this panel that must stay
        # legible, since it is what makes the elevation reading doubtful.
        t_counts.append(ax3.text(i, b["repr_k_025"] - 0.03, f"{b['repr_k_025']:.2f} K",
                                 ha="center", va="top", fontsize=9.0, color="white",
                                 fontweight="bold", zorder=6))
        # 0.42 rather than half the bar: the block is taller than it looks, and
        # at half height it grazed the value label above it -- which the pairwise
        # overlap check reported as two labels printed on one line.
        # Short lines on purpose: this text is white, so anything that spills
        # past the blue bar becomes white on white and silently disappears.  The
        # separations therefore live in the provenance line above instead.
        t_counts.append(ax3.text(i, b["repr_k_025"] * 0.42,
                                 f"{b['n_pair_obs_025']:,} 次配对\n"
                                 f"{b['n_distinct_pairs_025']} 对不同测站",
                                 ha="center", va="center", fontsize=8.0, color="white",
                                 zorder=5))
    ax3.plot(xb, [b["repr_k_050"] for b in band_rows], "o--", color=figstyle.WARN, ms=7,
             mfc="white", mew=1.8, lw=1.3, zorder=6,
             label="0.5° 格点（对照）："
                   + "/".join(f"{b['repr_k_050']:.2f}" for b in band_rows)
                   + " K —— 间距翻倍，量到的就更大")
    t_repeat = ax3.annotate(f"这 {slot['n_distinct_pairs_025']} 对被拍了 "
                 f"{max(d25['bands'][(HIGH_LO, HIGH_HI)]['pairs'].values())} 次，"
                 f"共 {slot['n_pair_obs_025']} 次配对观测：\n"
                 "配对观测不是独立对象",
                 xy=(slot_i[0] - 0.24, 0.50), xytext=(1.85, 2.34),
                 fontsize=8.6, color=figstyle.WARN, va="center", ha="left",
                 arrowprops=dict(arrowstyle="->", color=figstyle.WARN, lw=1.3,
                                 connectionstyle="arc3,rad=0.2"))
    t_where = ax3.text(-0.55, 3.66,
             f"2000 m 以上共 {len(d25['high'])} 对不同测站：38.8N/106.2W（科罗拉多 K7BM–KAEJ）、"
             "0.83N/77.7W（厄瓜多尔 SETU–SKIP）\n"
             f"高原框 {PLATEAU_BOX[0]:.0f}-{PLATEAU_BOX[1]:.0f}E/"
             f"{PLATEAU_BOX[2]:.0f}-{PLATEAU_BOX[3]:.0f}N 内 0 对 —— 对照框（科罗拉多）内有 1 对，"
             "说明框判据本身没坏；各带间距中位（0.25°）"
             + "/".join(f"{b['median_sep_km_025']:.1f}" for b in band_rows) + " km",
             fontsize=8.2, color=figstyle.FAINT, va="top", ha="left")
    ax3.set_xticks(xb)
    ax3.set_xticklabels([f"{b['lo']}–{b['hi']} m" for b in band_rows], fontsize=9.4)
    ax3.set_xlim(-0.62, len(band_rows) - 0.30)
    ax3.set_ylim(-0.30, 4.05)
    ax3.set_ylabel("代表性 sd（下限）K", fontsize=9.5)
    ax3.set_title("按海拔分层：机场在山谷和城市里，方法对高原在结构上无法作答", fontsize=11)
    figstyle.tidy(ax3)
    ax3.legend(fontsize=8.4, frameon=False, loc="upper left", bbox_to_anchor=(0.0, 0.80))

    figstyle.title(
        fig, "误差预算：量到了什么，以及判决值多少",
        "左：2.14 K 的散布分解为代表性 0.94 K、仪器 0.50 K、模式 1.86 K；份额是方差，σ 按平方和相加，"
        "故三段线性之和 3.30 K 大于总散布 —— 那不是错误，是「别把 σ 直接相加」。\n"
        "右：同一次比对「是否一致」可以是 36.2% 或 94.5%，差别只在把什么算作误差。"
        "下：机场在山谷和城市里，高海拔那一格因此量不出来。")
    figstyle.footer(
        fig, f"现场重算（scripts/fig_error_budget.py）：跑 scripts/representativeness.py 得 "
             f"n={r25['n_pairs']:,} 对、代表性 {repr_k:.2f} K（0.25°），"
             f"n={r50['n_pairs']:,} 对、{r50['repr_k']:.2f} K（0.5°）；"
             f"海拔分层、「不同测站对」去重、分辨高海拔测站位置均为本仓库计算；"
             f"右图空圈为本仓库对归档 poster 的重算（0 时效 · 0.5° · n={ref_local['n']:,}，"
             f"**与记录的 7 时效 · 0.25° 比对不是同一个比对**）。"
             f"RECORDED（本仓库无法重算：归档三次 gfs 运行的 0.25° store 上游现均 HTTP 404）："
             f"总散布 2.14 K（§2943 节表第 2971 行）；7 时效 n=4,196 / 中位 −0.30 / sd 2.13 / "
             f"36.2% / 94.5%（§3242 节表第 3257 行）；旧代表性 0.96 K（§3449 节第 3471 行）、"
             f"旧对数 478（第 3466 行）、旧海拔分层 242/154/44/34/2（§3507 节第 3513–3517 行）。"
             f"边界：代表性误差是**下限**（机场两站通常不横跨整个格点，真值只会更大），"
             f"故「模式占比多数」在有测站的地方成立，且**未被外推到高山**；"
             f"仪器 0.50 K 是 WMO/CIMO 规格值，不是本仓库的测量；"
             f"2000 m 以上不给数值（17 次配对观测仅 2 对不同测站，低于脚本自己的 15 对门槛），"
             f"且各带的间距中位随格点尺寸变化 —— 量到的是间距，不是海拔。")
    check_text_fits(fig, [(ax1, list(ax1.texts)), (ax2, [t_gauss, *t_pct, *t_th]),
                          (ax3, [t_where, t_repeat, t_slot, *t_counts])])
    for ftext in fig.texts:                      # title block and footer, on the figure
        tb = ftext.get_window_extent(fig.canvas.get_renderer())
        fb = fig.bbox
        assert (tb.x0 >= fb.x0 - 1 and tb.x1 <= fb.x1 + 1 and tb.y0 >= fb.y0 - 1), \
            f"figure-level text runs out of the canvas: {ftext.get_text()[:30]!r}"
    print(f"  自检：图级文字（标题/脚注）{len(fig.texts)} 条均在画布内")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    payload = {
        "recomputed_here": {
            "representativeness_0p25": r25, "representativeness_0p5": r50,
            "elevation_bands": band_rows,
            "decomposition": {"total_k": total_k, "repr_k": repr_k,
                              "instrument_k": DECLARED_INSTR_K, "model_k": model_k,
                              "shares_pct": shares, "sigma_sum_linear_k": sum(parts_k)},
            "high_band_distinct_pairs": {f"{a}–{b}": v for (a, b), v in d25["high"].items()},
            "high_band_pairs_in_plateau_box": len(plateau),
            "high_band_pairs_in_control_box": len(control),
            "local_replication": local_rows,
            "local_replication_used": ref_local,
        },
        "recorded": {k: {"value": v["value"], "ref": v["ref"]} for k, v in REC.items()},
        "verdict_standards": {
            "threshold_2sigma_instr_k": th_a, "threshold_2sigma_instr_repr_k": th_b,
            "threshold_2sigma_own_scatter_k": th_c,
            "recorded_pct": [REC["lead7_pct_2sigma_instr"]["value"], None,
                             REC["lead7_pct_2sigma_wide"]["value"]],
            "normal_prediction_pct": [pred_a, share_b, pred_c],
            "explanation": "三个阈值相对记录自身散布是 0.47σ / 1.00σ / 2.00σ，"
                           "第三个恒等于「±2 个标准差」，故必然接近 95%，与模式无关。",
        },
        "boundary": "代表性与仪器项均为下限/规格值；2000 m 以上无足够独立测站对；"
                    "36.2%/94.5% 为 RECORDED，存档的 tmp2m store 上游已 404，本仓库无法重算。",
    }
    Path(args.json).write_text(json.dumps(payload, indent=1, ensure_ascii=False,
                                          default=float))
    print(f"\n  写入 {out} 和 {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
