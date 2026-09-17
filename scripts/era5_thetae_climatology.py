#!/usr/bin/env python3
"""Sixty-three Septembers of plateau theta-e, to see whether GFS's values exist there.

The warm-season comparison found the 850 hPa equivalent potential temperature
over the Tibetan plateau to differ by 36 to 40 K between ERA5 and GFS on the same
day, with identical terrain (surface pressure medians 582.9 and 582.6 hPa) and the
same depth of 850 hPa below the ground (267.1 and 267.4 hPa).  That localises the
clamp to the GFS below-ground extrapolation rather than to the terrain.

One day is not a distribution, so this asks the next question: in the years ERA5
covers, does the plateau's September 850 hPa theta-e ever approach the values GFS
produces?  If it never comes close, then GFS is not merely high but outside the
range a second reanalysis reaches over six decades.

Cheap by construction.  ARCO also serves a coarsened 1.5 degree, six-hourly
variant with eight time steps per chunk, so one chunk is about 1.2 MB instead of
the 84.77 MB of the full-resolution store -- roughly seventy times cheaper -- and
it carries 13 pressure levels including 850.  The price is resolution: the plateau
box is 32 cells instead of 1,225, which is enough for a regional distribution and
not enough for a spatial pattern.  The coarse store ends in 2021, so recent years
are read from the fine store separately and the seam is stated rather than hidden.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import warnings

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bolton import bolton_theta_e  # noqa: E402

COARSE = ("https://storage.googleapis.com/gcp-public-data-arco-era5/ar/"
          "1959-2022-6h-240x121_equiangular_with_poles_conservative.zarr")
LEVEL = 850
BOXES = {
    "plateau (80-92E, 26-32N)": (26.0, 32.0, 80.0, 92.0),
    "warm pool (120-180E, 15S-15N)": (-15.0, 15.0, 120.0, 180.0),
}
GFS_CEILING_K = 357.0
# the values the same-day comparison produced, for reference lines on the output
GFS_PLATEAU = (366.22, 371.29)
ERA5_PLATEAU = (329.62, 331.29)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--first-year", type=int, default=1959)
    ap.add_argument("--last-year", type=int, default=2021)
    ap.add_argument("--month", type=int, default=9)
    ap.add_argument("--json", metavar="PATH")
    args = ap.parse_args()

    import xarray as xr
    warnings.filterwarnings("ignore")
    print(f"opening the coarse ARCO store ({args.first_year}-{args.last_year} available)")
    dataset = xr.open_zarr(COARSE, consolidated=True)
    levels = list(np.asarray(dataset["level"].values))
    if LEVEL not in levels:
        print(f"REFUSED {LEVEL} hPa is not among the coarse store's levels {levels}")
        return 1
    latitude = np.asarray(dataset["latitude"].values)
    longitude = np.asarray(dataset["longitude"].values)
    times = np.asarray(dataset["time"].values)
    # The coarse store orders its horizontal axes longitude-then-latitude while
    # the full-resolution store orders them latitude-then-longitude.  Rather than
    # assume either, the order is read off the variable after dropping time and
    # level and normalised here; the first version assumed and hit an IndexError
    # indexing a 121-long axis with a 240-long mask.  Computing the order from the
    # full dim tuple would also be wrong, because dropping level shifts it.
    dims = [d for d in dataset["temperature"].dims if d not in ("time", "level")]
    order = (dims.index("latitude"), dims.index("longitude"))
    print(f"  horizontal dims {dims}; latitude is axis {order[0]}, longitude axis {order[1]}")
    masks = {}
    for name, (south, north, west, east) in BOXES.items():
        masks[name] = ((latitude[:, None] >= south) & (latitude[:, None] <= north)
                       & (longitude[None, :] >= west) & (longitude[None, :] <= east))
        print(f"  {name}: {int(masks[name].sum())} cells on the 1.5 degree grid")

    rows = []
    for year in range(args.first_year, args.last_year + 1):
        start = np.datetime64(f"{year}-{args.month:02d}-01T00")
        end = start + np.timedelta64(31, "D")
        inside = np.flatnonzero((times >= start) & (times < end))
        if inside.size == 0:
            continue
        window = dataset.isel(time=slice(int(inside[0]), int(inside[-1]) + 1))
        temperature = np.asarray(window["temperature"].sel(level=LEVEL).values, dtype=np.float64)
        humidity = np.asarray(window["specific_humidity"].sel(level=LEVEL).values,
                              dtype=np.float64)
        # (time, latitude, longitude) regardless of how the store ordered them.
        # `order` indexes the horizontal dims; in the value array time takes axis
        # 0, so the horizontal axes sit at order[i] + 1.  Using order directly
        # produced transpose(0, 1, 0) and "repeated axis in transpose".
        permutation = (0, order[0] + 1, order[1] + 1)
        if order != (0, 1):
            temperature = temperature.transpose(*permutation)
            humidity = humidity.transpose(*permutation)
        assert temperature.shape[1:] == (latitude.size, longitude.size), temperature.shape
        entry = {"year": year, "hours": int(temperature.shape[0])}
        for name, mask in masks.items():
            t = temperature[:, mask] - 273.15
            q = humidity[:, mask]
            good = np.isfinite(t) & np.isfinite(q)
            theta = bolton_theta_e(np.where(good, t, 0.0), np.where(good, q, 1e-9), LEVEL)
            theta = np.where(good, theta, np.nan)
            per_hour = np.nanmean(theta, axis=1)
            entry[name] = {
                "month_mean": float(np.nanmean(per_hour)),
                "month_max": float(np.nanmax(theta)),
                "hour_p90": float(np.nanpercentile(per_hour, 90)),
                "frac_within_1K_of_gfs_ceiling": float(
                    np.nanmean(theta >= GFS_CEILING_K - 1.0) * 100),
            }
        rows.append(entry)
        if year % 5 == 0 or year == args.last_year:
            plateau = entry["plateau (80-92E, 26-32N)"]
            warm = entry["warm pool (120-180E, 15S-15N)"]
            print(f"  {year}  plateau mean {plateau['month_mean']:7.2f} max {plateau['month_max']:7.2f}"
                  f"   warm pool mean {warm['month_mean']:7.2f}"
                  f"   within 1 K of 357: {plateau['frac_within_1K_of_gfs_ceiling']:5.2f}%",
                  flush=True)
    dataset.close()

    if not rows:
        print("no years read")
        return 1
    plateau_mean = np.array([r["plateau (80-92E, 26-32N)"]["month_mean"] for r in rows])
    plateau_max = np.array([r["plateau (80-92E, 26-32N)"]["month_max"] for r in rows])
    warm_mean = np.array([r["warm pool (120-180E, 15S-15N)"]["month_mean"] for r in rows])
    near_ceiling = np.array([r["plateau (80-92E, 26-32N)"]["frac_within_1K_of_gfs_ceiling"]
                             for r in rows])
    years = np.array([r["year"] for r in rows])

    print(f"\n{'':<34}{'min':>9}{'median':>9}{'max':>9}")
    for label, series in (("plateau, September mean K", plateau_mean),
                          ("plateau, single-cell September max K", plateau_max),
                          ("warm pool, September mean K", warm_mean),
                          ("plateau, % within 1 K of 357 K", near_ceiling)):
        print(f"{label:<34}{series.min():>9.2f}{np.median(series):>9.2f}{series.max():>9.2f}")

    print(f"\n{'question':<58}{'answer':>22}")
    print(f"{'years with a September plateau max above 350 K':<58}"
          f"{int((plateau_max > 350).sum()):>22}")
    print(f"{'years with a September plateau max above 357 K':<58}"
          f"{int((plateau_max > GFS_CEILING_K).sum()):>22}")
    print(f"{'years where the plateau mean exceeded the warm pool mean':<58}"
          f"{int((plateau_mean > warm_mean).sum())} of {len(rows):>18}")
    print(f"{'the GFS same-day plateau values, for reference':<58}"
          f"{GFS_PLATEAU[0]:.1f} and {GFS_PLATEAU[1]:.1f} K")
    print(f"{'the ERA5 same-day plateau values, for reference':<58}"
          f"{ERA5_PLATEAU[0]:.1f} and {ERA5_PLATEAU[1]:.1f} K")

    print("\nDECLARED BEFORE RUNNING: if GFS's plateau values are a property of the")
    print("terrain, ERA5's six decades should reach the same region; if they are a")
    print("property of GFS's below-ground extrapolation, they should not.")
    print("NOT ESTABLISHED: that these years are comparable to 2026 -- the coarse")
    print("store ends in 2021 and the fine store runs to 2026, and the two grids")
    print("differ by a factor of six in cell count, so the seam is a change of")
    print("instrument and not only of year.")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump({"level_hpa": LEVEL, "years": [int(y) for y in years], "rows": rows},
                      handle, indent=2, ensure_ascii=False, default=str)
            handle.write("\n")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
