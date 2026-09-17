#!/usr/bin/env python3
"""Two checks that put the anchors to work: one on theta-e, one on forecast skill.

Both compare a published field against something a station or an ascent actually
measured.  The predictions are stated here, before the code that tests them, so
that a failure is visible as a failure rather than as a reinterpretation.

  thetae   P1  At an ascent whose surface pressure is below 850 hPa, the published
               `thetae850` at that station's cell exceeds the theta-e computed with
               Bolton (1980) from the air the ascent measured at the surface.
           P2  The excess is a dose-response: it grows as the surface pressure
               falls further below 850 hPa.  Stated as a monotone trend in bins of
               (850 - Ps), pooled over every ascent, not only the deepest ones.

  skill    P3  The 2 m temperature error against station anchors grows with
               forecast lead time, even across the five hours the live products
               allow.

Why only five hours: this repository's retention claim records that no xue family
keeps an archive.  A run is published one at a time, and the airport product holds
24 hours per station, so the overlap of "what the model forecast" and "what a
station measured" is however long the newest run has been alive.  That is a
consequence of the measured retention, not a choice made here.

Formulation reuse: the Bolton implementation is the one already validated against
the published field at +0.083 K mean bias, imported from `thetae_check.py` rather
than rewritten, so the two cannot drift apart.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin

import numpy as np
import xarray as xr

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from anchor_check import (  # noqa: E402
    AIRPORT_ROW, BASE, UA, fetch, fetch_json, frame_at, nearest, open_field)


def fetch_status(url: str) -> tuple[int, bytes, dict]:
    import urllib.error
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
            return r.status, r.read(), {}
    except urllib.error.HTTPError as exc:
        return exc.code, b"", {}
from thetae_check import bolton_theta_e  # noqa: E402

SOUNDING_INDEX = "latest-sounding.json"
AIRPORT_INDEX = "latest-airport.json"
MOMENT = dt.datetime(2026, 9, 17, 0, tzinfo=dt.timezone.utc)


def specific_humidity_from_dewpoint(dewpoint_c, pressure_hpa):
    """q from Td and p, Magnus saturation vapour pressure inverted."""
    e = 6.112 * np.exp(17.67 * dewpoint_c / (dewpoint_c + 243.5))
    return 0.622 * e / (pressure_hpa - 0.378 * e)


def load_soundings():
    pointer = fetch_json(urljoin(BASE, SOUNDING_INDEX))
    index_url = urljoin(BASE, pointer["path"])
    index = fetch_json(index_url)
    data_url = urljoin(index_url, index["soundings"]["path"])

    def pull(row):
        headers = dict(UA)
        headers["Range"] = f"bytes={row['offset']}-{row['offset'] + row['length'] - 1}"
        try:
            return json.loads(urllib.request.urlopen(
                urllib.request.Request(data_url, headers=headers), timeout=90).read())
        except Exception:  # noqa: BLE001
            return None

    with ThreadPoolExecutor(max_workers=16) as pool:
        return [r for r in pool.map(pull, index["stations"]) if r]


def surface_level(ascent, elev):
    """The level the ascent stood on: its reported height matches the station's."""
    p, t, td, z = ascent["p"], ascent["t"], ascent["td"], ascent["z"]
    cand = [i for i in range(len(p))
            if z[i] is not None and z[i] > -30000 and abs(z[i] - elev) <= 150]
    if not cand:
        return None
    return max(cand, key=lambda i: p[i])


