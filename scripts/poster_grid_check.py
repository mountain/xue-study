"""Verify the poster decode AND the poster's row/column -> lat/lon mapping.

WHY THIS CHECK EXISTS
---------------------
Every cross-model figure in this repository's figure set rests on one unproven
assumption: that a poster plane, once inflated and vertically un-filtered, is a
spherical field whose row 0 is the north pole and whose column 0 is 180 W.  The
decode itself is copied from xue's own `web/src/poster.ts`, so it is not in
doubt.  The GEOREFERENCE is -- nothing in `item.json` states which corner the
plane starts at, and a figure drawn on the wrong corner is not a slightly wrong
figure, it is a picture of a different piece of the planet.

So the mapping is tested against something that cannot be talked around: the
archived airport observations, which carry real latitudes and longitudes and a
real temperature at a real time.  Score the poster's tmp2m against the stations
under several candidate mappings.  The right one wins by a wide margin, and a
wrong one -- latitude flipped, longitude rolled -- loses.  If every candidate
scored the same, this check would be worthless, so the spread is reported.

A CONTROL THAT CAN FAIL
-----------------------
A mapping is accepted only if BOTH hold:
  * it has the lowest MAE of the candidates, and
  * the runner-up is worse by a margin that is large compared with the winner's
    own MAE (otherwise the test cannot separate them).
If neither holds, the script says the mapping is NOT established rather than
picking the best of a tie.

Usage:
  uv run --with numpy python scripts/poster_grid_check.py
"""

from __future__ import annotations

import argparse
import glob
import json
import zlib
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]

# Airport index row layout, as parsed by scripts/representativeness.py.
F_ICAO, F_LAT, F_LON, F_ELEV, F_TIME, F_T = 0, 1, 2, 3, 4, 5


def unfilter(plane: bytes, width: int, height: int) -> np.ndarray:
    a = np.frombuffer(plane, dtype=np.uint8).reshape(height, width).astype(np.uint64)
    return (np.cumsum(a, axis=0) % 256).astype(np.uint8)


def quantization_of(item_dir: Path, variable: str):
    man = item_dir / "manifest"
    if not man.exists():
        return None
    d = json.loads(man.read_text())
    for b in d.get("bundles", []):
        if b.get("variable") != variable:
            continue
        mj = (b.get("poster") or {}).get("metadataJson")
        if not mj:
            continue
        m = json.loads(mj) if isinstance(mj, str) else mj
        for v in m.get("variables", []):
            if v.get("id") == variable and v.get("quantization"):
                return v["quantization"]
    return None


def decode(archive: Path, item: str, variable: str):
    """Return (values_in_native_units, valid_mask, W, H, unit, run_time)."""
    item_dir = archive / item.split(".")[0] / item
    poster = item_dir / f"{variable}-poster"
    plane = zlib.decompress(poster.read_bytes())
    meta = json.loads((item_dir / "item.json").read_text())
    grid = (meta["assets"][f"{variable}-poster"].get("xue:grid") or {})
    w, h = grid["width"], grid["height"]
    if len(plane) != w * h:
        raise SystemExit(f"{item}/{variable}: plane {len(plane)} != {w}x{h}")
    codes = unfilter(plane, w, h).astype(np.float64)
    q = quantization_of(item_dir, variable)
    if q is None:
        raise SystemExit(f"{item}/{variable}: no quantization in the manifest")
    values = q["offset"] + codes * q["scale"]
    valid = (codes != q.get("nodataCode")) & (codes <= q.get("maximumCode", 255))
    unit = (meta["properties"].get("cube:variables", {}).get(variable, {})
            .get("unit"))
    run = meta["properties"].get("xue:runTime")
    return values, valid, w, h, unit, run


