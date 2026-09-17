#!/usr/bin/env python3
"""Cross-check the CMA radar mosaic against a GFS forecast over the same window.

The radar product declares a ``nodataCode`` it never writes, so a cell with no
echo is ambiguous between "no rain" and "no radar".  This script breaks the tie
from outside: it compares where the radar saw echo with where an independent
system -- the GFS precipitation field -- said it would rain.

The comparison is run over boxes spanning all three possible regimes, so the
answer is read off a *reference frame* rather than an absolute threshold:

  offshore-bay-of-bengal   far outside every Chinese radar's range
  offshore-arabian-sea     likewise
  ctrl-east-china          dense radar coverage, active weather
  ctrl-north-china         dense radar coverage, quieter weather
  himalaya-tibet           the box in question

If the Himalaya box scores like the offshore boxes, the radar is blind there.
If it scores like the East-China control, the radar sees the Himalaya and a low
echo fraction is a measurement.  Neither verdict is asserted here: the script
prints the contingency over a grid of thresholds so the reading does not depend
on one cut point.

Method, stated so its limits are visible:

  * radar "echo" is any code above the codebook minimum, i.e. reflectivity > 0
    dBZ -- a *reflectivity* threshold, not a rain-rate threshold;
  * the model side is ``prate``, an instantaneous rate, sampled hourly, reduced
    over the window by its maximum ("did the model rain at any point in this
    window") because that is the analogue of the radar's "ever echoed";
  * the radar mask is coarsened onto the model grid by the fraction of radar
    cells echoing inside each model cell, and only model cells wholly inside
    the radar domain are used;
  * the model is a forecast, not truth.  Agreement here corroborates that the
    radar echo is meteorological; disagreement over a dry forecast is weak
    evidence either way.  The offshore boxes carry the argument, because the
    physics there is not in doubt: radar range is ~230 km.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from urllib.parse import urljoin

import numpy as np
import xarray as xr

BASE = "https://dataset.ringsaturn.me/xue/"
UA = {"User-Agent": "xue-study/1.0 (+radar-vs-model-check)"}

BOXES = {
    "himalaya-tibet": (80.0, 92.0, 26.0, 32.0),
    "ctrl-east-china": (110.0, 122.0, 25.0, 35.0),
    "ctrl-north-china": (110.0, 120.0, 35.0, 42.0),
    "offshore-bay-of-bengal": (85.0, 92.0, 15.0, 20.0),
    "offshore-arabian-sea": (68.0, 74.0, 12.0, 18.0),
    "himalaya-north-half": (80.0, 92.0, 30.0, 32.0),
    "himalaya-south-half": (80.0, 92.0, 26.0, 29.0),
}

RADAR_FRAC_THRESHOLDS = (0.00, 0.02, 0.05, 0.10, 0.25)
MODEL_RATE_THRESHOLDS = (0.02, 0.10, 0.50, 1.00)


def fetch(url: str, attempts: int = 6, timeout: int = 60) -> bytes:
    last: Exception | None = None
    for i in range(attempts):
        try:
            return urllib.request.urlopen(
                urllib.request.Request(url, headers=UA), timeout=timeout).read()
        except Exception as exc:  # noqa: BLE001 - transient network only
            last = exc
            time.sleep(2 + 2 * i)
    raise RuntimeError(f"failed after {attempts} attempts: {url}") from last


def fetch_json(url: str):
    return json.loads(fetch(url))


def open_radar(window: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Load one radar window; ``window`` is ``<run>/<build>``, e.g. cma.2026091702/0442."""
    item_url = urljoin(BASE, f"{window}/item.json")
    item = fetch_json(item_url)
    href = urljoin(item_url, item["assets"]["cref"]["href"])
    raw = xr.open_zarr(href, mask_and_scale=False)
    return (np.asarray(raw["cref"].values, dtype=np.uint8),
            np.asarray(raw["time"].values),
            np.asarray(raw["latitude"].values),
            np.asarray(raw["longitude"].values))


def epoch_seconds(times: np.ndarray) -> np.ndarray:
    """datetime64[ns] -> int64 seconds since the epoch.

    ``.tolist()`` on a datetime64[ns] array yields integers, not datetimes, so
    every timestamp in this script is carried as an explicit epoch second.
    """
    return times.astype("datetime64[s]").astype(np.int64)


def iso(second: int) -> str:
    return np.datetime_as_string(np.datetime64(int(second), "s"))