def cmd_thetae(args, cache) -> dict:
    thetae, t_times, lat, lon = cache("thetae850")
    frame = frame_at(t_times, MOMENT)
    print(f"theta-e anchor, model frame {frame} ({np.datetime_as_string(t_times[frame])})")

    records = load_soundings()
    rows = []
    skipped = 0
    for rec in records:
        if rec["elev"] is None:
            continue
        for ascent in rec["soundings"]:
            if not ascent["time"].startswith(MOMENT.strftime("%Y-%m-%dT%H")):
                continue
            k = surface_level(ascent, rec["elev"])
            if k is None:
                skipped += 1
                continue
            t, td, p = ascent["t"][k], ascent["td"][k], ascent["p"][k]
            if None in (t, td) or t <= -30000 or td <= -30000:
                skipped += 1
                continue
            rows.append({"wmo": rec["wmo"], "lat": rec["lat"], "lon": rec["lon"],
                         "elev": rec["elev"], "ps": p / 100.0,
                         "t_c": t / 100.0 - 273.15, "td_c": td / 100.0 - 273.15})
    print(f"  ascents with a surface level: {len(rows)}  (skipped {skipped})")

    q = specific_humidity_from_dewpoint(np.array([r["td_c"] for r in rows]),
                                        np.array([r["ps"] for r in rows]))
    mine = bolton_theta_e(np.array([r["t_c"] for r in rows]), q,
                          np.array([r["ps"] for r in rows]))
    published = nearest(thetae[frame], lat, lon, [r["lat"] for r in rows],
                        [r["lon"] for r in rows])
    for r, m, pub in zip(rows, mine, published):
        r["thetae_measured_surface"] = float(m)
        r["thetae_published_850"] = None if not np.isfinite(pub) else float(pub)
    usable = [r for r in rows if r["thetae_published_850"] is not None]
    for r in usable:
        r["excess"] = r["thetae_published_850"] - r["thetae_measured_surface"]
        r["deficit"] = 850.0 - r["ps"]          # positive = 850 hPa below ground

    under = [r for r in usable if r["deficit"] > 0]
    over = [r for r in usable if r["deficit"] <= 0]
    print(f"\n  P1  where 850 hPa is below the ground (n={len(under)}):")
    if under:
        worse = sum(1 for r in under if r["excess"] > 0)
        e = np.array([r["excess"] for r in under])
        print(f"      published exceeds measured: {worse}/{len(under)}"
              f"   median excess {np.median(e):+.2f} K   range {e.min():+.2f}..{e.max():+.2f}")
    print(f"  P1  where 850 hPa exists (n={len(over)}):")
    if over:
        worse = sum(1 for r in over if r["excess"] > 0)
        e = np.array([r["excess"] for r in over])
        print(f"      published exceeds measured: {worse}/{len(over)}"
              f"   median excess {np.median(e):+.2f} K   range {e.min():+.2f}..{e.max():+.2f}")
    print(f"      P1 {'HOLDS' if under and sum(1 for r in under if r['excess'] > 0) / len(under) > 0.8 else 'FAILS'}")

    print("\n  P2  dose-response, bins of (850 - Ps) in hPa:")
    edges = [(-10 ** 9, -50), (-50, -20), (-20, 0), (0, 20), (20, 50), (50, 100), (100, 10 ** 9)]
    trend = []
    for lo, hi in edges:
        sel = [r for r in usable if lo <= r["deficit"] < hi]
        if not sel:
            continue
        e = np.array([r["excess"] for r in sel])
        label = f"{'-inf' if lo < -10 ** 8 else f'{lo:+d}'}..{'+inf' if hi > 10 ** 8 else f'{hi:+d}'}"
        print(f"      {label:>14}  n={len(sel):>4}  median excess {np.median(e):+7.2f} K")
        trend.append((lo, float(np.median(e)), len(sel)))
    positive = [t for t in trend if t[0] >= 0]
    monotone = all(positive[i][1] <= positive[i + 1][1] for i in range(len(positive) - 1))
    print(f"      P2 {'HOLDS' if monotone and len(positive) >= 3 else 'DOES NOT HOLD as a monotone trend'}")

    deepest = sorted(usable, key=lambda r: -r["deficit"])[:6]
    if deepest:
        print("\n  the deepest cases:")
        for r in deepest:
            print(f"      {r['wmo']} elev {r['elev']:>6.0f} m  Ps {r['ps']:6.1f}  "
                  f"measured surface theta-e {r['thetae_measured_surface']:7.2f} K  "
                  f"published 850 {r['thetae_published_850']:7.2f} K  "
                  f"excess {r['excess']:+7.2f} K")
    print("\n  NOT ESTABLISHED: that Bolton is the right convention or that the")
    print("  published number is wrong.  850 hPa below the ground has no measured")
    print("  theta-e to be wrong about; what is measured here is the distance between")
    print("  a published value and the value the air at that place actually had.")
    return {"n": len(usable), "under": len(under), "monotone": monotone}


