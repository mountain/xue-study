#!/usr/bin/env python3
"""The theta-e clamp, tested against a second reanalysis in its own season.

The theta-e claim says the published 850 hPa field over the Tibetan plateau is an
underground extrapolation, and that xue's version of it is pinned against the
codebook ceiling: every frame tops out at exactly 357.00 K and 62 to 66 percent
of the plateau box sits at that ceiling, making the plateau look more extreme
than the tropical warm pool.

Everything behind that came from one pipeline, and the one check that could have
used a second model ran in January -- where no clamp appears in either model and
the comparison therefore tests nothing.  The clamp is a warm-season phenomenon,
as the claim itself notes (the plateau is a summer heat source), so the test has
to run in a warm season.

ARCO-ERA5 supplies it without credentials: a public Google Cloud bucket, Zarr,
1940 to 2026-09-11 with the near-real-time ERA5T extension, 37 pressure levels
including 850, hourly, and chunked one hour at a time so a read fetches only the
hours asked for.  No account, no bulk download.

Prediction, declared before the run: if the clamp is the terrain doing this to
any model, ERA5 in September over the same box reaches values of the same order
and the plateau again sits near the top of its own range.  If the clamp is
something about the GFS field or about how xue stores it, ERA5 does not, and the
claim's mechanism needs narrowing to the pipeline rather than the terrain.
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import os
import sys
import urllib.request
import warnings

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bolton import bolton_theta_e  # noqa: E402

ARCO = ("https://storage.googleapis.com/gcp-public-data-arco-era5/ar/"
        "full_37-1h-0p25deg-chunk-1.zarr-v3")
BUCKET = "https://noaa-gfs-bdp-pds.s3.amazonaws.com"
UA = {"User-Agent": "xue-study/1.0 (+era5-thetae-season)"}
LEVEL = 850
BOXES = {
    "plateau (80-92E, 26-32N)": (26.0, 32.0, 80.0, 92.0),
    "warm pool (120-180E, 15S-15N)": (-15.0, 15.0, 120.0, 180.0),
}
# the codebook ceiling the claim is about, read from the published metadata
GFS_CEILING_K = 357.0


def theta_e_from_specific(temperature_c, specific_humidity, pressure_hpa: float = LEVEL):
    """Bolton theta-e from temperature and specific humidity directly.

    ARCO carries `specific_humidity` at pressure levels -- the same quantity the
    GFS encoder reads as `spfh850` -- so the ERA5 side uses it as it stands.
    The GFS side has only the published `rh850`, so there it is converted back to
    specific humidity first.  The two sides therefore differ in one conversion,
    which is stated rather than hidden.
    """
    return bolton_theta_e(temperature_c, specific_humidity, pressure_hpa)


def specific_from_relative(temperature_c, humidity_percent, pressure_hpa: float = LEVEL):
    vapour = (humidity_percent / 100.0) * 6.112 * np.exp(
        17.67 * temperature_c / (temperature_c + 243.5))
    return 0.622 * vapour / (pressure_hpa - 0.378 * vapour)


def era5_box(moment: dt.datetime, box: tuple, cache: dict):
    """850 hPa temperature and relative humidity from ARCO, one hour."""
    import xarray as xr
    warnings.filterwarnings("ignore")
    key = moment.strftime("%Y%m%d%H")
    if key not in cache:
        dataset = xr.open_zarr(ARCO, consolidated=True)
        stamp = np.datetime64(moment.strftime("%Y-%m-%dT%H:00"))
        times = np.asarray(dataset["time"].values)
        index = int(np.argmin(np.abs(times - stamp)))
        print(f"    ARCO {times[index]}", flush=True)
        cache[key] = {
            "temperature": np.asarray(
                dataset["temperature"].isel(time=index, level=list(
                    np.asarray(dataset["level"].values)).index(LEVEL)).values,
                dtype=np.float64),
            "specific_humidity": np.asarray(
                dataset["specific_humidity"].isel(time=index, level=list(
                    np.asarray(dataset["level"].values)).index(LEVEL)).values,
                dtype=np.float64),
            "latitude": np.asarray(dataset["latitude"].values),
            "longitude": np.asarray(dataset["longitude"].values),
            "time": str(times[index]),
        }
        dataset.close()
    entry = cache[key]
    south, north, west, east = box
    lat, lon = entry["latitude"], entry["longitude"]
    mask = ((lat[:, None] >= south) & (lat[:, None] <= north)
            & (lon[None, :] >= west) & (lon[None, :] <= east))
    mask = np.broadcast_to(mask, entry["temperature"].shape)
    t = entry["temperature"][mask] - 273.15
    q = entry["specific_humidity"][mask]
    good = np.isfinite(t) & np.isfinite(q)
    return t[good], q[good], entry["time"]


def gfs_box(moment: dt.datetime, box: tuple):
    """850 hPa temperature and relative humidity from the GFS analysis."""
    import rasterio
    warnings.filterwarnings("ignore")
    stamp = moment.strftime("%Y%m%d")
    hour = moment.strftime("%H")
    base = f"{BUCKET}/gfs.{stamp}/{hour}/atmos/gfs.t{hour}z.pgrb2.0p25.f000"
    lines = urllib.request.urlopen(
        urllib.request.Request(base + ".idx", headers=UA), timeout=120).read().decode().splitlines()
    offsets = sorted(int(l.split(":")[1]) for l in lines if l.strip())

    def record(phrase):
        for line in lines:
            if phrase in line:
                start = int(line.split(":")[1])
                following = [o for o in offsets if o > start]
                raw = urllib.request.urlopen(urllib.request.Request(
                    base, headers={**UA, "Range": f"bytes={start}-{following[0] - 1}"}),
                    timeout=180).read()
                with rasterio.open(io.BytesIO(raw)) as source:
                    data = source.read(1).astype(np.float64)
                    unit = (source.tags(1).get("GRIB_UNIT") or "").strip()
                    transform = source.transform
                    height, width = source.height, source.width
                if unit in ("[K]", "K"):
                    data = data - 273.15
                return data, transform, height, width
        raise KeyError(phrase)

    t, transform, height, width = record(":TMP:850 mb:anl:")
    r, _, _, _ = record(":RH:850 mb:anl:")
    lon = transform.c + transform.a * (np.arange(width) + 0.5)
    lat = transform.f + transform.e * (np.arange(height) + 0.5)
    south, north, west, east = box
    mask = ((lat[:, None] >= south) & (lat[:, None] <= north)
            & (lon[None, :] >= west) & (lon[None, :] <= east))
    mask = np.broadcast_to(mask, t.shape)
    values = mask & np.isfinite(t) & np.isfinite(r)
    return t[values], r[values]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", default="2026-09-10")
    ap.add_argument("--hours", nargs="+", default=["00", "06", "12", "18"])
    ap.add_argument("--json", metavar="PATH")
    args = ap.parse_args()

    day = dt.datetime.fromisoformat(args.date)
    cache: dict = {}
    results: dict = {"date": args.date, "level_hpa": LEVEL,
                     "gfs_codebook_ceiling_k": GFS_CEILING_K, "rows": []}
    print(f"{args.date}, 850 hPa equivalent potential temperature, two reanalyses\n")
    print(f"{'hour':<7}{'source':<8}{'box':<32}{'n':>7}{'p50':>9}{'p90':>8}{'max':>8}"
          f"{'at ceiling':>12}")
    for hour in args.hours:
        moment = day.replace(hour=int(hour))
        for name, box in BOXES.items():
            try:
                t, r, stamp = era5_box(moment, box, cache)
                theta = theta_e_from_specific(t, r)
                near = float((theta >= GFS_CEILING_K - 1.0).mean() * 100)
                print(f"{hour}Z{'':<3}{'ERA5':<8}{name:<32}{theta.size:>7}"
                      f"{np.median(theta):>9.2f}{np.percentile(theta, 90):>8.2f}"
                      f"{theta.max():>8.2f}{near:>11.1f}%")
                results["rows"].append({"hour": hour, "source": "ERA5", "box": name,
                                        "n": int(theta.size),
                                        "p50": float(np.median(theta)),
                                        "p90": float(np.percentile(theta, 90)),
                                        "max": float(theta.max()),
                                        "within_1K_of_gfs_ceiling_pct": near})
            except Exception as error:  # noqa: BLE001
                print(f"{hour}Z{'':<3}{'ERA5':<8}{name:<32}  unavailable: "
                      f"{type(error).__name__} {str(error)[:50]}")
            try:
                t, r = gfs_box(moment, box)
                theta = theta_e_from_specific(t, specific_from_relative(t, r))
                at = float((theta >= GFS_CEILING_K - 0.001).mean() * 100)
                print(f"{hour}Z{'':<3}{'GFS':<8}{name:<32}{theta.size:>7}"
                      f"{np.median(theta):>9.2f}{np.percentile(theta, 90):>8.2f}"
                      f"{theta.max():>8.2f}{at:>11.1f}%")
                results["rows"].append({"hour": hour, "source": "GFS", "box": name,
                                        "n": int(theta.size),
                                        "p50": float(np.median(theta)),
                                        "p90": float(np.percentile(theta, 90)),
                                        "max": float(theta.max()),
                                        "exactly_at_ceiling_pct": at})
            except Exception as error:  # noqa: BLE001
                print(f"{hour}Z{'':<3}{'GFS':<8}{name:<32}  unavailable: "
                      f"{type(error).__name__} {str(error)[:50]}")
        print()

    print(f"DECLARED BEFORE RUNNING: if the clamp is the terrain acting on any model,")
    print(f"ERA5 in this warm-season box reaches the same order and sits near its own")
    print(f"top; if it is the GFS field or xue's storage of it, ERA5 does not.")
    print(f"The 'at ceiling' column is not symmetric: ERA5 has no ceiling, so it")
    print(f"counts cells within 1 K of the GFS codebook maximum, which is a")
    print(f"comparison of distributions and not of the same quantity.")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(results, handle, indent=2, ensure_ascii=False, default=str)
            handle.write("\n")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
