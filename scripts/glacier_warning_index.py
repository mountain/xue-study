#!/usr/bin/env python3
"""A fused high-altitude liquid-water index, and what its ranking can and cannot say.

The third problem card found the paper's own trigger -- ten days with the daily
minimum above freezing -- to be climate normal over 91 percent of High Mountain
Asia in every year tested, so it discriminates nothing.  It then found the
liquid fraction at high elevation to separate 2026 from two earlier years.  This
script fuses four model fields into one index, extends the baseline to every year
the archive serves, and reports where the event year sits -- and, just as
importantly, what one event in six years cannot establish.

Fused quantities, all from the same six-hour window of the same run:

    APCP        precipitation accumulated over the window, mm
    TMIN, TMAX  the window's 2 m temperature extremes, degC
    WEASD       water equivalent of the snow on the ground at the window's end, mm

Index, defined before the run:

    RAIN-ON-ICE   APCP over windows whose *minimum* 2 m temperature stayed above
                  freezing.  Using the window minimum rather than an endpoint or
                  a mean is the conservative choice: it counts only windows in
                  which no part of the precipitation could have fallen as snow.
    SNOW-COVERED  the same, restricted to cells carrying WEASD > 0, so the water
                  lands on a snowpack rather than on bare ground.

Both are reported per elevation band from the model's own HGT:surface, over every
year the NOAA GFS archive serves.  The event year's rank among those years is the
"how unusual" statement; nothing here predicts anything.

What this does NOT establish, and the report repeats it: the baseline is six
years, there is one event, the fields are analyses rather than observations, and
a rank is not a skill score.  A rank of one in six is not a warning system.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np

UA = {"User-Agent": "xue-study/1.0 (+glacier-warning-index)"}
BUCKET = "https://noaa-gfs-bdp-pds.s3.amazonaws.com"
BOX = {"lat": (25.0, 40.0), "lon": (70.0, 105.0)}
BANDS = [(None, 3000, "<3000 m"), (3000, 4000, "3000-4000 m"),
         (4000, 5000, "4000-5000 m"), (5000, 10 ** 9, ">=5000 m")]
FIELDS = {
    "apcp": (":APCP:surface:0-6 hour acc fcst:", False),
    "tmin": (":TMIN:2 m above ground:0-6 hour min fcst:", True),
    "tmax": (":TMAX:2 m above ground:0-6 hour max fcst:", True),
    "weasd": (":WEASD:surface:6 hour fcst:", False),
}


def fetch(url: str, byte_range=None, attempts: int = 4, timeout: int = 240) -> bytes:
    headers = dict(UA)
    if byte_range:
        headers["Range"] = f"bytes={byte_range[0]}-{byte_range[1]}"
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers),
                                        timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code == 404:
                raise
            last = error
        except Exception as error:  # noqa: BLE001
            last = error
        time.sleep(2 + 2 * attempt)
    raise RuntimeError(f"failed: {url}") from last


def cycle_index(stamp: str, hour: str) -> list[str]:
    url = f"{BUCKET}/gfs.{stamp}/{hour}/atmos/gfs.t{hour}z.pgrb2.0p25.f006.idx"
    return fetch(url).decode().splitlines()


def span(lines: list[str], pattern: str) -> tuple[int, int]:
    offsets = sorted(int(line.split(":")[1]) for line in lines if line.strip())
    for line in lines:
        if pattern in line:
            start = int(line.split(":")[1])
            following = [o for o in offsets if o > start]
            return start, (following[0] - 1 if following else start + 2_000_000)
    raise KeyError(pattern)


def read(stamp: str, hour: str, key: str, lines: list[str]) -> tuple[np.ndarray, tuple]:
    pattern, is_temperature = FIELDS[key]
    base = f"{BUCKET}/gfs.{stamp}/{hour}/atmos/gfs.t{hour}z.pgrb2.0p25.f006"
    start, end = span(lines, pattern)
    path = f"/tmp/_gw_{stamp}_{hour}_{key}.grib2"
    with open(path, "wb") as handle:
        handle.write(fetch(base, (start, end)))
    import rasterio
    with rasterio.open(path) as source:
        data = source.read(1).astype(np.float64)
        unit = (source.tags(1).get("GRIB_UNIT") or "").strip()
        transform, height, width = source.transform, source.height, source.width
    if is_temperature and unit in ("[K]", "K"):
        data = data - 273.15
    elif is_temperature and unit not in ("[C]", "C", ""):
        raise RuntimeError(f"unhandled temperature unit {unit!r}")
    return data, (transform, height, width)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", type=int, nargs="+",
                    default=[2021, 2022, 2023, 2024, 2025, 2026])
    ap.add_argument("--start", default="0812")
    ap.add_argument("--days", type=int, default=15)
    ap.add_argument("--hours", nargs="+", default=["00", "06", "12", "18"])
    ap.add_argument("--threshold-mm", type=float, default=1.0,
                    help="a window counts only if its precipitation reaches this")
    ap.add_argument("--json", metavar="PATH")
    args = ap.parse_args()

    cycles = []
    for year in args.years:
        first = dt.datetime.strptime(f"{year}{args.start}", "%Y%m%d")
        for day in range(args.days):
            stamp = (first + dt.timedelta(days=day)).strftime("%Y%m%d")
            for hour in args.hours:
                cycles.append((year, stamp[4:], stamp, hour))
    print(f"{len(cycles)} cycles across {len(args.years)} years "
          f"({args.days} days x {len(args.hours)} a day)", flush=True)

    # The archive does not start at a year boundary -- 2021 begins in April -- so
    # the reference window is taken from the first year that actually serves it
    # rather than from the first year asked for.  Assuming otherwise killed the
    # whole run on a 404 before any cycle was attempted.
    first_stamp = None
    for year in args.years:
        candidate = dt.datetime.strptime(f"{year}{args.start}", "%Y%m%d").strftime("%Y%m%d")
        try:
            cycle_index(candidate, args.hours[0])
            first_stamp = candidate
            break
        except Exception:  # noqa: BLE001 - a missing window is expected at the boundary
            print(f"  {candidate} not served; trying the next year", flush=True)
    if first_stamp is None:
        print("REFUSED no requested year serves this window")
        return 1
    terrain, grid = read(first_stamp, args.hours[0], "apcp", cycle_index(first_stamp, args.hours[0]))
    import rasterio
    with rasterio.open(f"/tmp/_gw_{first_stamp}_{args.hours[0]}_apcp.grib2") as source:
        transform, height, width = source.transform, source.height, source.width
    # HGT:surface for the same grid, once.
    lines = cycle_index(first_stamp, args.hours[0])
    start, end = span(lines, ":HGT:surface:")
    with open("/tmp/_gw_orog.grib2", "wb") as handle:
        handle.write(fetch(f"{BUCKET}/gfs.{first_stamp}/{args.hours[0]}/atmos/"
                           f"gfs.t{args.hours[0]}z.pgrb2.0p25.f006", (start, end)))
    with rasterio.open("/tmp/_gw_orog.grib2") as source:
        orography = source.read(1).astype(np.float64)
    cols = np.arange(width); rows = np.arange(height)
    lon = transform.c + transform.a * (cols + 0.5)
    lat = transform.f + transform.e * (rows + 0.5)
    lon2d, lat2d = np.meshgrid(lon, lat)
    inside = ((lat2d >= BOX["lat"][0]) & (lat2d <= BOX["lat"][1])
              & (lon2d >= BOX["lon"][0]) & (lon2d <= BOX["lon"][1]))
    print(f"grid {width}x{height}, {int(inside.sum())} cells in the box; "
          f"terrain {np.nanmin(orography[inside]):.0f}..{np.nanmax(orography[inside]):.0f} m",
          flush=True)

    totals = {year: {"rain": np.zeros_like(orography), "snow": np.zeros_like(orography),
                     "windows": 0, "rain_windows": 0} for year in args.years}
    daily: dict = {}

    def one(cycle):
        year, day, stamp, hour = cycle
        try:
            lines = cycle_index(stamp, hour)
            apcp, _ = read(stamp, hour, "apcp", lines)
            tmin, _ = read(stamp, hour, "tmin", lines)
            weasd, _ = read(stamp, hour, "weasd", lines)
            return (year, day), apcp, tmin, weasd, None
        except Exception as error:  # noqa: BLE001
            return (year, day), None, None, None, f"{stamp} {hour}Z: {type(error).__name__}"

    done, failures = 0, []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for (year, day), apcp, tmin, weasd, error in pool.map(one, cycles):
            done += 1
            if error:
                failures.append(error)
                continue
            wet = apcp >= args.threshold_mm
            liquid = wet & (tmin > 0.0) & (weasd > 0.0)
            contribution = np.where(liquid, apcp, 0.0)
            totals[year]["rain"] += contribution
            totals[year]["snow"] += np.where(weasd > 0.0, apcp, 0.0)
            totals[year]["windows"] += 1
            totals[year]["rain_windows"] += int(liquid.sum())
            key = (year, day)
            daily[key] = daily.get(key, 0.0) + float(np.nansum(contribution[inside & (orography >= 4000)]))
            if done % 30 == 0:
                print(f"  {done}/{len(cycles)}", flush=True)

    print(f"\nfailures: {len(failures)}")
    for line in failures[:5]:
        print(f"  {line}")

    print(f"\nliquid precipitation onto snowpack above 4000 m "
          f"(APCP >= {args.threshold_mm} mm, window TMIN > 0, WEASD > 0), mm per cell")
    print(f"{'terrain band':<16}" + "".join(f"{y:>10}" for y in args.years)
          + f"{'rank of '+str(args.years[-1]):>16}")
    ranked: dict = {}
    for low, high, name in BANDS:
        if high < 4000:
            continue
        band = inside & (orography >= low) & (orography < high)
        values = {y: float(np.nanmean(totals[y]["rain"][band])) for y in args.years
                  if totals[y]["windows"]}
        if not values:
            continue
        ordered = sorted(values.items(), key=lambda kv: -kv[1])
        rank = [y for y, _ in ordered].index(args.years[-1]) + 1
        print(f"{name:<16}" + "".join(f"{values[y]:>10.1f}" for y in args.years)
              + f"{rank:>16}")
        ranked[name] = {"values": values, "rank": rank, "of": len(ordered)}
    print()
    for low, high, name in BANDS:
        if high >= 4000:
            continue
        band = inside & (orography >= (low if low is not None else -10 ** 9)) & (orography < high)
        values = {y: float(np.nanmean(totals[y]["rain"][band])) for y in args.years
                  if totals[y]["windows"]}
        if values:
            ordered = sorted(values.items(), key=lambda kv: -kv[1])
            rank = [y for y, _ in ordered].index(args.years[-1]) + 1
            print(f"{name:<16}" + "".join(f"{values[y]:>10.1f}" for y in args.years)
                  + f"{rank:>16}")

    print(f"\ndaily liquid water above 4000 m, mm summed over the box:")
    days = sorted({d for (_y, d) in daily})
    print(f"{'day':<8}" + "".join(f"{y:>10}" for y in args.years))
    for day in days:
        row = [daily.get((y, day)) for y in args.years]
        print(f"{day:<8}" + "".join(f"{(v if v is not None else float('nan')):>10.1f}"
                                    for v in row))

    print("\nWHAT THIS IS: a rank of the event year inside the years the archive")
    print("serves.  WHAT IT IS NOT: an accuracy.  Six years, one event, analyses")
    print("rather than observations, and no false-alarm rate that six years can")
    print("support.  A rank of one in six is not a warning system.")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump({"years": args.years, "cycles": len(cycles),
                       "failures": failures, "ranked": ranked,
                       "daily": {f"{y}-{d}": v for (y, d), v in daily.items()}},
                      handle, indent=2, ensure_ascii=False, default=str)
            handle.write("\n")
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