def cmd_skill(args, cache) -> dict:
    tmp2m, times, lat, lon = cache("tmp2m")
    seconds = times.astype("datetime64[s]").astype(np.int64)
    run_time = int(seconds[0])
    print(f"forecast skill, model run begins {np.datetime_as_string(times[0])}")

    pointer = fetch_json(urljoin(BASE, AIRPORT_INDEX))
    index_url = urljoin(BASE, pointer["path"])
    index = fetch_json(index_url)
    history_url = urljoin(index_url, index["history"]["path"])
    print(f"  fetching the whole history file ({index['history']['byteLength']:,} B) "
          f"-- the analyst's route the spec names")
    blob = fetch(history_url).decode("utf-8", "replace")

    stations, observations = [], defaultdict(dict)
    for line in blob.splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        la, lo, elev = rec.get("lat"), rec.get("lon"), rec.get("elev")
        if la is None or lo is None:
            continue
        stations.append({"icao": rec["icao"], "lat": la, "lon": lo, "elev": elev})
        for metar in rec.get("metars") or []:
            t = metar.get("t")
            if t is None:
                continue
            moment = dt.datetime.fromisoformat(metar["time"].replace("Z", "+00:00"))
            observations[rec["icao"]][int(moment.timestamp())] = t
    points = [(s["lat"], s["lon"]) for s in stations]
    print(f"  stations {len(stations)}  observations {sum(len(v) for v in observations.values())}")

    print(f"\n{'lead h':>7}{'n':>7}{'median bias':>13}{'MAE':>9}{'RMSE':>9}")
    out = {}
    for lead in args.leads:
        target = run_time + lead * 3600
        frame = int(np.argmin(np.abs(seconds - target)))
        if abs(int(seconds[frame]) - target) > 1800:
            continue
        model = nearest(tmp2m[frame], lat, lon, [p[0] for p in points], [p[1] for p in points])
        errs = []
        for s, m in zip(stations, model):
            if not np.isfinite(m):
                continue
            obs = observations.get(s["icao"], {})
            if not obs:
                continue
            nearest_s = min(obs, key=lambda k: abs(k - target))
            if abs(nearest_s - target) > args.window_seconds:
                continue
            errs.append(m - obs[nearest_s])
        if not errs:
            continue
        e = np.array(errs)
        print(f"{lead:>7}{len(e):>7}{np.median(e):>13.2f}{np.abs(e).mean():>9.2f}"
              f"{np.sqrt((e ** 2).mean()):>9.2f}")
        out[lead] = {"n": int(e.size), "median": float(np.median(e)),
                     "mae": float(np.abs(e).mean()), "rmse": float(np.sqrt((e ** 2).mean()))}
    if len(out) >= 2:
        leads = sorted(out)
        grew = out[leads[-1]]["rmse"] > out[leads[0]]["rmse"]
        print(f"\n  P3  RMSE at {leads[0]} h = {out[leads[0]]['rmse']:.2f} K, "
              f"at {leads[-1]} h = {out[leads[-1]]['rmse']:.2f} K")
        print(f"      P3 {'HOLDS' if grew else 'FAILS -- no growth detected over this span'}")
        print("      A five-hour span may simply be too short for the trend to exceed")
        print("      the spread between stations; a failure here is not evidence that")
        print("      forecasts do not degrade.")
    print(f"\n  The span is capped by retention, not by choice: the run is published one")
    print(f"  at a time and the station product holds 24 hours, so only the hours since")
    print(f"  {np.datetime_as_string(times[0])} have both a forecast and a measurement.")
    return out


