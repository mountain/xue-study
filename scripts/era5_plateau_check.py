#!/usr/bin/env python3
"""What ERA5 does at 850 hPa over the Tibetan plateau, read from the drive.

The theta-e claim in this repository says the published 850 hPa field over the
plateau is an underground extrapolation, and that xue's version of it is clamped
against a codebook ceiling.  Everything that claim rests on came from one
pipeline: GFS fields, through the encoder, read back out.  It has never been
asked whether the *terrain* does this to any model, or whether it is something
about that pipeline.

ERA5 answers that, because it is a different model with its own orography, its
own levels and no codebook in common.  If 850 hPa over a four-kilometre plateau
produces extreme equivalent potential temperature in ERA5 too, then the
mechanism is the terrain and the pipeline only decides how it is stored.  If
ERA5 does something visibly different, the claim needs narrowing.

Read in place.  The bytes stay on the drive: ERA5 is a Copernicus product, free
to use but not public domain, and this repository admits public domain only.

Method.  Temperature and relative humidity at the 850 hPa level, for a sample of
days in January 2024, on the plateau box and on a tropical warm-pool box as the
control the claim already uses.  Equivalent potential temperature is computed by
the same Bolton implementation the claim was checked with, imported rather than
rewritten so the two cannot drift.
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

ROOT = "/Volumes/Newsmy"
BOXES = {
    "plateau (80-92E, 26-32N)": {"lat": (26.0, 32.0), "lon": (80.0, 92.0)},
    "warm pool (120-180E, 15S-15N)": {"lat": (-15.0, 15.0), "lon": (120.0, 180.0)},
}
LEVEL_HPA = 850


def band_for(dataset, level: int, time_index: int) -> int:
    """Band number for one level at one time, from the file's own metadata."""
    times = []
    for band in range(1, dataset.count + 1):
        tag = dataset.tags(band)
        stamp = tag.get("NETCDF_DIM_time")
        value = tag.get("NETCDF_DIM_level")
        if value is None:
            continue
        if stamp not in times:
            times.append(stamp)
        if int(value) == level and times.index(stamp) == time_index:
            return band
    raise KeyError(f"level {level} hPa at time index {time_index} not in this file")


def read_level(path: str, level: int, time_index: int):
    import rasterio
    warnings.filterwarnings("ignore")
    with rasterio.open(path) as dataset:
        band = band_for(dataset, level, time_index)
        tags = dataset.tags(band)
        raw = dataset.read(band).astype(np.float64)
        scale = float(tags["scale_factor"])
        offset = float(tags["add_offset"])
        fill = float(tags.get("_FillValue", -32767))
        transform = dataset.transform
        height, width = dataset.height, dataset.width
    physical = raw * scale + offset
    physical[raw == fill] = np.nan
    lon = transform.c + transform.a * (np.arange(width) + 0.5)
    lat = transform.f + transform.e * (np.arange(height) + 0.5)
    return physical, lat, lon, tags


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, nargs="+", default=[1, 15, 31])
    ap.add_argument("--time-index", type=int, default=12, help="hour index (default 12Z)")
    ap.add_argument("--json", metavar="PATH")
    args = ap.parse_args()

    if not os.path.isdir(ROOT):
        print(f"REFUSED the drive is not mounted at {ROOT}")
        return 1

    out: dict = {"level_hpa": LEVEL_HPA, "days": args.days,
                 "time_index": args.time_index, "boxes": {}}
    print(f"ERA5, {LEVEL_HPA} hPa, hour index {args.time_index}, January 2024")
    print(f"{'day':<6}{'box':<32}{'n':>7}{'theta-e p50':>13}{'p90':>8}{'max':>8}"
          f"{'clamped-like':>14}")

    for day in args.days:
        stamp = f"202401{day:02d}"
        t_path = f"{ROOT}/多层变量/temperature/era5.temperature.{stamp}.nc"
        r_path = f"{ROOT}/多层变量/relative_humidity/era5.relative_humidity.{stamp}.nc"
        if not (os.path.exists(t_path) and os.path.exists(r_path)):
            print(f"  {stamp}: files absent")
            continue
        temperature, lat, lon, _ = read_level(t_path, LEVEL_HPA, args.time_index)
        humidity, _, _, _ = read_level(r_path, LEVEL_HPA, args.time_index)
        lat2d, lon2d = np.meshgrid(lat, lon, indexing="ij")

        for name, box in BOXES.items():
            inside = ((lat2d >= box["lat"][0]) & (lat2d <= box["lat"][1])
                      & (lon2d >= box["lon"][0]) & (lon2d <= box["lon"][1]))
            t = temperature[inside] - 273.15          # ERA5 gives kelvin
            rh = humidity[inside]
            good = np.isfinite(t) & np.isfinite(rh)
            t, rh = t[good], rh[good]
            if t.size == 0:
                continue
            # specific humidity from RH at this level, the same path thetae_check uses
            vapour = (rh / 100.0) * 6.112 * np.exp(17.67 * t / (t + 243.5))
            q = 0.622 * vapour / (LEVEL_HPA - 0.378 * vapour)
            theta_e = bolton_theta_e(t, q, LEVEL_HPA)
            # a ceiling does not exist here, so "clamped-like" counts how much of
            # the box sits within half a kelvin of the day's own maximum
            top = np.nanmax(theta_e)
            near_top = float((theta_e > top - 0.5).mean() * 100)
            print(f"{stamp[4:]:<6}{name:<32}{t.size:>7}"
                  f"{np.median(theta_e):>13.2f}{np.percentile(theta_e, 90):>8.2f}"
                  f"{top:>8.2f}{near_top:>13.1f}%")
            out["boxes"].setdefault(name, []).append({
                "day": stamp, "n": int(t.size),
                "theta_e_p50": float(np.median(theta_e)),
                "theta_e_p90": float(np.percentile(theta_e, 90)),
                "theta_e_max": float(top), "within_half_k_of_max_pct": near_top,
            })

    print("\nWHAT THIS SHOWS: whether a second, independent model also produces")
    print("extreme equivalent potential temperature at a level that lies below the")
    print("ground over this terrain.  WHAT IT DOES NOT: an error.  A level below the")
    print("ground has no measurement to be wrong about, in ERA5 any more than in GFS.")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(out, handle, indent=2, ensure_ascii=False, default=str)
            handle.write("\n")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
