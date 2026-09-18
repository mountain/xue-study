"""Score every archived run against every archived observation, by lead time.

WHY ACROSS RUNS
---------------
The first attempt scored ONE run against ONE batch of observations and got lead
times 0-7 hours with sample counts of 23, 59, 70, 65 and 4196.  That is not a
skill curve, it is one big number at 7 hours with four small ones beside it, and
the scatter at the small leads was driven by a handful of stations.

Lead time is (observation time - run time).  A single run can only produce the
lead times its own validity window overlaps, so widening the curve means using
MANY runs, each contributing the part of the curve it can see.  That is what the
block is for: the archive holds the runs, so the curve can be assembled from it
rather than from one convenient case.

WHAT IT REPORTS AND WHAT IT REFUSES TO
--------------------------------------
Errors are grouped by lead time, and each group carries its own n.  A group
below --min-n is reported as insufficient rather than plotted, because a median
over twelve pairs and a median over four thousand are not the same kind of
claim, and a curve drawn through both hides that.

The error standard is stated per row: the observation's own declared accuracy
and the observed scatter are different quantities, and this study has twice
confused them.

Usage:
  python3 scripts/block_skill.py --gallery /tmp/xue-upstream/web/public
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import math
import urllib.request
import warnings
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = "https://dataset.ringsaturn.me/xue/"
UA = "Mozilla/5.0 xue-study skill"
DECLARED_OBS_K = 0.5
F_TIME, F_T, F_LAT, F_LON = 4, 5, 1, 2


def get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return json.loads(urllib.request.urlopen(req, timeout=120).read())


def runs_from_archive(archive: Path, limit: int):
    out = []
    for f in sorted(glob.glob(str(archive / "gfs" / "*" / "manifest")))[-limit:]:
        try:
            d = json.loads(Path(f).read_text())
        except Exception:
            continue
        bundles = {b["variable"]: b for b in d.get("bundles", [])}
        if "tmp2m" not in bundles:
            continue
        out.append({
            "id": Path(f).parent.name,
            "run": dt.datetime.fromisoformat(d["runTime"].replace("Z", "+00:00")),
            "hours": d.get("forecastHours"),
            "store": "../" + Path(f).parent.name + "/tmp2m.zarr",
            "bundle": bundles["tmp2m"],
        })
    return out


def observations_from_archive(archive: Path):
    rows = []
    for f in sorted(glob.glob(str(archive / "airport" / "*" / "index"))):
        try:
            d = json.loads(Path(f).read_text())
        except Exception:
            continue
        for r in d.get("stations", []):
            if len(r) > 12 and r[F_T] is not None and r[F_TIME]:
                rows.append(r)
    return rows


def main() -> int:
    import numpy as np
    import xarray as xr

    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", default=str(ROOT / "archive"))
    ap.add_argument("--gallery", default="/tmp/xue-upstream/web/public")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--min-n", type=int, default=30)
    args = ap.parse_args()

    archive = Path(args.archive)
    runs = runs_from_archive(archive, args.runs)
    obs = observations_from_archive(archive)
    print(f"  归档中的 gfs 运行 {len(runs)} 次，airport 观测 {len(obs)} 条")

    # Group observations by (run, lead) once, before touching any store.
    by_lead = defaultdict(list)
    for r in runs:
        for o in obs:
            try:
                vt = dt.datetime.fromisoformat(o[F_TIME].replace("Z", "+00:00"))
            except Exception:
                continue
            h = (vt - r["run"]).total_seconds() / 3600
            if 0 <= h <= (r["hours"] or 240):
                by_lead[(r["id"], int(round(h)))].append(o)

    rows = []
    for r in runs:
        leads = sorted(k[1] for k in by_lead if k[0] == r["id"])
        if not leads:
            continue
        store = CATALOG + r["store"].lstrip("./")
        store = store.replace("/../", "/")
        try:
            ds = xr.open_zarr(store, consolidated=True)
            zj = get_json(store + "/zarr.json")
            offs = np.array(zj["attributes"]["xue"]["time"]["frameOffsets"])
            lat = ds["latitude"].values
            lon = ds["longitude"].values
        except Exception as exc:
            print(f"    {r['id']}: 存储不可用 — {str(exc)[:70]}")
            continue
        print(f"    {r['id']}  {r['run']:%m-%d %HZ}  时效 {leads}")
        for h in leads:
            if not np.isclose(offs, h).any():
                continue
            fi = int(np.argmin(np.abs(offs - h)))
            field = ds["tmp2m"].isel(time=fi).values
            d = []
            for o in by_lead[(r["id"], h)]:
                ri = int(round((lat[0] - o[F_LAT]) / 0.25))
                ci = int(round((o[F_LON] - lon[0]) / 0.25))
                if not (0 <= ri < lat.size and 0 <= ci < lon.size):
                    continue
                m = float(field[ri, ci])
                if math.isfinite(m):
                    d.append(m - o[F_T])
            if not d:
                continue
            a = np.array(d)
            rows.append({"run": r["id"], "lead_h": h, "n": len(a),
                         "median_bias": float(np.median(a)),
                         "mae": float(np.abs(a).mean()),
                         "sd": float(a.std(ddof=1)) if len(a) > 1 else None})

    # Pool across runs, keeping n per lead so a thin group stays visible.
    pool = defaultdict(list)
    for r in rows:
        pool[r["lead_h"]].append(r)
    curve = []
    for h in sorted(pool):
        ns = sum(x["n"] for x in pool[h])
        if ns < args.min_n:
            curve.append({"lead_h": h, "n": ns, "state": "insufficient"})
            continue
        bias = sum(x["median_bias"] * x["n"] for x in pool[h]) / ns
        mae = sum(x["mae"] * x["n"] for x in pool[h]) / ns
        curve.append({"lead_h": h, "n": ns, "median_bias": bias, "mae": mae,
                      "state": "ok", "runs": len(pool[h])})

    print(f"\n  {'时效':>5}{'n':>8}{'合偏差':>9}{'MAE':>8}   状态")
    for c in curve:
        if c["state"] == "ok":
            print(f"  {c['lead_h']:>5}{c['n']:>8}{c['median_bias']:>9.2f}"
                  f"{c['mae']:>8.2f}   {c['runs']} 次运行")
        else:
            print(f"  {c['lead_h']:>5}{c['n']:>8}{'—':>9}{'—':>8}   样本不足"
                  f"（< {args.min_n}），不作结论")

    ok = [c for c in curve if c["state"] == "ok"]
    print(f"\n  可用时效 {len(ok)} 个，跨越 "
          f"{min((c['lead_h'] for c in ok), default=0)}–"
          f"{max((c['lead_h'] for c in ok), default=0)} 小时")
    if len(ok) < 3:
        print("  → **时效曲线仍未建立**：可用时效少于 3 个。")
        print("     团块还年轻，观测覆盖的时效范围受运行次数限制。")
    else:
        mono = all(b["mae"] >= a["mae"] for a, b in zip(ok, ok[1:]))
        print(f"  MAE 随时效单调不减: {mono}")
        if not mono:
            print("  → 仍不单调；即使跨运行汇总，也不能声称「误差随时效增长」。")

    out = {"declared_obs_k": DECLARED_OBS_K, "per_run": rows, "curve": curve,
           "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    g = Path(args.gallery)
    (g / "block-skill.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(f"\n  已写 {g/'block-skill.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