def discover_runs(days: int = 5) -> list[str]:
    """Every GFS cycle the bucket still serves, newest first.

    The pointer names one run, but the run directories outlive it, and it is the
    directories that make a skill curve possible: several runs forecasting the
    same valid hour give that hour several lead times, which is what separates
    lead from time of day.
    """
    now = dt.datetime.now(dt.timezone.utc).replace(minute=0, second=0, microsecond=0)
    stamps, t = [], now
    while t > now - dt.timedelta(days=days):
        if t.hour % 6 == 0:
            stamps.append(t.strftime("%Y%m%d%H"))
        t -= dt.timedelta(hours=1)

    def probe(stamp):
        try:
            code, _, _ = fetch_status(urljoin(BASE, f"gfs.{stamp}/manifest.json"))
            return stamp if code == 200 else None
        except Exception:  # noqa: BLE001
            return None

    with ThreadPoolExecutor(max_workers=12) as pool:
        return [s for s in pool.map(probe, stamps) if s]


def cmd_skill_runs(args, cache) -> dict:
    runs = args.runs.split(",") if args.runs else discover_runs(args.days)
    only = getattr(args, "tier", None)
    print(f"GFS runs still served: {len(runs)}  ({', '.join(runs)})")
    if only:
        print(f"  restricted to the {only} tier, so no lead is compared at a different "
              f"resolution from another")

    pointer = fetch_json(urljoin(BASE, AIRPORT_INDEX))
    index_url = urljoin(BASE, pointer["path"])
    index = fetch_json(index_url)
    blob = fetch(urljoin(index_url, index["history"]["path"])).decode("utf-8", "replace")
    obs: dict[str, dict[int, float]] = defaultdict(dict)
    where: dict[str, tuple] = {}
    for line in blob.splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec.get("lat") is None or rec.get("lon") is None:
            continue
        where[rec["icao"]] = (rec["lat"], rec["lon"])
        for metar in rec.get("metars") or []:
            if metar.get("t") is None:
                continue
            moment = dt.datetime.fromisoformat(metar["time"].replace("Z", "+00:00"))
            obs[rec["icao"]][int(moment.timestamp())] = metar["t"]
    ic = list(where)
    lats = [where[k][0] for k in ic]
    lons = [where[k][1] for k in ic]
    print(f"  stations {len(ic)}  observations {sum(len(v) for v in obs.values())}")

    samples: list[tuple[int, float, str, int]] = []   # lead, error, icao, valid epoch
    tiers: dict[str, str] = {}
    for run in runs:
        field = times = mlat = mlon = None
        for want in ((only,) if only else ("full", "half")):
            try:
                field, times, mlat, mlon = open_field("tmp2m", run, tier=want)
                tiers[run] = want
                break
            except Exception:  # noqa: BLE001
                continue
        if field is None:
            print(f"  {run}: unreadable (neither tier served)")
            continue
        seconds = times.astype("datetime64[s]").astype(np.int64)
        run_time = int(seconds[0])
        wanted = set()
        for icao in ic:
            for stamp in obs[icao]:
                k = int(np.argmin(np.abs(seconds - stamp)))
                if abs(int(seconds[k]) - stamp) <= args.window_seconds:
                    wanted.add(k)
        got = 0
        for k in sorted(wanted):
            model = nearest(field[k], mlat, mlon, lats, lons)
            valid = int(seconds[k])
            for icao, m in zip(ic, model):
                if not np.isfinite(m) or valid not in obs[icao]:
                    continue
                samples.append((round((valid - run_time) / 3600), float(m - obs[icao][valid]),
                                icao, valid))
                got += 1
        print(f"  {run}: {len(wanted)} frames, {got} matched pairs   [tier {tiers[run]}]")
        del field

    if not samples:
        print("\n  no matched pairs -- nothing to report")
        return {}
    leads = sorted({s[0] for s in samples})
    print(f"\n{'lead h':>7}{'n':>8}{'stations':>10}{'median bias':>13}{'MAE':>9}{'RMSE':>9}")
    by_lead = {}
    for lead in leads:
        sel = [s for s in samples if s[0] == lead]
        e = np.array([s[1] for s in sel])
        by_lead[lead] = {"n": len(e), "median": float(np.median(e)),
                         "mae": float(np.abs(e).mean()),
                         "rmse": float(np.sqrt((e ** 2).mean())),
                         "stations": len({s[2] for s in sel})}
        print(f"{lead:>7}{len(e):>8}{by_lead[lead]['stations']:>10}"
              f"{np.median(e):>13.2f}{np.abs(e).mean():>9.2f}{np.sqrt((e ** 2).mean()):>9.2f}")

    common = sorted(set.intersection(*[set(obs[k]) for k in ic])) if ic else []
    print("\n  the same valid hour seen at several leads (this is what removes the")
    print("  time-of-day confound that a single run cannot):")
    hours = defaultdict(dict)
    for lead, error, icao, valid in samples:
        hours[valid].setdefault(lead, []).append(error)
    multi = {v: d for v, d in hours.items() if len(d) >= 3}
    print(f"    valid hours with three or more leads: {len(multi)}")
    for valid in sorted(multi)[-4:]:
        d = multi[valid]
        row = "  ".join(f"{lead}h {np.abs(np.array(d[lead])).mean():.2f}" for lead in sorted(d))
        print(f"      {dt.datetime.fromtimestamp(valid, dt.timezone.utc):%m-%d %HZ}  {row}")
    # The pair that matters: one valid hour, two lead times, so the time of day
    # is held fixed and only the lead differs.
    paired = []
    for valid, d in hours.items():
        if len(d) < 2:
            continue
        lo, hi = min(d), max(d)
        paired.append((lo, np.abs(np.array(d[lo])).mean(), hi, np.abs(np.array(d[hi])).mean()))
    if paired:
        a = np.array([p[1] for p in paired]); b = np.array([p[3] for p in paired])
        print(f"\n  paired comparison over {len(paired)} valid hours, time of day held fixed:")
        print(f"    mean MAE at the shortest available lead ({min(p[0] for p in paired)} h): {a.mean():.3f} K")
        print(f"    mean MAE at the longest  available lead ({max(p[2] for p in paired)} h): {b.mean():.3f} K")
        print(f"    growth {b.mean() - a.mean():+.3f} K  ({(b.mean() - a.mean()) / a.mean() * 100:+.1f}%)")
        print(f"    hours where the longer lead was worse: {int((b > a).sum())}/{len(paired)}")
    if len(set(tiers.values())) > 1:
        print(f"\n  WARNING: the runs above do not all carry the same tier ({tiers}).")
        print(f"  Leads from different tiers are measured at different resolutions, so a")
        print(f"  growth in error across them mixes skill decay with a resolution change.")
        print(f"  `tier-control` measures that change on a run that has both tiers.")
    print(f"\n  A run directory is not a run: two of the manifests served here "
          f"(gfs.2026091600, gfs.2026091418)")
    print(f"  name stores that now return 404, so the readable runs are three and the")
    print(f"  gap at leads 13-17 is the 12Z cycle, which is not served at all.")
    print(f"  The span is bounded by two measured retentions: the station product holds")
    print(f"  about 16 hours of observations, and only {len(by_lead) and 3} runs still have stores.")
    return {"by_lead": by_lead, "paired_hours": len(paired),
            "paired_growth_k": float(b.mean() - a.mean()) if paired else None}