def merge_windows(windows: list[str]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """De-overlap several rolling windows into one frame stack, keyed by timestamp.

    Overlapping frames are required to agree cell for cell; if they do not, the
    rolling window is not a stable view and every downstream number is suspect,
    so this fails loudly rather than picking a winner.
    """
    frames: dict[int, np.ndarray] = {}
    for window in windows:
        codes, times, lat, lon = open_radar(window)
        for t, frame in zip(epoch_seconds(times).tolist(), codes):
            if t in frames:
                if not np.array_equal(frames[t], frame):
                    raise SystemExit(
                        f"overlapping frame {iso(t)}Z differs between windows: the "
                        "rolling window is not a stable view")
            frames[t] = frame
    keys = np.array(sorted(frames), dtype=np.int64)
    stack = np.stack([frames[int(k)] for k in keys])
    print(f"radar  {len(keys)} frames from {iso(keys[0])[11:16]} to "
          f"{iso(keys[-1])[11:16]}Z over {len(windows)} window(s), "
          f"{stack.shape[1]}x{stack.shape[2]} cells")
    return stack, keys, lat, lon


def open_model(variable: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, dict, dict]:
    pointer = fetch_json(urljoin(BASE, "latest.json"))
    item_url = urljoin(BASE, pointer["manifestPath"].replace("manifest.json", "item.json"))
    item = fetch_json(item_url)
    href = urljoin(item_url, item["assets"][variable]["href"])
    raw = xr.open_zarr(href)
    meta = raw[variable].attrs["xue"]["variable"]
    return (np.asarray(raw[variable].values, dtype=np.float64),
            np.asarray(raw["time"].values),
            np.asarray(raw["latitude"].values),
            np.asarray(raw["longitude"].values),
            item, meta)


def coarsen_onto(mask: np.ndarray, rlat: np.ndarray, rlon: np.ndarray,
                 glat: np.ndarray, glon: np.ndarray) -> np.ndarray:
    """Fraction of radar cells echoing inside each model cell; NaN if not covered."""
    dlat = abs(float(rlat[1] - rlat[0]))
    dlon = abs(float(rlon[1] - rlon[0]))
    hlat = abs(float(glat[1] - glat[0])) / 2.0
    hlon = abs(float(glon[1] - glon[0])) / 2.0

    # radar latitude decreases with index; solve rlat[0] - dlat*j in the half-open
    # interval (centre - hlat, centre + hlat]
    j_lo = np.ceil(((rlat[0] - hlat) - glat) / dlat).astype(np.int64)
    j_hi = np.ceil(((rlat[0] + hlat) - glat) / dlat).astype(np.int64)
    # radar longitude increases with index; interval [centre - hlon, centre + hlon)
    i_lo = np.ceil(((glon - hlon) - rlon[0]) / dlon).astype(np.int64)
    i_hi = np.ceil(((glon + hlon) - rlon[0]) / dlon).astype(np.int64)

    out = np.full((glat.size, glon.size), np.nan)
    for m in range(glat.size):
        a, b = int(j_lo[m]), int(j_hi[m])
        if a < 0 or b > rlat.size or a >= b:
            continue
        for k in range(glon.size):
            c, d = int(i_lo[k]), int(i_hi[k])
            if c < 0 or d > rlon.size or c >= d:
                continue
            block = mask[a:b, c:d]
            if block.size:
                out[m, k] = block.mean()
    return out


def pearson(x: np.ndarray, y: np.ndarray) -> float:
    if x.size < 3 or x.std() == 0 or y.std() == 0:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--window", action="append", required=True, metavar="RUN/BUILD",
                    help="radar window, repeatable; e.g. cma.2026091702/0442")
    ap.add_argument("--variable", default="prate", help="model variable (default prate)")
    ap.add_argument("--json", metavar="PATH", help="write the measurement as JSON")
    ap.add_argument("--only", action="append", default=[], metavar="NAME",
                    help="restrict the report to these boxes (repeatable)")
    ap.add_argument("--box", action="append", default=[], metavar="NAME:W,E,S,N",
                    help="add or replace a box, e.g. band2830:80,92,28,30 (repeatable)")
    args = ap.parse_args()
    global BOXES
    for spec in args.box:
        name, _, coords = spec.partition(":")
        parts = coords.split(",")
        if len(parts) != 4:
            ap.error(f"--box {spec!r}: expected NAME:W,E,S,N")
        try:
            BOXES[name] = tuple(float(x) for x in parts)
        except ValueError:
            ap.error(f"--box {spec!r}: coordinates must be numbers")
    if args.only:
        unknown = [n for n in args.only if n not in BOXES]
        if unknown:
            ap.error(f"unknown box(es) {unknown}; known: {sorted(BOXES)}")
        BOXES = {n: BOXES[n] for n in args.only}

    codes, keys, rlat, rlon = merge_windows(args.window)
    echo = codes > 0

    model, mtimes, mlat, mlon, mitem, meta = open_model(args.variable)
    unit = meta["unit"]
    print(f"model  {args.variable} [{unit}] on {mlat.size}x{mlon.size} "
          f"({abs(mlat[1] - mlat[0]):.2f} deg), run {mitem['properties'].get('xue:runTime')}")

    # model frames whose valid time lies inside the radar's observed span
    mseconds = epoch_seconds(mtimes)
    inside = np.flatnonzero((mseconds >= int(keys[0])) & (mseconds <= int(keys[-1]) + 3600))
    if inside.size == 0:
        raise SystemExit("no model frame lies inside the radar window")
    print(f"       {inside.size} frame(s) inside the radar span: "
          + ", ".join(iso(mseconds[i])[11:16] for i in inside[:8])
          + (" ..." if inside.size > 8 else ""))

    rate_max = model[inside].max(axis=0)
    rate_mean = model[inside].mean(axis=0)

    ever = echo.any(axis=0)
    fraction = coarsen_onto(ever, rlat, rlon, mlat, mlon)
    print(f"       coarsened onto the model grid: "
          f"{int(np.isfinite(fraction).sum())} cells inside the radar domain")

    print()
    header = (f"{'box':<26}{'cells':>7}{'radar%':>9}{'model%':>9}"
              f"{'both%':>8}{'r-only%':>9}{'m-only%':>9}{'r':>8}")
    print(header)
    print("-" * len(header))

    summary: dict = {"windows": args.window, "variable": args.variable, "unit": unit,
                     "radar_frames": int(len(keys)),
                     "radar_span": [iso(keys[0]) + "Z", iso(keys[-1]) + "Z"], "boxes": {}}
    for name, (west, east, south, north) in BOXES.items():
        rows = np.flatnonzero((mlat >= south) & (mlat < north))
        cols = np.flatnonzero((mlon >= west) & (mlon < east))
        if rows.size == 0 or cols.size == 0:
            continue
        f = fraction[np.ix_(rows, cols)].ravel()
        r = rate_max[np.ix_(rows, cols)].ravel()
        good = np.isfinite(f)
        f, r = f[good], r[good]
        if f.size == 0:
            print(f"{name:<26}{0:>7}   (no model cell wholly inside the radar domain)")
            continue
        radar_yes = f > 0.0
        model_yes = r >= 0.10
        item = {
            "cells": int(f.size),
            "radar_any_pct": float(radar_yes.mean() * 100.0),
            "model_any_pct": float(model_yes.mean() * 100.0),
            "both_pct": float((radar_yes & model_yes).mean() * 100.0),
            "radar_only_pct": float((radar_yes & ~model_yes).mean() * 100.0),
            "model_only_pct": float((~radar_yes & model_yes).mean() * 100.0),
            "pearson": pearson(f, r),
        }
        summary["boxes"][name] = item
        print(f"{name:<26}{item['cells']:>7}{item['radar_any_pct']:>9.1f}"
              f"{item['model_any_pct']:>9.1f}{item['both_pct']:>8.1f}"
              f"{item['radar_only_pct']:>9.1f}{item['model_only_pct']:>9.1f}"
              f"{item['pearson']:>8.3f}")

    print()
    print("    radar%   model cells where the radar ever echoed (any sub-cell, any frame)")
    print(f"    model%   model cells where {args.variable} reached 0.10 {unit} at some frame")
    print("    both%    both said yes")
    print("    r-only%  radar had echo, model stayed dry   <- unexplained by the model")
    print("    m-only%  model had rain, radar stayed clear <- candidate blind spot")
    print("    r        Pearson correlation of echo fraction against peak model rate")

    print()
    print("threshold sweep (share of cells where both agree, and hit rate), "
          "radar-fraction x model-rate")
    print(f"{'box':<26}" + "".join(f"{g:>9.2f}" for g in MODEL_RATE_THRESHOLDS))
    sweep = {}
    for name, (west, east, south, north) in BOXES.items():
        rows = np.flatnonzero((mlat >= south) & (mlat < north))
        cols = np.flatnonzero((mlon >= west) & (mlon < east))
        if rows.size == 0 or cols.size == 0:
            continue
        f = fraction[np.ix_(rows, cols)].ravel()
        r = rate_max[np.ix_(rows, cols)].ravel()
        good = np.isfinite(f)
        f, r = f[good], r[good]
        if f.size == 0:
            continue
        line, row = f"{name:<26}", {}
        for g in MODEL_RATE_THRESHOLDS:
            model_yes = r >= g
            radar_yes = f > 0.0
            positives = model_yes.sum()
            hit = (radar_yes & model_yes).sum() / positives if positives else float("nan")
            row[f"{g:.2f}"] = float(hit)
            line += f"{hit:>9.3f}"
        sweep[name] = row
        print(line)
    print("    each column: of the model's rain cells at that rate, the share the radar echoed in")

    summary["sweep_hit_rate"] = sweep
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(summary, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