def candidate_axes(w: int, h: int, lat0: float, north_up: bool,
                   lon0: float, roll: bool):
    """The lat/lon of every plane cell under one mapping hypothesis.

    Two things are genuinely unknown and both are enumerated:

      * which END of the plane is the north pole -- hence `north_up`, which
        reverses the row order rather than the data;
      * which COLUMN is the seam of the longitude circle -- hence `roll`, which
        rotates the columns by half the width.

    The first version of this check wrote the roll as `(lon + 180) % 360 - 180`,
    which on a -180..180 axis is the identity: `roll` True and False returned
    the same MAE, so that candidate could not fail and tested nothing.  A roll
    only means something if it moves the seam to the middle of the axis.
    """
    step = 0.5
    order = np.arange(h)
    lat = lat0 - step * order if north_up else lat0 + step * order
    cols = (np.arange(w) + w // 2) % w if roll else np.arange(w)
    lon = (lon0 + step * cols + 180.0) % 360.0 - 180.0
    return lat, lon


def sample(values, valid, lat, lon, s_lat, s_lon):
    """Nearest-neighbour sample, returning the value and whether it was valid."""
    i = np.abs(lat[None, :] - s_lat[:, None]).argmin(axis=1)
    j = np.abs(lon[None, :] - s_lon[:, None]).argmin(axis=1)
    return values[i, j], valid[i, j]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", default=str(ROOT / "archive"))
    ap.add_argument("--item", default=None,
                    help="item id; default = the newest gfs item with a tmp2m poster")
    ap.add_argument("--variable", default="tmp2m")
    args = ap.parse_args()

    archive = Path(args.archive)
    item = args.item
    if item is None:
        items = sorted(p.name for p in (archive / "gfs").iterdir()
                       if (p / f"{args.variable}-poster").exists())
        item = items[-1]
    # The poster is the run's FIRST frame, so pairs come from the observation
    # batch whose valid time is closest to the run time.
    values, valid, w, h, unit, run = decode(archive, item, args.variable)
    run_t = np.datetime64(run.replace("Z", ""))
    best = None
    for f in sorted(glob.glob(str(archive / "airport" / "*" / "index"))):
        d = json.loads(Path(f).read_text())
        ts = [r[F_TIME] for r in d.get("stations", []) if len(r) > 12 and r[F_TIME]]
        if not ts:
            continue
        t = np.datetime64(sorted(ts)[len(ts) // 2].replace("Z", ""))
        gap = abs((t - run_t) / np.timedelta64(1, "m"))
        if best is None or gap < best[0]:
            best = (gap, f, d)
    gap, index_file, d = best

    rows = [r for r in d["stations"]
            if len(r) > 12 and r[F_T] is not None and r[F_TIME]]
    s_lat = np.array([r[F_LAT] for r in rows], dtype=float)
    s_lon = np.array([r[F_LON] for r in rows], dtype=float)
    s_t = np.array([r[F_T] for r in rows], dtype=float)
    print(f"poster   {item} · {args.variable} · {w}×{h} · unit {unit} · run {run}")
    print(f"stations {Path(index_file).parent.name} · {len(rows)} reports · "
          f"median valid time {gap:.0f} min from the run\n")
    if unit != "°C":
        print(f"  NOTE unit is {unit!r}; the delta below is in poster units")

    # The first frame of the poster is the analysis at the run time.  Compare it
    # with the station reports nearest that hour rather than with all 5,505.
    hours = np.array([np.datetime64(r[F_TIME].replace("Z", "")) for r in rows])
    near = np.abs((hours - run_t) / np.timedelta64(1, "m")) <= 60.0
    print(f"within ±60 min of the run: {int(near.sum())} reports\n")

    # Enumerate rather than assume.  The half-cell offset matters: a 0.25 deg
    # error puts every sample on a cell boundary, where nearest-neighbour
    # rounds inconsistently and the mapping degrades into a coin toss.  So the
    # offsets are swept, not guessed.
    OFFSETS = (0.0, -0.125, 0.125, -0.25, 0.25)
    results = []
    for north_up in (True, False):
        for off in OFFSETS:
            lat0 = (90.0 if north_up else -90.0) + off
            for lon_off in OFFSETS:
                for roll in (False, True):
                    lon0 = -180.0 + lon_off
                    lat, lon = candidate_axes(w, h, lat0, north_up, lon0, roll)
                    v, ok = sample(values, valid, lat, lon,
                                   s_lat[near], s_lon[near])
                    m = ok & np.isfinite(v)
                    if m.sum() < 50:
                        continue
                    err = v[m] - s_t[near][m]
                    results.append({
                        "lat0": lat0, "north_up": north_up, "lon0": lon0,
                        "roll": roll, "n": int(m.sum()),
                        "mae": float(np.abs(err).mean()),
                        "bias": float(err.mean()),
                    })
    # Two candidates that place every cell in the same grid box are the same
    # hypothesis wearing different labels; keep only the best of each group so
    # the runner-up is a genuinely different hypothesis.
    results.sort(key=lambda r: r["mae"])
    print(f"{'lat0':>8} {'n-up':>5} {'lon0':>9} {'roll':>5} {'n':>5} "
          f"{'MAE K':>7} {'bias K':>7}")
    for r in results[:6]:
        print(f"{r['lat0']:>8.3f} {str(r['north_up']):>5} {r['lon0']:>9.3f} "
              f"{str(r['roll']):>5} {r['n']:>5} {r['mae']:>7.2f} {r['bias']:>7.2f}")
    if len(results) < 2:
        print("\n判定：候选不足，映射【未建立】")
        return 1

    win = results[0]
    # The runner-up must be a DIFFERENT hypothesis: either the other pole order
    # or the other longitude seam.  A same-hypothesis neighbour differing only
    # by a sub-cell offset is not a competitor and must not be used to claim a
    # margin.
    rivals = [r for r in results[1:]
              if r["north_up"] != win["north_up"] or r["roll"] != win["roll"]]
    if not rivals:
        print("\n判定：没有第二个不同的假设可比，映射【未建立】")
        return 1
    second = rivals[0]
    margin = second["mae"] - win["mae"]
    print(f"\n最佳 {win['mae']:.2f} K，最强对手 {second['mae']:.2f} K"
          f"（north_up={second['north_up']}, roll={second['roll']}），"
          f"差 {margin:.2f} K（最佳自身的 {margin / win['mae']:.0%}）")
    established = margin > 0.5 * win["mae"]
    print("判定：" + (
        "映射成立 —— 最佳明显优于最强对手，南北翻转与经度滚动都被排除"
        if established else
        "映射【未建立】—— 最佳与最强对手差距不足以分开两个假设，不得据此作图"))
    print("\n  注意：这一条只保证「平面到经纬度的方向」正确。"
          "它不保证 poster 是模式的原始网格，poster 是 2 倍降采样后的网格。")
    return 0 if established else 1


if __name__ == "__main__":
    raise SystemExit(main())