def cmd_tier_control(args, cache) -> dict:
    """How much of the apparent skill decay is actually a resolution change?

    The runs are not uniform: one carries only the half store (0.5 degrees) and
    the next only the full one (0.25 degrees).  Leads drawn from different tiers
    are then compared at different resolutions.  This measures the penalty on a
    single run that serves both, so the two effects can be separated.
    """
    run = args.runs or "2026091700"
    print(f"tier control on gfs.{run}: the same run, both tiers, same valid hours")

    pointer = fetch_json(urljoin(BASE, AIRPORT_INDEX))
    index_url = urljoin(BASE, pointer["path"])
    index = fetch_json(index_url)
    blob = fetch(urljoin(index_url, index["history"]["path"])).decode("utf-8", "replace")
    obs: dict[str, dict[int, float]] = defaultdict(dict)
    where: dict[str, tuple] = {}
    for line in blob.splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec.get("lat") is None or rec.get("lon") is None:
            continue
        where[rec["icao"]] = (rec["lat"], rec["lon"])
        for metar in rec.get("metars") or []:
            if metar.get("t") is None:
                continue
            moment = dt.datetime.fromisoformat(metar["time"].replace("Z", "+00:00"))
            obs[rec["icao"]][int(moment.timestamp())] = metar["t"]
    ic = list(where); lats = [where[k][0] for k in ic]; lons = [where[k][1] for k in ic]

    per_tier: dict[str, dict[int, list[float]]] = {}
    for tier in ("full", "half"):
        try:
            field, times, mlat, mlon = open_field("tmp2m", run, tier=tier)
        except Exception as error:  # noqa: BLE001
            print(f"  {tier}: unavailable ({type(error).__name__})")
            continue
        seconds = times.astype("datetime64[s]").astype(np.int64)
        run_time = int(seconds[0])
        wanted = set()
        for icao in ic:
            for stamp in obs[icao]:
                k = int(np.argmin(np.abs(seconds - stamp)))
                if abs(int(seconds[k]) - stamp) <= args.window_seconds:
                    wanted.add(k)
        acc: dict[int, list[float]] = defaultdict(list)
        for k in sorted(wanted):
            model = nearest(field[k], mlat, mlon, lats, lons)
            valid = int(seconds[k])
            for icao, m in zip(ic, model):
                if np.isfinite(m) and valid in obs[icao]:
                    acc[round((valid - run_time) / 3600)].append(float(m - obs[icao][valid]))
        per_tier[tier] = acc
        grid = field.shape[1:]
        print(f"  {tier:<5} grid {grid[1]}x{grid[0]}  leads {min(acc)}..{max(acc)}  "
              f"n={sum(len(v) for v in acc.values())}")
        del field

    if len(per_tier) < 2:
        print("\n  only one tier available here -- the penalty cannot be measured")
        return {}
    shared = sorted(set(per_tier["full"]) & set(per_tier["half"]))
    print(f"\n{'lead h':>7}{'full MAE':>11}{'half MAE':>11}{'penalty':>10}")
    penalties = []
    for lead in shared:
        a = np.abs(np.array(per_tier["full"][lead])).mean()
        b = np.abs(np.array(per_tier["half"][lead])).mean()
        penalties.append(b - a)
        print(f"{lead:>7}{a:>11.3f}{b:>11.3f}{b - a:>+10.3f}")
    print(f"\n  mean resolution penalty (half minus full): {np.mean(penalties):+.3f} K")
    print(f"  for comparison, the paired lead growth reported by `skill-runs` was +0.191 K")
    print(f"  NOT ESTABLISHED: that this penalty is constant across leads or regions;")
    print(f"  it is measured on one run over the leads that run covers.")
    return {"mean_penalty_k": float(np.mean(penalties)), "leads": len(shared)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["thetae", "skill", "skill-runs", "tier-control", "all"])
    ap.add_argument("--runs", help="comma-separated GFS runs; default: discover")
    ap.add_argument("--days", type=int, default=5, help="days back to discover runs")
    ap.add_argument("--tier", choices=["full", "half"],
                    help="restrict every run to one tier, so a growth in error cannot "
                         "be a resolution change (the tiers are NOT uniform across runs)")
    ap.add_argument("--leads", type=int, nargs="+", default=[0, 1, 2, 3, 4, 5])
    ap.add_argument("--window-seconds", type=int, default=1800)
    ap.add_argument("--json", metavar="PATH")
    args = ap.parse_args()

    cache_store: dict = {}

    def cache(variable):
        if variable not in cache_store:
            cache_store[variable] = open_field(variable)
        return cache_store[variable]

    results = {}
    if args.command in ("thetae", "all"):
        results["thetae"] = cmd_thetae(args, cache)
    if args.command in ("skill", "all"):
        results["skill"] = cmd_skill(args, cache)
    if args.command in ("skill-runs", "all"):
        results["skill_runs"] = cmd_skill_runs(args, cache)
    if args.command in ("tier-control", "all"):
        results["tier_control"] = cmd_tier_control(args, cache)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(results, handle, indent=2, ensure_ascii=False, default=str)
            handle.write("\n")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
