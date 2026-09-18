"""An event is an observation with an uncertainty entering the system.

THE REFRAME
-----------
The learning phase stalled on one thing: a labelled event set.  Building a
historical catalogue of glacier collapses needs an external inventory, and the
inventories this session tried were unreachable (zenodo.org down, COSR/Durham
403, NASA COOLR host gone).

That was the wrong requirement.  **An event is not a row in a disaster
catalogue.  An event is an observation, carrying its uncertainty, entering the
system.**  The observation stream the block already ingests IS the event stream.
Nothing external is needed, and the reframe is not a workaround -- it is what
the block design always implied, since the block compares prediction against
observation at every point it covers.

WHAT THIS FORCES, AND WHY IT IS THE POINT
-----------------------------------------
Every record must carry an uncertainty AND the provenance of that uncertainty.
An observation without an error bar cannot enter, because a comparison against
it cannot be scored -- it can only be asserted.

This study has been sloppy here in a specific, repeated way: it reports
"GFS tmp2m against 5,354 stations: median -0.10 K, sd 2.17" and then treats that
as a fact about the model, when it is a fact about the model PLUS the
representativeness error PLUS the instrument.  Making the uncertainty a required
field with a named source forces that distinction to be written down instead of
left implicit.

THREE KINDS OF UNCERTAINTY, KEPT APART
--------------------------------------
  declared          from a specification (an instrument's rated accuracy)
  computed          derived from the record itself (a proportion's binomial error)
  observed-scatter  measured across comparisons, and therefore CONTAMINATED:
                    it mixes instrument, representativeness and model error, so
                    it must never be quoted as the observation's own error.

Only the first two are the observation's error.  The third is reported because
it is useful, and labelled because it is not the same thing.

Usage:
  python3 scripts/event_ingest.py                    # ingest what the archive holds
  python3 scripts/event_ingest.py --out docs/event-stream.jsonl
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Declared instrument accuracies.  These are specifications, so they are named
# as such: nothing here is a measurement made by this study.
DECLARED = {
    "airport.t":   {"k": 0.5, "source": "WMO/CIMO surface synoptic temperature accuracy"},
    "airport.td":  {"k": 0.5, "source": "WMO/CIMO surface synoptic dewpoint accuracy"},
    "airport.qnh": {"hpa": 0.1, "source": "WMO/CIMO barometer accuracy at station level"},
}

# Measured across comparisons, therefore contaminated by model and
# representativeness error and NOT the observation's own uncertainty.
OBSERVED_SCATTER = {
    "gfs.tmp2m.vs.airport.t": {"sd_k": 2.14, "n": 4770, "lead_h": 7,
                               "source": "block_pair.py, this session"},
}

# Positional layout of an airport station record in the archive index.
F_ICAO, F_LAT, F_LON, F_ELEV, F_TIME = 0, 1, 2, 3, 4
F_T, F_TD, F_QNH = 5, 6, 11


def event_id(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


def airport_events(archive: Path, limit_items: int) -> list[dict]:
    """One event per station observation.  Every field carries its own error."""
    out = []
    files = sorted(glob.glob(str(archive / "airport" / "*" / "index")))[-limit_items:]
    for f in files:
        d = json.loads(Path(f).read_text())
        issued = d.get("issued")
        for r in d.get("stations", []):
            if len(r) < 12 or r[F_TIME] is None:
                continue
            common = {"place": {"icao": r[F_ICAO], "lat": r[F_LAT], "lon": r[F_LON],
                                "elev_m": r[F_ELEV]},
                      "time": r[F_TIME],
                      "provenance": {"collection": "airport", "item": Path(f).parent.name,
                                     "issued": issued,
                                     "path": "xue STAC airport index, station tuple"}}
            for name, idx, unit in (("t", F_T, "degC"), ("td", F_TD, "degC"),
                                    ("qnh", F_QNH, "hPa")):
                v = r[idx]
                if v is None:
                    continue
                spec = DECLARED[f"airport.{name}"]
                key = "k" if "k" in spec else "hpa"
                out.append({
                    **common,
                    "event_id": event_id(r[F_ICAO], r[F_TIME], name),
                    "variable": f"airport.{name}",
                    "unit": unit,
                    "value": v,
                    "uncertainty": {"kind": "declared", "sigma": spec[key],
                                    "source": spec["source"]},
                })
    return out


def sar_density_event() -> dict:
    """A change-density measurement, with a COMPUTED uncertainty.

    The density is a proportion over counted pixels, so its standard error is
    binomial and follows from the record -- no specification and no
    cross-comparison needed.  This is the cleanest uncertainty in the study.

    The numbers are THIS STUDY'S OWN three-orbit result at Langtang, not the
    published one.  The first version of this function used 0.300 with n=5123,
    which was wrong twice over: 0.300 is the figure from the EarthArXiv note
    (500 m radius, 6 dB threshold -- a different quantity from ours, and
    RECORDED rather than observed here), and n=5123 was invented. A 500 m disc
    at 10 m posting holds 7,854 pixels, not 5,123.  Neither the value nor the
    count belonged to this study.

    `n` below is DERIVED from the stated geometry (a 0-2 km disc at the 20 m
    posting our change product uses), not counted from a saved mask, and it is
    labelled that way rather than presented as measured.
    """
    densities = [0.1250, 0.1231, 0.1305]      # three orbits, measured here
    p = sum(densities) / len(densities)
    radius_m, pixel_m = 2000.0, 20.0
    n = int(math.pi * radius_m ** 2 / pixel_m ** 2)
    sigma = math.sqrt(p * (1 - p) / n)
    return {
        "event_id": event_id("sar.langtang", "2026-08-26", "vv.change.density"),
        "variable": "sar.vv.change-density.source-region",
        "unit": "fraction",
        "value": p,
        "place": {"name": "Langtang Lirung, west flank", "lat": 28.2853, "lon": 85.5252},
        "time": "2026-08-26T02:52:10Z",
        "uncertainty": {"kind": "computed", "sigma": sigma,
                        "formula": "sqrt(p(1-p)/n)",
                        "n": n,
                        "n_provenance": "derived from the 0-2 km disc at 20 m "
                                        "posting, not counted from a mask",
                        "source": "binomial, from the count itself"},
        "provenance": {"collection": "sentinel-1",
                       "orbits": "three relative orbits, spread 0.73 points",
                       "measured": densities,
                       "note": "value and spread are this study's own; the "
                               "detachment coordinate is externally verified. "
                               "The published 0.300 (500 m, 6 dB) is a DIFFERENT "
                               "quantity and is recorded, not observed here.",
                       "reusable_rule": "density statistics are geometry-robust, "
                                        "area statistics are not"},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", default=str(ROOT / "archive"))
    ap.add_argument("--out", default=str(ROOT / "docs" / "event-stream.jsonl"))
    ap.add_argument("--items", type=int, default=2,
                    help="how many archived airport items to ingest")
    args = ap.parse_args()

    archive = Path(args.archive)
    ev = airport_events(archive, args.items)
    ev.append(sar_density_event())

    # No record may enter without a named uncertainty source.  A comparison
    # against an observation that has no error bar can only be asserted.
    for e in ev:
        u = e.get("uncertainty") or {}
        assert u.get("kind") in ("declared", "computed"), e["event_id"]
        assert u.get("source"), e["event_id"]
        assert e.get("provenance"), e["event_id"]

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for e in ev:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")

    kinds = {}
    vars_ = {}
    for e in ev:
        kinds[e["uncertainty"]["kind"]] = kinds.get(e["uncertainty"]["kind"], 0) + 1
        vars_[e["variable"]] = vars_.get(e["variable"], 0) + 1
    print(f"  事件 {len(ev)} 条 → {out}")
    for k, v in sorted(vars_.items()):
        print(f"    {k:<34}{v:>7}")
    print(f"  不确定度来源: {kinds}")
    print()
    print("  观测散布（受模式与代表性误差污染，【不是】观测自身误差）:")
    for k, v in OBSERVED_SCATTER.items():
        print(f"    {k}: sd {v['sd_k']} K (n={v['n']}, lead {v['lead_h']}h)")
    d = sar_density_event()
    print(f"\n  可计算的不确定度样例（本条的干净样例）:")
    print(f"    {d['variable']}: {d['value']:.3f} ± {d['uncertainty']['sigma']:.4f}"
          f"  ({d['uncertainty']['formula']}, n={d['uncertainty']['n']})")
    print(f"    即 {d['uncertainty']['sigma']/d['value']*100:.1f}% 的相对误差")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
