"""Was the pre-collapse trigger condition rare, or ordinary?

The Cuojian ice avalanche (Nepal, 2026-08-26) is documented by Yao Tandong and
colleagues as triggered by meltwater reaching the glacier bed, with the observed
condition at an automatic station 31 km away being a ten-plus day run in which
**the daily minimum never fell below 0 C**, a mean of 7.4 C and a maximum above
16 C. A station is one point. This asks the question a forecast product would
have to answer: over High Mountain Asia, how much area carried that condition
in the run-up, and how does that compare with the same window in earlier years?

The answer decides whether an atmospheric field can carry this trigger at all.
If the condition covers a large area every year while collapses are rare, then
melt-degree-days have no discriminative power here and saying otherwise would be
dishonest. If August 2026 stands out, it is a candidate signal worth pursuing.

Everything is read from GFS 0.25 degree analyses (f000 = the analysis) on NOAA's
public bucket, one GRIB record per time by byte range, decoded with GDAL.

Usage: uv run python scripts/collapse_trigger_check.py [out.json]
"""

from __future__ import annotations

import io
import json
import sys
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import rasterio

BUCKET = "https://noaa-gfs-bdp-pds.s3.amazonaws.com/gfs.{day}/{hour}/atmos/gfs.t{hour}z.pgrb2.0p25.f000"
REGION = (25.0, 40.0, 70.0, 105.0)  # south, north, west, east — High Mountain Asia
HOURS = ("00", "06", "12", "18")
WINDOW = (date(2026, 8, 12), date(2026, 8, 26))  # the paper's "ten-plus days"
YEARS = (2026, 2024, 2025)
PHRASE = ":TMP:2 m above ground:"
OROGRAPHY = ":HGT:surface:"


def fetch(url: str, byte_range: tuple[int, int] | None = None) -> bytes:
    headers = {"User-Agent": "xue-study/1.0 (collapse trigger check)"}
    if byte_range:
        headers["Range"] = f"bytes={byte_range[0]}-{byte_range[1]}"
    request = urllib.request.Request(url, headers=headers)
    return urllib.request.urlopen(request, timeout=90).read()


def field(day: date, hour: str):
    base = BUCKET.format(day=day.strftime("%Y%m%d"), hour=hour)
    try:
        index = fetch(f"{base}.idx").decode()
        lines = index.strip().split("\n")
        for i, line in enumerate(lines):
            if PHRASE in line:
                start = int(line.split(":")[1])
                end = int(lines[i + 1].split(":")[1]) - 1 if i + 1 < len(lines) else start + 900_000
                raw = fetch(base, (start, end))
                with rasterio.open(io.BytesIO(raw)) as source:
                    return source.read(1), source.transform, source.width, source.height
        return None
    except Exception as exc:  # noqa: BLE001 - report and continue
        print(f"    {day} {hour}Z  SKIPPED — {type(exc).__name__}: {str(exc)[:60]}")
        return None


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else "collapse-trigger.json"
    south, north, west, east = REGION
    results = {}

    for year in YEARS:
        offset = (date(year, 8, 12) - WINDOW[0]).days
        start, end = WINDOW[0] + timedelta(days=offset), WINDOW[1] + timedelta(days=offset)
        days = []
        for step in range((end - start).days + 1):
            day = start + timedelta(days=step)
            samples = []
            for hour in HOURS:
                got = field(day, hour)
                if got is not None:
                    samples.append(got[0])
                    transform, width, height = got[1], got[2], got[3]
            if not samples:
                continue
            daily = np.minimum.reduce(samples)
            lat = np.arange(height) * transform.e + transform.f
            lon = np.arange(width) * transform.a + transform.c
            rows = (lat >= south) & (lat <= north)
            columns = (lon >= west) & (lon <= east)
            days.append(daily[np.ix_(np.flatnonzero(rows), np.flatnonzero(columns))])
            print(f"  {year}: {day} ({len(samples)} 个时次)")
        if not days:
            continue
        stack = np.stack(days)                       # (day, lat, lon)
        above = stack > 0.0                          # daily minimum above freezing
        # Longest run of consecutive days, per grid cell.
        runs = np.zeros(above.shape[1:], dtype=int)
        current = np.zeros_like(runs)
        for day in range(above.shape[0]):
            current = np.where(above[day], current + 1, 0)
            runs = np.maximum(runs, current)
        cell_area = abs(transform.a * transform.e) * 111.0 * 111.0 * np.cos(np.deg2rad(32.0))
        np.save(f"/tmp/runs-{year}.npy", runs)
        results[year] = {
            "window": [str(start), str(end)],
            "days": len(days),
            "cells": int(runs.size),
            "never_below_freezing_10d": int((runs >= 10).sum()),
            "any_above_freezing": int((runs >= 1).sum()),
            "area_10d_km2": float((runs >= 10).sum() * cell_area),
            "median_run": float(np.median(runs)),
            "max_run": int(runs.max()),
        }
        row = results[year]
        print(f"  → {year}: 连续 ≥10 天日最低 >0 °C 的格点 {row['never_below_freezing_10d']:,} / {row['cells']:,} "
              f"（约 {row['area_10d_km2'] / 1000:,.0f} 千 km²），最长连续 {row['max_run']} 天")

    Path(out).write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"\n写入 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
