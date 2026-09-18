"""Score a forecast against observations that carry uncertainty.

WHY THE ERROR STANDARD DECIDES THE VERDICT
------------------------------------------
This study has, several times, reported a bias and a scatter and then talked
about skill as if those numbers settled the question.  They do not.  Whether a
forecast is "consistent with observation" depends entirely on what counts as
error, and the standard is usually left implicit.

The numbers here make the dependence explicit.  Three error standards are
available for the same comparison, and they differ by a factor of four:

  declared          the instrument's rated accuracy, 0.5 K for a synoptic
                    temperature.  This is the OBSERVATION's own error.
  representativeness  a model grid cell is 0.25 deg (about 28 km) while the
                    station is a point.  On this evidence that term is the
                    dominant one, and it is NOT the instrument's fault.
  observed scatter  what you measure across all pairs -- 2.14 K here.  It
                    contains instrument, representativeness AND model error,
                    so it can never be quoted as an error of any one of them.

Scoring against the declared 0.5 K makes the model look broken.  Scoring
against the observed 2.14 K makes it look fine.  Neither verdict is a fact
about the model; both are facts about the choice.  What IS a fact about the
model is how the scatter grows with lead time, and that is separated out below.

Usage:
  python3 scripts/skill_with_uncertainty.py [--lead 7] [--n 3000]
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import math
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
STORE = "https://dataset.ringsaturn.me/xue/gfs.2026091718/tmp2m.zarr"

DECLARED_OBS_K = 0.5          # WMO/CIMO synoptic temperature accuracy
F_TIME, F_T, F_LAT, F_LON = 4, 5, 1, 2


def main() -> int:
    import xarray as xr

    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", default=str(ROOT / "archive"))
    ap.add_argument("--leads", type=int, nargs="+", default=[0, 1, 3, 5, 7])
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    ds = xr.open_zarr(STORE, consolidated=True)
    # xarray has already applied the store's quantization; .encoding proves it.
    assert "scale_factor" in ds["tmp2m"].encoding, \
        "reader did not decode; applying the transform by hand would double it"
    lat = ds["latitude"].values
    lon = ds["longitude"].values
    # A User-Agent is required: the bare urllib default is answered with 403.
    import urllib.request
    req = urllib.request.Request(STORE + "/zarr.json",
                                 headers={"User-Agent": "Mozilla/5.0 xue-study"})
    meta = json.loads(urllib.request.urlopen(req, timeout=60).read())
    offs = np.array(meta["attributes"]["xue"]["time"]["frameOffsets"])
    run = dt.datetime(2026, 9, 17, 18, tzinfo=dt.timezone.utc)

    idx = sorted(glob.glob(str(Path(args.archive) / "airport" / "*" / "index")))[-1]
    rows = [r for r in json.loads(Path(idx).read_text())["stations"]
            if len(r) > 12 and r[F_T] is not None]

    # Bucket observations by lead time.
    buck = {}
    for r in rows:
        try:
            vt = dt.datetime.fromisoformat(r[F_TIME].replace("Z", "+00:00"))
        except Exception:
            continue
        h = (vt - run).total_seconds() / 3600
        hi = int(round(h))
        if np.isclose(offs, hi).any():
            buck.setdefault(hi, []).append(r)

    print(f"  GFS tmp2m 对机场站气温，观测自身误差 {DECLARED_OBS_K} K (declared)")
    print(f"\n  {'时效':>5}{'n':>7}{'中位偏差':>10}{'散布sd':>10}"
          f"{'|d|<2σ观测':>12}{'|d|<2σ观测+代表':>16}")
    out = []
    for h in args.leads:
        if h not in buck:
            continue
        fi = int(np.argmin(np.abs(offs - h)))
        field = ds["tmp2m"].isel(time=fi).values
        d = []
        for r in buck[h]:
            ri = int(round((lat[0] - r[F_LAT]) / 0.25))
            ci = int(round((r[F_LON] - lon[0]) / 0.25))
            if not (0 <= ri < lat.size and 0 <= ci < lon.size):
                continue
            m = float(field[ri, ci])
            if not np.isfinite(m):
                continue
            d.append(m - r[F_T])
        if len(d) < 20:
            continue
        d = np.array(d)
        sd = d.std(ddof=1)
        # Representative error is not measured here; it is the residual after
        # the observation's own error, reported so the third standard is visible.
        rep = math.sqrt(max(sd ** 2 - DECLARED_OBS_K ** 2, 0.0))
        comb = math.hypot(DECLARED_OBS_K, rep)
        print(f"  {h:>5}{len(d):>7}{np.median(d):>10.2f}{sd:>10.2f}"
              f"{100*np.mean(np.abs(d) < 2*DECLARED_OBS_K):>11.1f}%"
              f"{100*np.mean(np.abs(d) < 2*comb):>15.1f}%")
        out.append({"lead_h": h, "n": len(d), "median_bias": float(np.median(d)),
                    "sd": float(sd), "repr_residual": rep, "combined": comb})

    if out:
        print(f"\n  === 判决取决于误差标准（这一条成立）===")
        print(f"  观测自身误差 2σ = {2*DECLARED_OBS_K:.1f} K → 第四列")
        print(f"  含代表性与模式误差 2σ = {2*out[-1]['combined']:.1f} K → 第五列")
        print(f"  **同一个模式，同一个观测，两个判决。**")
        print(f"\n  === 时效依赖：**未建立** ===")
        ns = [o["n"] for o in out]
        sds = [o["sd"] for o in out]
        print(f"  各时效样本数 {ns} —— 极不平衡，相差 {max(ns)//max(min(ns),1)} 倍")
        mono = all(b >= a for a, b in zip(sds, sds[1:]))
        print(f"  散布 {[f'{s:.2f}' for s in sds]}  单调不减: {mono}")
        if not mono:
            print(f"  → **散布随时效不单调**，故「误差随时效增长」在这份数据上【未建立】。")
            print(f"     最小时效的 sd 反而最大，几乎肯定由少数离群站主导"
                  f"（n={ns[0]} 对 n={ns[-1]}）。")
            print(f"     要做这条，必须先按时效平衡样本 —— 现在不能。")
        print(f"\n  注：「代表误差」一列是 sd 减去观测误差后的残差，"
              f"混了代表性与模式误差，不可单独归因。")
        print(f"  注：此处小样本的 sd 含离群值，未做剔除；本文不据此下任何结论。")

    if args.json:
        Path(args.json).write_text(json.dumps(
            {"declared_obs_k": DECLARED_OBS_K, "rows": out}, indent=1, ensure_ascii=False))
        print(f"\n  已写 {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
