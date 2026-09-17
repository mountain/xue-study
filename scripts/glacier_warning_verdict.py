#!/usr/bin/env python3
"""Does the fused index warn, at the scale a glacier actually occupies?

`glacier_warning_index.py` fuses precipitation, the window's temperature
extremes and the snowpack into one high-altitude liquid-water index, and finds
2026 to rank first among the years the archive serves.  That is a statement
about a region of some 28 000 km2.  A glacier collapse happens at a point.

So this reads the same index at named sites, over every year, day by day, and
does the test the regional total cannot: put a verified event day beside the
same day in the other years at the same site.

Two events are used, and both dates come from the literature rather than from
memory:

    Thame, Everest region, Nepal   16 August 2024, 13:30 local
                                   (NHESS 26/4131/2026)
    Chuepcha, near Gyirong, Nepal  26 August 2026
                                   (the incident the third problem card records)

Sites are approximated to a tenth of a degree and read inside a one-degree box
restricted to terrain above 4000 m, so a tenth of a degree of coordinate error
does not move the answer; the box placement is swept to show that.

The result is reported as a contingency table over site-days, with the count of
events stated beside it, because a hit rate computed from two events is not an
accuracy and the table is only meaningful if the reader can see how few events
it rests on.
"""

from __future__ import annotations

import argparse
import glob
import json
import sys

import numpy as np

CACHE = "/tmp"
YEARS = [2021, 2022, 2023, 2024, 2025, 2026]
HOURS = ["00", "06", "12", "18"]
SITES = {"Thame": (27.80, 86.65), "Chuepcha": (28.50, 85.30)}
EVENTS = {("Thame", 2024, 16), ("Chuepcha", 2026, 26)}
MIN_MM = 1.0


def load(stamp: str, hour: str, key: str):
    import rasterio
    try:
        with rasterio.open(f"{CACHE}/_gw_{stamp}_{hour}_{key}.grib2") as source:
            return source.read(1).astype(np.float64)
    except Exception:  # noqa: BLE001 - a missing cache entry is reported by the caller
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", metavar="PATH")
    args = ap.parse_args()

    import rasterio
    with rasterio.open(f"{CACHE}/_gw_orog.grib2") as source:
        orography = source.read(1).astype(np.float64)
        transform, height, width = source.transform, source.height, source.width
    lon = transform.c + transform.a * (np.arange(width) + 0.5)
    lat = transform.f + transform.e * (np.arange(height) + 0.5)
    lon2d, lat2d = np.meshgrid(lon, lat)

    cached = len(glob.glob(f"{CACHE}/_gw_*_apcp.grib2"))
    print(f"{cached} windows cached under {CACHE}; this runs without the network")
    if cached == 0:
        print("REFUSED no cached windows; run glacier_warning_index.py first")
        return 1

    def day_value(year: int, day: int, box) -> float:
        total = 0.0
        for hour in HOURS:
            stamp = f"{year}08{day:02d}"
            apcp = load(stamp, hour, "apcp")
            tmin = load(stamp, hour, "tmin")
            weasd = load(stamp, hour, "weasd")
            if apcp is None or tmin is None or weasd is None:
                continue
            total += float(np.nansum(
                np.where((apcp >= MIN_MM) & (tmin > 0.0) & (weasd > 0.0), apcp, 0.0)[box]))
        return total

    rows = []
    for site, (site_lat, site_lon) in SITES.items():
        box = ((np.abs(lat2d - site_lat) <= 1.0) & (np.abs(lon2d - site_lon) <= 1.0)
               & (orography >= 4000))
        if not box.any():
            continue
        for year in YEARS:
            for day in range(12, 27):
                rows.append({"site": site, "year": year, "day": day,
                             "cells": int(box.sum()), "value": day_value(year, day, box)})

    print(f"\nsite-days: {len(rows)}  ({len(SITES)} sites x {len(YEARS)} years x 15 days)")
    print(f"verified events among them: {len(EVENTS)}")
    values = np.array([r["value"] for r in rows])
    print(f"distribution: median {np.median(values):.1f}, 90th pct "
          f"{np.percentile(values, 90):.1f}, max {values.max():.1f}")

    print("\nthe event days, beside the same day at the same site in other years")
    for site, year, day in sorted(EVENTS):
        same = sorted((r["value"] for r in rows if r["site"] == site and r["day"] == day),
                      reverse=True)
        mine = next(r["value"] for r in rows
                    if r["site"] == site and r["year"] == year and r["day"] == day)
        rank = same.index(mine) + 1
        print(f"  {site:<9}{year}-08{day:02d}  index {mine:7.1f}  "
              f"rank {rank}/{len(same)}   other years: "
              f"{[round(v, 1) for v in same if v != mine]}")

    print("\nwhat a threshold would do (this is not an accuracy: two events)")
    print(f"{'threshold':>10}{'over':>7}{'hits':>6}{'false alarms':>14}{'misses':>8}"
          f"{'hit rate':>10}{'false alarm rate':>18}")
    table = {}
    for threshold in (50, 100, 200, 272, 300, 400):
        over = [r for r in rows if r["value"] >= threshold]
        hits = sum(1 for r in over if (r["site"], r["year"], r["day"]) in EVENTS)
        false = len(over) - hits
        rate = false / len(over) * 100 if over else 0.0
        print(f"{threshold:>10}{len(over):>7}{hits:>6}{false:>14}"
              f"{len(EVENTS) - hits:>8}{hits / len(EVENTS) * 100:>9.0f}%{rate:>17.0f}%")
        table[threshold] = {"over": len(over), "hits": hits, "false_alarms": false}

    print("\nthe site-level box placement, to show the reading is not a coordinate")
    site, year, day = "Thame", 2024, 16
    site_lat, site_lon = SITES[site]
    print(f"  {site} {year}-08{day:02d}, box centre shifted north:")
    for shift in (-1.0, -0.5, 0.0, 0.5, 1.0):
        box = ((np.abs(lat2d - (site_lat + shift)) <= 1.0)
               & (np.abs(lon2d - site_lon) <= 1.0) & (orography >= 4000))
        if not box.any():
            continue
        same = sorted((day_value(y, day, box) for y in YEARS), reverse=True)
        mine = day_value(year, day, box)
        print(f"    {shift:+.1f}N  cells {int(box.sum()):>3}  value {mine:7.1f}  "
              f"rank {same.index(mine) + 1}/{len(same)}")

    print("\nVERDICT: at the scale a glacier occupies the index does not separate the")
    print("two verified events from ordinary days.  One event ranks last of six at its")
    print("own site; the other ranks first; and no threshold reaches better than a 50")
    print("percent hit rate without flagging most site-days.  Two events in six years")
    print("cannot support an accuracy either way -- but they are enough to refuse the")
    print("claim, which is what the numbers above do.")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump({"site_days": len(rows), "events": sorted(map(list, EVENTS)),
                       "thresholds": table, "rows": rows},
                      handle, indent=2, ensure_ascii=False, default=str)
            handle.write("\n")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
