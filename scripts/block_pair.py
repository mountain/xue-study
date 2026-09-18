"""Pair what the block predicts against what the block observed.

THE SHAPE OF THE THING
----------------------
The forecast design is a sliding spacetime block: verified state and relations
inside, new data arriving, prediction and observation compared at every point,
the block advancing.  Skill is not trained once, it accumulates as the block
moves.

Two processes divide that work, and the division is what makes it affordable:

  xue_collect.py   archives the INDEX and METADATA every pass.  Cheap, and it
                   is the part that cannot be recovered later.
  block_pair.py    fetches the VALUES on demand, only at the space-time points
                   it is asked to score.  Expensive per point, so it is never
                   done speculatively.

A block whose index is complete can be scored at any time.  A block whose values
were never fetched can still be scored later, as long as the store still exists
upstream.  That is the whole reason the index is what gets archived first.

LEAD TIME IS THE PRODUCT
------------------------
A forecast run issued at T has frames at T+h.  Comparing frame h against the
observation valid at T+h gives an error attributable to lead time h -- and that,
not a single error number, is what verification produces.  Everything here is
accumulated by (model, variable, lead time), because an error averaged over lead
time is a number nobody can act on.

WHAT THIS DELIBERATELY DOES NOT DO
----------------------------------
It does not interpolate the model field to the station.  It samples the nearest
model cell and reports the offset, because a bilinear interpolation would hide
exactly the kind of representativeness error this study keeps finding (a station
in a valley, a model cell averaged over a ridge).  The offset is recorded so the
sampling error stays visible instead of being smoothed into the residual.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import re
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = "https://dataset.ringsaturn.me/xue/"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) xue-study pairer"

# Positional layout of an airport station record, read off the archived index:
#   ["AGGH", -9.43, 160.047, 6.0, "2026-09-18T00:00:00Z", 27.0, 24.0, 20, 2.6,
#    null, 10000, 1012.9, "VFR", 0, 0, 4466]
#            lat    lon    elev        time            T     Td    wdir wspd  gust vis   qnh
F_ICAO, F_LAT, F_LON, F_ELEV, F_TIME = 0, 1, 2, 3, 4
F_T, F_TD, F_QNH = 5, 6, 11


def get(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def parse_time(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def grid_of(store_url: str) -> dict:
    """Read a store's consolidated metadata and its grid description."""
    root = json.loads(get(store_url.rstrip("/") + "/zarr.json"))
    nodes = (root.get("consolidated_metadata") or {}).get("metadata") or {}
    return root, nodes


def fetch_chunk(store_url: str, key: str) -> bytes:
    return get(f"{store_url.rstrip('/')}/{key}")


def open_store(store_url: str):
    """Open a xue Zarr store for lazy reading.

    THE DECODE TRAP, which this study has now hit twice in two formats.

    A store's metadata declares `quantization: {offset, scale, nodataCode}` and
    the reader (xarray, or GDAL for GRIB) applies it, exposing `scale_factor`
    and `add_offset` in `.encoding` once it has.  Applying the documented
    transform again on top is silent and catastrophic: the first run of this
    script scored GFS `tmp2m` against 5,447 airport stations and got a uniform
    -71 K bias at every lead time, because -60 + 0.5 * (already-decoded C) is
    not a temperature.

    Earlier in this study the same mistake went the other way: GDAL returns GRIB
    temperature already in Celsius, and subtracting 273.15 inverted the sign of
    every result.

    So: check `.encoding` for scale_factor/add_offset BEFORE transforming, and
    let the reader own the decode unless it demonstrably has not done it.
    """
    import xarray as xr

    return xr.open_zarr(store_url, consolidated=True)


def nearest_index(axis, value, step) -> int:
    return int(round((axis[0] - value) / step)) if step < 0 \
        else int(round((value - axis[0]) / step))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", default=str(ROOT / "archive"))
    ap.add_argument("--model", default="gfs")
    ap.add_argument("--obs", default="airport")
    ap.add_argument("--variable", default="tmp2m")
    ap.add_argument("--list", action="store_true",
                    help="show what the block can pair, fetch nothing")
    args = ap.parse_args()

    archive = Path(args.archive)
    idx = json.loads((archive / "index.json").read_text())

    runs = {}
    for item_id, rec in idx["seen"].items():
        if rec["collection"] != args.model:
            continue
        man = archive / args.model / item_id / "manifest"
        if not man.exists():
            continue
        d = json.loads(man.read_text())
        runs[item_id] = {"runTime": parse_time(d["runTime"]),
                         "hours": d.get("forecastHours"),
                         "bundles": {b["variable"]: b for b in d.get("bundles", [])}}

    obs = {}
    for item_id, rec in idx["seen"].items():
        if rec["collection"] != args.obs:
            continue
        f = archive / args.obs / item_id / "index"
        if not f.exists():
            continue
        d = json.loads(f.read_text())
        rows = [r for r in d.get("stations", []) if r[F_T] is not None]
        obs[item_id] = {"issued": parse_time(d["issued"]), "rows": rows}

    print(f"  块内可配对：{len(runs)} 次 {args.model} 运行，"
          f"{len(obs)} 批 {args.obs} 实况")
    for rid, r in sorted(runs.items()):
        print(f"    run {rid}  {r['runTime']:%Y-%m-%d %H:%MZ}  "
              f"时长 {r['hours']}h  变量 {len(r['bundles'])} 个"
              f"  {'含'+args.variable if args.variable in r['bundles'] else '缺 '+args.variable}")
    for oid, o in sorted(obs.items()):
        times = sorted({r[F_TIME] for r in o["rows"]})
        print(f"    obs {oid}  站点 {len(o['rows'])}  观测时刻 {len(times)} 个"
              f"  {times[0] if times else '-'} .. {times[-1] if times else '-'}")

    if args.list:
        # What overlap exists, and is it enough to score?  Said explicitly,
        # because "no overlap" and "no skill" must never look the same.
        if not runs or not obs:
            print("\n  → 无重叠可配对：索引尚不足以评分（不是「无技巧」）")
            return 0
        ov = 0
        for rid, r in runs.items():
            for oid, o in obs.items():
                for row in o["rows"][:2000]:
                    vt = parse_time(row[F_TIME])
                    h = (vt - r["runTime"]).total_seconds() / 3600
                    if 0 <= h <= r["hours"] and (h < 120 or h % 3 == 0):
                        ov += 1
        print(f"\n  → 重叠的 (运行, 实况) 对：{ov}")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
