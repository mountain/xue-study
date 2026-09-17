#!/usr/bin/env python3
"""The fused index over named regions, from whatever windows are cached.

The GFS records already fetched are global grids, so once a window is on disk
every region of the Earth can be read out of it at no further network cost.  This
script does that: it builds the same index as `glacier_warning_index.py` --
liquid precipitation onto a snowpack, with the liquid test taken over the whole
six-hour window's minimum temperature -- and reports it per region and per
elevation band, ranking each year.

Regions are named boxes.  Two of them are the ones asked for, and one matters
because of a seasonality that a single global window cannot express:

    Tibet / Himalaya   the region the third problem card is about
    Peru / Andes       a glacierized range in the southern hemisphere, where
                       August is the dry season and a rain-on-ice window in
                       August is therefore the wrong season for it
    global >=4000 m    every high cell on Earth, as a reference

The southern-hemisphere point is not a detail.  Reading a Peru number out of an
August window and comparing it to the Tibet number would be comparing a dry
season against a wet one.  `--window` exists so the same code can be run over
the window each hemisphere actually has weather in.
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import sys
from concurrent.futures import ThreadPoolExecutor

import re

import numpy as np

CACHE = "/tmp"
HOURS = ["00", "06", "12", "18"]
MIN_MM = 1.0
REGIONS = {
    "Tibet / Himalaya": {"lat": (25.0, 40.0), "lon": (70.0, 105.0)},
    "Peru / Andes": {"lat": (-18.0, -8.0), "lon": (-80.0, -68.0)},
    "Karakoram / Hindu Kush": {"lat": (33.0, 40.0), "lon": (70.0, 80.0)},
    "Alaska / Yukon": {"lat": (58.0, 64.0), "lon": (-155.0, -135.0)},
    "Patagonia": {"lat": (-52.0, -46.0), "lon": (-75.0, -71.0)},
}
BANDS = [(2500, 3500, "2500-3500 m"), (3500, 4500, "3500-4500 m"),
         (4500, 5500, "4500-5500 m"), (5500, 10 ** 9, ">=5500 m")]


def load(stamp: str, hour: str, key: str):
    import rasterio
    try:
        with rasterio.open(f"{CACHE}/_gw_{stamp}_{hour}_{key}.grib2") as source:
            return source.read(1).astype(np.float64)
    except Exception:  # noqa: BLE001
        return None


def window_days(start: str, days: int) -> list[str]:
    first = dt.datetime.strptime("2026" + start, "%Y%m%d")
    return [(first + dt.timedelta(days=k)).strftime("%m%d") for k in range(days)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", type=int, nargs="+",
                    default=[2021, 2022, 2023, 2024, 2025, 2026])
    ap.add_argument("--start", default="0812", help="MMDD start of the window")
    ap.add_argument("--days", type=int, default=15)
    ap.add_argument("--json", metavar="PATH")
    args = ap.parse_args()

    import rasterio
    with rasterio.open(f"{CACHE}/_gw_orog.grib2") as source:
        orography = source.read(1).astype(np.float64)
        transform, height, width = source.transform, source.height, source.width
    lon = transform.c + transform.a * (np.arange(width) + 0.5)
    lat = transform.f + transform.e * (np.arange(height) + 0.5)
    lon2d, lat2d = np.meshgrid(lon, lat)

    days = window_days(args.start, args.days)
    # file names are _gw_<stamp>_<hour>_<key>.grib2, so the stamp is field 2
    have = set()
    for path in glob.glob(f"{CACHE}/_gw_*_apcp.grib2"):
        parts = path.rsplit("/", 1)[-1].split("_")
        if len(parts) >= 3 and re.fullmatch(r"\d{8}", parts[2]):
            have.add(parts[2])
    missing = [(y, d) for y in args.years for d in days
               if f"{y}{d}" not in have]
    print(f"window {args.start} + {args.days} days, {len(args.years)} years; "
          f"{len(missing)} of {len(args.years) * len(days)} year-days not cached")
    if missing:
        print(f"  first missing: {missing[:3]} -- run glacier_warning_index.py "
              f"--start {args.start} to fetch them")

    # accumulate per year, globally
    totals = {y: np.zeros_like(orography) for y in args.years}
    counts = {y: 0 for y in args.years}

    def one(task):
        year, day = task
        if f"{year}{day}" not in have:
            return year, None
        acc = np.zeros_like(orography)
        for hour in HOURS:
            stamp = f"{year}{day}"
            a = load(stamp, hour, "apcp")
            t = load(stamp, hour, "tmin")
            w = load(stamp, hour, "weasd")
            if a is None or t is None or w is None:
                return year, None
            acc += np.where((a >= MIN_MM) & (t > 0.0) & (w > 0.0), a, 0.0)
        return year, acc

    tasks = [(y, d) for y in args.years for d in days]
    done = 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        for year, acc in pool.map(one, tasks):
            done += 1
            if acc is None:
                continue
            totals[year] += acc
            counts[year] += 1
            if done % 20 == 0:
                print(f"  {done}/{len(tasks)}", flush=True)

    print(f"  year-days accumulated: "
          f"{ {y: counts[y] for y in args.years} }")

    results: dict = {}
    print(f"\nliquid precipitation onto snowpack, mm per cell, summed over the window")
    for name, box in REGIONS.items():
        inside = ((lat2d >= box["lat"][0]) & (lat2d <= box["lat"][1])
                  & (lon2d >= box["lon"][0]) & (lon2d <= box["lon"][1]))
        if not inside.any():
            continue
        print(f"\n--- {name}  {box['lat']}N x {box['lon']}E ---")
        print(f"{'band':<14}{'cells':>7}" + "".join(f"{y:>9}" for y in args.years)
              + f"{'rank of last':>14}")
        for low, high, label in BANDS:
            band = inside & (orography >= low) & (orography < high)
            if not band.any():
                continue
            values = {}
            for y in args.years:
                if counts[y] == 0:
                    continue
                values[y] = float(np.nanmean(totals[y][band]))
            if not values:
                continue
            ordered = sorted(values.items(), key=lambda kv: -kv[1])
            rank = [y for y, _ in ordered].index(args.years[-1]) + 1
            print(f"{label:<14}{int(band.sum()):>7}"
                  + "".join(f"{values.get(y, float('nan')):>9.1f}" for y in args.years)
                  + f"{rank:>13}/{len(ordered)}")
            results.setdefault(name, {})[label] = {"values": values, "rank": rank,
                                                   "cells": int(band.sum())}

    global_band = orography >= 4000
    values = {y: float(np.nanmean(totals[y][global_band])) for y in args.years
              if counts[y]}
    ordered = sorted(values.items(), key=lambda kv: -kv[1])
    print(f"\n--- global land above 4000 m  ({int(global_band.sum())} cells) ---")
    print("  " + "  ".join(f"{y}: {v:.1f}" for y, v in values.items()))
    print(f"  rank of {args.years[-1]}: "
          f"{[y for y, _ in ordered].index(args.years[-1]) + 1}/{len(ordered)}")
    results["global>=4000m"] = {"values": values}

    print("\nWHAT THIS IS: one index over named boxes, one window, six years.")
    print("WHAT IT IS NOT: comparable across hemispheres.  August is the wet")
    print("season in High Mountain Asia and the dry season in the Andes, so a")
    print("Peru number read out of an August window is a dry-season number and")
    print("putting it beside a Tibet number compares two different seasons.")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump({"window": f"{args.start}+{args.days}d", "regions": results},
                      handle, indent=2, ensure_ascii=False, default=str)
            handle.write("\n")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
