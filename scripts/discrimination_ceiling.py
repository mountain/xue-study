"""What precision can ANY detector reach, given how rare the events are.

WHY THIS IS THE FIRST THING TO COMPUTE
--------------------------------------
This study has now measured three separate detectors for glacier collapse, and
all three came back with no usable skill:

  positive degree day      triggers 91 percent of the time -- saturated, no power
  rain-on-ice threshold    threshold 50 gives 100 percent hit and 95 percent
                           false alarm; 275 gives zero hits
  ITS_LIVE velocity        the verified site is SLOWER than its own baseline in
                           2021-2023, not faster

The reflex is to blame the features and go looking for better ones.  That reflex
is wrong, and this script shows why with arithmetic rather than opinion.

Precision has a ceiling set by the base rate alone, independent of the physics:

    with a PERFECT ranker that puts every real event at the top,
    flagging a fraction a of the population gives
        precision = p / a          where p is the base rate
        recall    = 1

So to have half your alarms be real, you may flag at most 2p of the population.
Nothing about the atmosphere enters that line.  It is a property of counting.

THE UNITS MATTER AND ARE STATED
-------------------------------
"Population" here means SITE-YEARS: one glacier in one year.  That is the unit a
seasonal warning would act on.  Saying "site-years" and not "glaciers" matters,
because a glacier watched for eleven years contributes eleven chances to raise a
false alarm, and a detector that fires once per glacier per decade is already
firing at the base rate.

WHAT THIS DOES NOT SAY
----------------------
It does not say that no warning is possible.  It says that any warning worth
acting on must be extremely selective, and it puts a number on "extremely".  A
detector that flags one percent of site-years cannot be right more than about
two percent of the time no matter how good its physics is -- so the design
question is not "which feature", it is "how do we get the alarm rate down to the
base rate", which means either far better precision at the very top of the
ranking, or a population restricted to sites already known to be unstable.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

# Site-year populations, so the ceiling can be read at three scales.  The local
# figure is measured (564 glacier pixels in the Langtang neighbourhood over the
# eleven years the fixed pixel set supports); the wider ones are stated as
# orders of magnitude and labelled as such, because they are not measured here.
POPULATIONS = {
    "langtang local (measured)": 564 * 11,
    "high mountain asia (~)": 100_000 * 11,
    "global glaciers (~)": 200_000 * 11,
}

# Detectors already measured in this study, for the comparison table.
MEASURED = [
    ("positive degree day", "triggers 91% of the time", 0.91),
    ("rain-on-ice, threshold 50", "100% hit / 95% false alarm", 0.95),
]


def ceiling(p: float, alarms: list[float]) -> list[dict]:
    out = []
    for a in alarms:
        # A perfect ranker: every event is inside the flagged set, so precision
        # is events over flagged, and flagged is a*N.
        prec = min(1.0, p / a) if a > 0 else 1.0
        out.append({"alarm_rate": a, "best_precision": prec,
                    "best_false_alarm": 1.0 - prec})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", type=int, default=1,
                    help="verified events in the population (default: the one "
                         "this study has coordinates, a date and a source for)")
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    alarms = [0.5, 0.1, 0.01, 0.001, 0.0001, 0.00001]
    report = {"events": args.events, "populations": {}, "measured": MEASURED}

    print(f"已核实事件数: {args.events}\n")
    for name, N in POPULATIONS.items():
        p = args.events / N
        rows = ceiling(p, alarms)
        report["populations"][name] = {"site_years": N, "base_rate": p,
                                       "ceiling": rows}
        print(f"=== {name}  N={N:,} 基率 p={p:.3e}（约 1/{1/p:,.0f}）===")
        print(f"  {'报警率':>12}{'完美排序下的最好精确率':>24}{'误报率下界':>14}")
        for r in rows:
            # Format small rates as ratios: "%.0f%%" renders every rate below
            # half a percent as "0%", which hides exactly the regime that matters.
            a = r["alarm_rate"]
            a_s = f"{a:.0%}" if a >= 0.01 else f"1/{1/a:,.0f}"
            print(f"  {a_s:>12}{r['best_precision']:>23.2%}"
                  f"{r['best_false_alarm']:>13.1%}")
        need = 2 * p
        # 2p*N is 2E regardless of N: with one event the count is always two.
        # The informative quantity is the RATE, which is what shrinks with N.
        print(f"  → 要让一半报警是真的，报警率必须 ≤ 2p = {need:.2e}"
              f"（即 1/{1/need:,.0f} 的站年）")
        print(f"     注意：换算成个数时不分尺度都是 2E = {2*args.events} 个，"
              f"因为 2p·N = 2E 与 N 无关；\n"
              f"     随总体扩大而收紧的是【率】，不是个数。\n")
        report["populations"][name]["alarm_rate_for_half_precision"] = need

    print("=== 本会话已实测的三个探测器，放在这个上限下看 ===")
    N = POPULATIONS["langtang local (measured)"]
    p = args.events / N
    for name, note, a in MEASURED:
        prec = min(1.0, p / a)
        print(f"  {name:<28} 报警率 {a:>5.0%}  上限精确率 {prec:.3%}   （{note}）")
    print(f"\n  它们的报警率比基率高出 {MEASURED[1][2]/p:,.0f} 倍。")
    print("  → 误报不是特征的毛病，是报警率与基率不匹配的算术后果。")
    print("  → 因此「换一个更好的特征」不会修好它；要修的是报警率，")
    print("     或者把总体限制到已知不稳定的那部分站点上。")

    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=1, ensure_ascii=False))
        print(f"\n  已写 {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
