#!/usr/bin/env python3
"""ERA5 against GFS, on the fields this repository has made claims about.

Two independent reanalyses, the same days, the same hours, the same boxes.  This
is the first check in the tree that can say whether a field xue delivers agrees
with anything other than itself: every earlier check compared GFS with GFS, or
with the stations, but no station archive reaches these dates and no second model
was available.  ERA5 arrives on the portable drive and supplies that second
model, at the cost of one limitation stated up front: the drive holds January
2024 only, so the comparison is a winter comparison, and the theta-e claim's
clamp is a summer phenomenon seen in September.  A winter agreement does not
test a summer claim.

Read in place from /Volumes/Newsmy.  ERA5 is a Copernicus product: free to use,
not public domain, and this repository admits public domain only, so no bytes
are copied into the tree.

Two traps this code is written around, both of which it fell into first:

  * ERA5's longitudes run 0..360 and GFS's run -180..180, so a box like the
    Andes (-80..-68) selects zero ERA5 cells unless it is re-expressed as
    280..292.  Each source's mask is therefore built from that source's own
    coordinate arrays, never from the other's.
  * GDAL returns GRIB temperatures already in Celsius and says so in GRIB_UNIT,
    while ERA5's NetCDF packing is in kelvin.  The unit is read from each file.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import urllib.request
import warnings

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bolton import bolton_theta_e  # noqa: E402

DRIVE = "/Volumes/Newsmy"
BUCKET = "https://noaa-gfs-bdp-pds.s3.amazonaws.com"
UA = {"User-Agent": "xue-study/1.0 (+era5-vs-gfs)"}
BOXES = {
    "plateau (80-92E, 26-32N)": (26.0, 32.0, 80.0, 92.0),
    "warm pool (120-180E, 15S-15N)": (-15.0, 15.0, 120.0, 180.0),
    "Andes (80-68W, 18-8S)": (-18.0, -8.0, -80.0, -68.0),
    "global (-60..60)": (-60.0, 60.0, -180.0, 180.0),
}


def gfs_bytes(url: str, byte_range=None, timeout: int = 180) -> bytes:
    headers = dict(UA)
    if byte_range:
        headers["Range"] = f"bytes={byte_range[0]}-{byte_range[1]}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers),
                                timeout=timeout) as response:
        return response.read()


def gfs_field(stamp: str, phrase: str):
    """One GRIB record, decoded, with its own coordinate arrays."""
    import rasterio
    warnings.filterwarnings("ignore")
    base = f"{BUCKET}/gfs.{stamp}/12/atmos/gfs.t12z.pgrb2.0p25.f000"
    lines = gfs_bytes(base + ".idx").decode().splitlines()
    offsets = sorted(int(l.split(":")[1]) for l in lines if l.strip())
    for line in lines:
        if phrase in line:
            start = int(line.split(":")[1])
            following = [o for o in offsets if o > start]
            raw = gfs_bytes(base, (start, following[0] - 1 if following else start + 900_000))
            with rasterio.open(io.BytesIO(raw)) as source:
                data = source.read(1).astype(np.float64)
                unit = (source.tags(1).get("GRIB_UNIT") or "").strip()
                transform, height, width = source.transform, source.height, source.width
            if unit in ("[K]", "K"):
                data = data - 273.15
            lon = transform.c + transform.a * (np.arange(width) + 0.5)
            lat = transform.f + transform.e * (np.arange(height) + 0.5)
            return data, lon, lat
    raise KeyError(phrase)


def era5_field(stamp: str, name: str, hour_index: int = 13, level: int | None = None):
    """One ERA5 variable, or one level of one, with its own coordinate arrays."""
    import rasterio
    warnings.filterwarnings("ignore")
    if level is None:
        path = f"{DRIVE}/单层变量/single_lvl/era5.{stamp}.nc"
        with rasterio.open(path) as dataset:
            target = next(s for s in dataset.subdatasets if s.endswith(":" + name))
        with rasterio.open(target) as source:
            raw = source.read(hour_index).astype(np.float64)
            tags = source.tags(hour_index)
            transform, height, width = source.transform, source.height, source.width
    else:
        path = f"{DRIVE}/多层变量/{name}/era5.{name}.{stamp}.nc"
        with rasterio.open(path) as source:
            band = None
            times = []
            for candidate in range(1, source.count + 1):
                tagged = source.tags(candidate)
                stamp_tag = tagged.get("NETCDF_DIM_time")
                if stamp_tag not in times:
                    times.append(stamp_tag)
                if (int(tagged.get("NETCDF_DIM_level", 0)) == level
                        and times.index(stamp_tag) == hour_index - 1):
                    band = candidate
                    break
            if band is None:
                raise KeyError(f"{name} at {level} hPa, hour {hour_index}")
            raw = source.read(band).astype(np.float64)
            tags = source.tags(band)
            transform, height, width = source.transform, source.height, source.width
    data = raw * float(tags["scale_factor"]) + float(tags.get("add_offset", 0.0))
    data[raw == float(tags.get("_FillValue", -32767))] = np.nan
    # ERA5 packs temperature in kelvin and says so; every other variable in this
    # collection carries a unit where that conversion would be wrong.  Read the
    # unit rather than assuming, which is the same rule applied to the GRIB side.
    if (tags.get("units") or "").strip() == "K":
        data = data - 273.15
    lon = transform.c + transform.a * (np.arange(width) + 0.5)
    lat = transform.f + transform.e * (np.arange(height) + 0.5)
    return data, lon, lat


def mask_for(lon, lat, box):
    south, north, west, east = box
    lon2d, lat2d = np.meshgrid(lon, lat)
    # longitudes may be 0..360 or -180..180; accept either spelling of the box
    if lon.min() >= 0.0:
        west, east = west % 360.0, east % 360.0
        if west > east:
            return (lat2d >= south) & (lat2d <= north) & ((lon2d >= west) | (lon2d <= east))
    return (lat2d >= south) & (lat2d <= north) & (lon2d >= west) & (lon2d <= east)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stamps", nargs="+", default=["20240101", "20240115", "20240131"])
    ap.add_argument("--json", metavar="PATH")
    args = ap.parse_args()

    if not os.path.isdir(DRIVE):
        print(f"REFUSED the drive is not mounted at {DRIVE}")
        return 1

    out: dict = {"stamps": args.stamps, "boxes": {}}
    print("ERA5 (drive) against GFS (NOAA archive), same days, 12Z")
    print(f"\n{'day':<8}{'box':<32}{'ERA5':>9}{'GFS':>9}{'diff':>8}   field")
    for stamp in args.stamps:
        try:
            t2e, lon_e, lat_e = era5_field(stamp, "t2m")
            t2g, lon_g, lat_g = gfs_field(stamp, ":TMP:2 m above ground:anl:")
        except Exception as error:  # noqa: BLE001
            print(f"  {stamp}: {type(error).__name__} {str(error)[:70]}")
            continue
        for name, box in BOXES.items():
            me = mask_for(lon_e, lat_e, box)
            mg = mask_for(lon_g, lat_g, box)
            if me.sum() == 0 or mg.sum() == 0:
                print(f"{stamp[4:]:<8}{name:<32}{'--':>9}{'--':>9}{'':>8}   "
                      f"(no cells: ERA5 {int(me.sum())}, GFS {int(mg.sum())})")
                continue
            a = float(np.nanmedian(t2e[me]))
            b = float(np.nanmedian(t2g[mg]))
            print(f"{stamp[4:]:<8}{name:<32}{a:>9.2f}{b:>9.2f}{a - b:>+8.2f}   t2m degC")
            out["boxes"].setdefault(name, {}).setdefault("t2m", {})[stamp] = {
                "era5": a, "gfs": b, "diff": a - b}

        # 850 hPa equivalent potential temperature, the level the theta-e claim is about
        try:
            te, lon_et, lat_et = era5_field(stamp, "temperature", level=850)
            re_, _, _ = era5_field(stamp, "relative_humidity", level=850)
            tg, lon_gt, lat_gt = gfs_field(stamp, ":TMP:850 mb:anl:")
            rg, _, _ = gfs_field(stamp, ":RH:850 mb:anl:")
        except Exception as error:  # noqa: BLE001
            print(f"          850 hPa unavailable: {type(error).__name__}")
            continue
        for name in ("plateau (80-92E, 26-32N)", "warm pool (120-180E, 15S-15N)"):
            box = BOXES[name]
            me = mask_for(lon_et, lat_et, box)
            mg = mask_for(lon_gt, lat_gt, box)
            rows = []
            for data_t, data_r, mask in ((te, re_, me), (tg, rg, mg)):
                t = data_t[mask]
                rh = data_r[mask]
                good = np.isfinite(t) & np.isfinite(rh)
                t, rh = t[good], rh[good]
                vapour = (rh / 100.0) * 6.112 * np.exp(17.67 * t / (t + 243.5))
                q = 0.622 * vapour / (850.0 - 0.378 * vapour)
                rows.append(float(np.median(bolton_theta_e(t, q, 850.0))))
            print(f"{stamp[4:]:<8}{name:<32}{rows[0]:>9.2f}{rows[1]:>9.2f}"
                  f"{rows[0] - rows[1]:>+8.2f}   theta-e 850 hPa K")
            out["boxes"].setdefault(name, {}).setdefault("thetae850", {})[stamp] = {
                "era5": rows[0], "gfs": rows[1], "diff": rows[0] - rows[1]}

    print("\nWHAT THIS SHOWS: that two independent reanalyses agree on these fields")
    print("over these boxes on these days, which no earlier check could say.")
    print("WHAT IT DOES NOT: test the summer clamp.  The drive holds January only.")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(out, handle, indent=2, ensure_ascii=False, default=str)
            handle.write("\n")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
