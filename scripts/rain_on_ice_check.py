#!/usr/bin/env python3
"""Does rain-on-ice discriminate, where the positive-degree-day trigger did not?

The third problem card asked whether the atmospheric data can serve glacier
collapse, and its retrospective found the trigger the paper names -- daily
minimum temperature above freezing for ten consecutive days -- to be climate
normal there: 91 percent of the box, and still two thirds of the cells above
5000 m, in all three years.  A trigger that fires everywhere discriminates
nothing.  The card's remaining candidate is rain-on-ice: liquid water reaching
the ice, which needs precipitation and a temperature above freezing together.

Prediction, stated before the run: if rain-on-ice is the discriminating term,
then in 2026-08-12..08-26 the *liquid* precipitation reaching high terrain should
stand out against 2024 and 2025.  Falsified if 2026 sits inside the year-to-year
range of the other two at the elevations glaciers occupy.

Construction.  For every six-hour window (four cycles a day) and every 0.25 degree
cell:

    APCP      precipitation accumulated over the window, mm
    T         the mean of the 2 m temperature at the window's two ends, degC
    rain      APCP where T > 0, else 0
    solid     APCP where T <= 0, else 0

and the cells are binned by the model's own surface geopotential height, so the
comparison is against the terrain the model thinks it has rather than against a
DEM that would be a second, unrelated error.

What this does NOT do: attribute the year-to-year differences to anything.  The
same run is used for all three years and the 2 m temperature over this terrain
carries the representativeness error measured elsewhere in this repository (a
4.38 K standard deviation in the plateau box), but a comparison between years is
robust to a bias that does not change between them -- which is the same argument
that made the positive-degree-day result decisive.
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

UA = {"User-Agent": "xue-study/1.0 (+rain-on-ice)"}
BUCKET = "https://noaa-gfs-bdp-pds.s3.amazonaws.com"
BOX = {"lat": (25.0, 40.0), "lon": (70.0, 105.0)}
TERRAIN_BANDS = [(None, 3000, "<3000 m"), (3000, 4000, "3000-4000 m"),
                 (4000, 5000, "4000-5000 m"), (5000, 10 ** 9, ">=5000 m")]


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


def index(cycle: str, hour: str) -> list[str]:
    url = f"{BUCKET}/gfs.{cycle}/{hour}/atmos/gfs.t{hour}z.pgrb2.0p25.f006.idx"
    return fetch(url).decode().splitlines()


def record_span(lines: list[str], pattern: str) -> tuple[int, int]:
    offsets = sorted(int(line.split(":")[1]) for line in lines if line.strip())
    for line in lines:
        if pattern in line:
            start = int(line.split(":")[1])
            following = [o for o in offsets if o > start]
            return start, (following[0] - 1 if following else start + 2_000_000)
    raise KeyError(pattern)


def read_field(cycle: str, hour: str, pattern: str, lines: list[str],
               temperature: bool = False) -> np.ndarray:
    base = f"{BUCKET}/gfs.{cycle}/{hour}/atmos/gfs.t{hour}z.pgrb2.0p25.f006"
    start, end = record_span(lines, pattern)
    blob = fetch(base, (start, end))
    path = f"/tmp/_gfs_{cycle}_{hour}_{abs(hash(pattern)) % 10 ** 8}.grib2"
    with open(path, "wb") as handle:
        handle.write(blob)
    import rasterio
    with rasterio.open(path) as source:
        data = source.read(1).astype(np.float64)
        unit = (source.tags(1).get("GRIB_UNIT") or "").strip()
    # GDAL's GRIB driver hands back temperature already in Celsius and says so in
    # GRIB_UNIT.  Subtracting 273.15 on top of that turns the whole field below
    # freezing and silently makes every precipitation event "solid", which is what
    # this check did on its first run.  Convert only when the unit says Kelvin.
    if temperature:
        if unit in ("[K]", "K"):
            data = data - 273.15
        elif unit not in ("[C]", "C", ""):
            raise RuntimeError(f"unhandled temperature unit {unit!r}")
    return data


def cell_mask(transform, height, width):
    """Latitude/longitude of every cell centre, and the analysis box."""
    rows = np.arange(height)
    cols = np.arange(width)
    lon = transform.c + transform.a * (cols + 0.5)
    lat = transform.f + transform.e * (rows + 0.5)
    lon2d, lat2d = np.meshgrid(lon, lat)
    inside = ((lat2d >= BOX["lat"][0]) & (lat2d <= BOX["lat"][1])
              & (lon2d >= BOX["lon"][0]) & (lon2d <= BOX["lon"][1]))
    return inside


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", type=int, nargs="+", default=[2024, 2025, 2026])
    ap.add_argument("--start", default="0812")
    ap.add_argument("--days", type=int, default=15)
    ap.add_argument("--hours", nargs="+", default=["00", "06", "12", "18"])
    ap.add_argument("--json", metavar="PATH")
    args = ap.parse_args()

    cycles = []
    for year in args.years:
        first = dt.datetime.strptime(f"{year}{args.start}", "%Y%m%d")
        for day in range(args.days):
            stamp = (first + dt.timedelta(days=day)).strftime("%Y%m%d")
            for hour in args.hours:
                cycles.append((year, stamp, hour))
    print(f"{len(cycles)} cycles over {len(args.years)} years "
          f"({args.days} days x {len(args.hours)} a day)")

    # ---- terrain, once -----------------------------------------------------
    reference = index(cycles[0][1], cycles[0][2])
    terrain_lines = reference
    terrain = read_field(cycles[0][1], cycles[0][2], ":HGT:surface:", terrain_lines)
    import rasterio
    path = f"/tmp/_gfs_{cycles[0][1]}_{cycles[0][2]}_{abs(hash(':HGT:surface:')) % 10 ** 8}.grib2"
    with rasterio.open(path) as source:
        inside = cell_mask(source.transform, source.height, source.width)
    print(f"grid {terrain.shape[1]}x{terrain.shape[0]}, {int(inside.sum())} cells in "
          f"{BOX['lat']}N x {BOX['lon']}E; terrain "
          f"{np.nanmin(terrain[inside]):.0f}..{np.nanmax(terrain[inside]):.0f} m")

    # The phase threshold is the delicate part: it is applied where the model's
    # temperature is least reliable.  So several thresholds are accumulated in
    # one pass rather than re-run, and the reading has to survive all of them.
    thresholds = (0.0, 1.0, 2.0)
    totals = {year: {t: {"rain": np.zeros_like(terrain), "solid": np.zeros_like(terrain)}
                     for t in thresholds} for year in args.years}
    windows = {year: 0 for year in args.years}
    # Per-day series, so the window total can be read against the shape of the
    # window itself: an excess spread evenly over fifteen days and an excess
    # concentrated in the three days before the event are different claims, and
    # a single total cannot tell them apart.
    daily: dict = {}

    def one(cycle):
        year, stamp, hour = cycle
        try:
            lines = index(stamp, hour)
            t2 = read_field(stamp, hour, ":TMP:2 m above ground:6 hour fcst:", lines,
                            temperature=True)
            apcp = read_field(stamp, hour, ":APCP:surface:0-6 hour acc fcst:", lines)
            return (year, stamp), t2, apcp, None
        except Exception as error:  # noqa: BLE001
            return (year, stamp), None, None, f"{stamp} {hour}Z: {type(error).__name__}"

    done = 0
    failures = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        for (year, stamp), t2, apcp, error in pool.map(one, cycles):
            done += 1
            if error:
                failures.append(error)
                continue
            for threshold in thresholds:
                rain = np.where(t2 > threshold, apcp, 0.0)
                totals[year][threshold]["rain"] += rain
                totals[year][threshold]["solid"] += np.where(t2 <= threshold, apcp, 0.0)
                if threshold == 0.0:
                    # key on the month-day, so the same day of the window
                    # lines up across years instead of each year forming its own row
                    key = (year, stamp[4:])
                    daily[key] = daily.get(key, np.zeros_like(terrain)) + rain
            windows[year] += 1
            if done % 20 == 0:
                print(f"  {done}/{len(cycles)} cycles", flush=True)

    print(f"\nfailures: {len(failures)}")
    for line in failures[:5]:
        print(f"  {line}")

    out: dict = {}
    for threshold in thresholds:
        print(f"\n--- liquid defined as 2 m temperature above {threshold:.0f} degC ---")
        print(f"{'terrain band':<16}{'year':<7}{'cells':>7}{'windows':>9}"
              f"{'rain mm':>10}{'solid mm':>10}{'ratio':>9}")
        for low, high, name in TERRAIN_BANDS:
            band = (inside & (terrain >= (low if low is not None else -10 ** 9))
                    & (terrain < high))
            if not band.any():
                continue
            for year in args.years:
                if not windows[year]:
                    continue
                entry = totals[year][threshold]
                rain = float(np.nanmean(entry["rain"][band]))
                solid = float(np.nanmean(entry["solid"][band]))
                ratio = rain / solid if solid > 0 else float("inf")
                print(f"{name:<16}{year:<7}{int(band.sum()):>7}{windows[year]:>9}"
                      f"{rain:>10.1f}{solid:>10.1f}{ratio:>9.2f}")
                out.setdefault(f"{name}@{threshold:.0f}C", {})[year] = {
                    "rain_mean_mm": rain, "solid_mean_mm": solid, "ratio": ratio}
            print()

    print("\n--- daily liquid precipitation at >=5000 m, mm per cell per day ---")
    band = inside & (terrain >= 5000)
    days = sorted({day for (_year, day) in daily})
    print(f"{'day':<10}" + "".join(f"{y:>9}" for y in args.years) + f"{'2026/mean(other)':>18}")
    ratios = []
    for stamp in days:
        row = []
        for year in args.years:
            series = daily.get((year, stamp))
            row.append(float(np.nanmean(series[band])) if series is not None else float("nan"))
        others = [v for v in row if np.isfinite(v)][:-1]
        ratio = row[-1] / np.mean(others) if others and np.mean(others) > 0 else float("nan")
        if np.isfinite(ratio):
            ratios.append(ratio)
        print(f"{stamp:<10}" + "".join(f"{v:>9.2f}" for v in row) + f"{ratio:>18.2f}")
    if ratios:
        print(f"\n  median 2026-to-others ratio across the {len(ratios)} days: "
              f"{np.median(ratios):.2f}")
        top = sorted(range(len(days)), key=lambda i: -ratios[i])[:5] if len(ratios) == len(days) else []
        if top:
            print(f"  the five days where 2026 stands out most: "
                  f"{[days[i] for i in top]}")
        print(f"  2026 is the wettest of the three on "
              f"{sum(1 for r in ratios if r > 1)}/{len(ratios)} days")
    out["daily_ratio_median"] = float(np.median(ratios)) if ratios else None

    print("\nThe question the third problem card left open: does the liquid fraction")
    print("separate 2026 from the other two years where the positive-degree-day")
    print("trigger did not?  Read the table above by band.")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump({"cycles": len(cycles), "failures": failures, "bands": out},
                      handle, indent=2, ensure_ascii=False, default=str)
            handle.write("\n")
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
