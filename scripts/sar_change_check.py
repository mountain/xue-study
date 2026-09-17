#!/usr/bin/env python3
"""Reproduce the Sentinel-1 change detection for the 2026-08-26 Langtang event.

The event: 2026-08-26 02:52:10 UTC, an ice-rock avalanche from the north face of
Langtang Lirung on the China-Nepal border, detachment reported at
28.2853N, 85.5252E.  Debris ran down the Bhote Koshi and the Trishuli.

Why this belongs in this repository: the third problem card recorded that the
precursor the literature names for glacier collapse -- flow velocity, 0.4 m per
day in the 2026 event it studied -- is not in any atmospheric dataset.  Synthetic
aperture radar measures it.  SAR is therefore the observational side that the
atmospheric index has never been checked against, and the 2026-08-26 event is a
case where both exist.

Method, taken from the public write-up at blog.ringsaturn.me and reproduced here
rather than trusted:

  * Sentinel-1 RTC gamma0 from Microsoft Planetary Computer, anonymous read,
    assets signed through its SAS endpoint.  The rasters are UTM (EPSG:32645 here)
    at 10 m, linear power, nodata -32768.
  * All comparisons are within one orbit.  Ascending and descending look at
    opposite sides of a ridge, so the same slope is layover in one and shadow in
    the other; a pixel-wise comparison across geometries is meaningless.
  * Average to 20 m, convert to dB, smooth 5x5, threshold at +-3 dB, discard
    patches below 20 000 m^2.
  * The noise floor is measured, not assumed: the same pipeline is run on a
    pre-event same-orbit pair, where by construction nothing happened.

Erring toward the same choices the published numbers used, so that a difference
between them and these is a difference in the data or the code and not in the
setup.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
import warnings

import numpy as np

API = "https://planetarycomputer.microsoft.com/api/stac/v1"
SAS = "https://planetarycomputer.microsoft.com/api/sas/v1"
UA = {"User-Agent": "xue-study/1.0 (+sar-crosscheck)"}
CORRIDOR = (85.15, 28.10, 85.60, 28.40)
FULL_AOI = (85.09, 27.79, 85.71, 28.51)
SOURCE = (28.2853, 85.5252)
MIN_PATCH_M2 = 20_000
DB_THRESHOLD = 3.0


def post(url: str, body: dict) -> dict:
    request = urllib.request.Request(url, data=json.dumps(body).encode(),
                                     headers={**UA, "Content-Type": "application/json"},
                                     method="POST")
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.loads(response.read())


def get(url: str) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90) as response:
        return json.loads(response.read())


def search(start: str, end: str) -> list[dict]:
    result = post(f"{API}/search", {
        "collections": ["sentinel-1-rtc"], "bbox": list(REVERSED),
        "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z", "limit": 100,
    })
    return result.get("features", [])


def sign(href: str) -> str:
    return get(f"{SAS}/sign?href=" + urllib.parse.quote(href, safe=""))["href"]


def read_scene(feature: dict, polarization: str, target_res: float = 20.0,
               box: tuple | None = None):
    """AOI window at the target resolution, in dB, with its UTM geometry.

    Returns the window's bounds **in the raster's own projected CRS**, and the
    source point transformed into that CRS too.  The first version of this
    function handed back a UTM transform while the caller built its region mask
    in degrees, so `lat >= 27.79` was false everywhere, the region was empty and
    every change area came out exactly zero -- which reads like "nothing
    happened" rather than like a bug.  Everything geometric now happens in the
    raster's CRS, where the distances are also true metres rather than degrees.
    """
    day = feature["properties"]["datetime"][:10]
    path = feature["properties"].get("sat:relative_orbit")
    print(f"    reading {day} path {path} {polarization} ...", flush=True)
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.warp import transform_bounds
    from rasterio.windows import from_bounds
    warnings.filterwarnings("ignore")
    href = sign(feature["assets"][polarization]["href"])
    box = box or FULL_AOI
    with rasterio.open(href) as dataset:
        bounds = transform_bounds("EPSG:4326", dataset.crs, *box)
        window = from_bounds(*bounds, dataset.transform)
        # Going from 10 m native to 20 m target means FEWER cells, so the factor
        # multiplies: the first version divided, produced a two-times oversampled
        # window, and every area came out 16 times too large while still looking
        # plausible.  Cell size is now read back from the output transform rather
        # than assumed, so the same mistake cannot survive in the area arithmetic.
        factor = dataset.res[0] / target_res
        out_shape = (max(1, round(window.height * factor)),
                     max(1, round(window.width * factor)))
        data = dataset.read(1, window=window, out_shape=out_shape,
                            resampling=Resampling.average)
        transform = dataset.window_transform(window) * rasterio.Affine.scale(
            window.width / out_shape[1], window.height / out_shape[0])
        nodata = dataset.nodata
        source_xy = transform_point_xy(dataset.crs, SOURCE)
    window_bounds = (transform.c, transform.f + transform.e * out_shape[0],
                     transform.c + transform.a * out_shape[1], transform.f)
    cell_m2 = abs(transform.a * transform.e)
    data = data.astype(np.float64)
    data[data == nodata] = np.nan
    data[data <= 0] = np.nan
    with np.errstate(divide="ignore", invalid="ignore"):
        decibels = 10.0 * np.log10(data)
    return decibels, transform, window_bounds, source_xy, cell_m2


def transform_point_xy(crs, lonlat):
    """One lon/lat point into the raster's CRS, so distances are metres."""
    from rasterio.warp import transform as warp_transform
    xs, ys = warp_transform("EPSG:4326", crs, [lonlat[1]], [lonlat[0]])
    return float(xs[0]), float(ys[0])


def box_mean(data: np.ndarray, size: int = 5) -> np.ndarray:
    """Uniform filter by summed-area table; scipy is not available here."""
    filled = np.where(np.isfinite(data), data, 0.0)
    weight = np.isfinite(data).astype(np.float64)
    pad = size // 2
    padded = np.pad(filled, pad, mode="constant")
    padded_w = np.pad(weight, pad, mode="constant")
    total = padded.cumsum(0).cumsum(1)
    totals = np.pad(total, ((1, 0), (1, 0)), mode="constant")
    def window_sum(arr):
        return (arr[size:, size:] - arr[:-size, size:]
                - arr[size:, :-size] + arr[:-size, :-size])
    sum_values = window_sum(totals)
    sum_weights = window_sum(np.pad(padded_w.cumsum(0).cumsum(1), ((1, 0), (1, 0))))
    with np.errstate(invalid="ignore", divide="ignore"):
        return sum_values / sum_weights


def components(mask: np.ndarray) -> tuple[np.ndarray, dict]:
    """4-connected labelling by run-length union-find."""
    height, width = mask.shape
    labels = np.zeros((height, width), dtype=np.int32)
    parent = [0]
    next_label = 1
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    previous = []
    for y in range(height):
        row = mask[y].astype(np.int8)
        delta = np.diff(np.concatenate(([0], row, [0])))
        starts, ends = np.flatnonzero(delta == 1), np.flatnonzero(delta == -1)
        current = []
        for start, end in zip(starts.tolist(), ends.tolist()):
            label = 0
            for ps, pe, pl in previous:
                if ps < end and start < pe:
                    if label == 0:
                        label = pl
                    else:
                        union(label, pl)
            if label == 0:
                label = next_label
                parent.append(label)
                next_label += 1
            labels[y, start:end] = label
            current.append((start, end, label))
        previous = current
    if next_label == 1:
        return labels, {}
    lookup = np.arange(next_label, dtype=np.int32)
    for i in range(1, next_label):
        lookup[i] = find(i)
    labels = lookup[labels]
    uniq, counts = np.unique(labels[labels > 0], return_counts=True)
    return labels, dict(zip(uniq.tolist(), counts.tolist()))


def change_area(before: np.ndarray, after: np.ndarray, cell_m2: float,
                region: np.ndarray) -> dict:
    difference = box_mean(after) - box_mean(before)
    out = {}
    for sign_name, mask in (("brighten", difference >= DB_THRESHOLD),
                            ("darken", difference <= -DB_THRESHOLD)):
        mask = mask & region & np.isfinite(difference)
        _, sizes = components(mask)
        kept = sum(s for s in sizes.values() if s * cell_m2 >= MIN_PATCH_M2)
        out[sign_name] = kept * cell_m2 / 1e6
        out[sign_name + "_cells"] = kept
    out["difference"] = difference
    return out


REVERSED = (FULL_AOI[0], FULL_AOI[1], FULL_AOI[2], FULL_AOI[3])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", metavar="PATH")
    args = ap.parse_args()

    print("Sentinel-1 RTC gamma0, Microsoft Planetary Computer, anonymous read")
    features = search("2026-08-01", "2026-09-15")
    by_key = {}
    for f in features:
        p = f["properties"]
        key = (p["datetime"][:10], p.get("sat:relative_orbit"), p.get("sat:orbit_state"))
        by_key.setdefault(key, f)
    print(f"  {len(features)} scenes, {len(by_key)} distinct (day, path, orbit):")
    for key in sorted(by_key):
        print(f"    {key[0]}  path {key[1]:>3} {key[2]}")

    def pick(day, path):
        for (d, p, o), f in by_key.items():
            if d == day and p == path:
                return f
        raise KeyError(f"{day} path {path}")

    results: dict = {"scenes": sorted(f"{k[0]} path {k[1]} {k[2]}" for k in by_key)}

    # --- noise floor: same orbit, same 12-day gap, before the event ---------
    print("\nnoise floor, path 85 ascending, 08-04 -> 08-16 (nothing happened)")
    pre_a = read_scene(pick("2026-08-04", 85), "vv", box=CORRIDOR)
    pre_b = read_scene(pick("2026-08-16", 85), "vv", box=CORRIDOR)
    pre_ah = read_scene(pick("2026-08-04", 85), "vh", box=CORRIDOR)
    pre_bh = read_scene(pick("2026-08-16", 85), "vh", box=CORRIDOR)
    cell = pre_a[4]
    print(f"  output cell {abs(pre_a[1].a):.1f} x {abs(pre_a[1].e):.1f} m "
          f"= {cell:.0f} m2", flush=True)
    height, width = pre_a[0].shape
    rows = np.arange(height)[:, None]
    cols = np.arange(width)[None, :]
    transform = pre_a[1]
    east = transform.c + transform.a * (cols + 0.5)
    north = transform.f + transform.e * (rows + 0.5)
    east = np.broadcast_to(east, (height, width))
    north = np.broadcast_to(north, (height, width))
    region = np.ones((height, width), dtype=bool)     # the window is the AOI
    floor_vv = change_area(pre_a[0], pre_b[0], cell, region)
    floor_vh = change_area(pre_ah[0], pre_bh[0], cell, region)
    finite = np.isfinite(floor_vv["difference"])
    print(f"  window {pre_a[0].shape}, usable cells {finite.mean() * 100:.1f}%")
    print(f"  VV brighten {floor_vv['brighten']:6.1f} km2   darken {floor_vv['darken']:6.1f} km2")
    print(f"  VH brighten {floor_vh['brighten']:6.1f} km2   darken {floor_vh['darken']:6.1f} km2")
    results["noise_floor"] = {"vv": {k: v for k, v in floor_vv.items() if k != "difference"},
                              "vh": {k: v for k, v in floor_vh.items() if k != "difference"}}

    # --- cross-event: same orbit, across 08-26 ------------------------------
    print("\ncross-event, path 85 ascending, 08-16 -> 08-28 (the event is inside)")
    post_vv = read_scene(pick("2026-08-28", 85), "vv", box=CORRIDOR)
    post_vh = read_scene(pick("2026-08-28", 85), "vh", box=CORRIDOR)
    change_vv = change_area(pre_b[0], post_vv[0], cell, region)
    change_vh = change_area(pre_bh[0], post_vh[0], cell, region)
    print(f"  VV brighten {change_vv['brighten']:6.1f} km2   darken {change_vv['darken']:6.1f} km2")
    print(f"  VH brighten {change_vh['brighten']:6.1f} km2   darken {change_vh['darken']:6.1f} km2")
    print(f"  signal over noise floor (VV brighten): "
          f"{change_vv['brighten'] / max(floor_vv['brighten'], 1e-9):.1f}x")
    results["cross_event"] = {"vv": {k: v for k, v in change_vv.items() if k != "difference"},
                              "vh": {k: v for k, v in change_vh.items() if k != "difference"}}

    # --- where the change is ------------------------------------------------
    difference = change_vv["difference"]
    inside = region & np.isfinite(difference)
    density_all = float(np.nanmean(np.abs(difference[inside]) >= DB_THRESHOLD) * 100)
    source_x, source_y = pre_a[3]
    radial = np.hypot(east - source_x, north - source_y) / 1000.0   # km
    print(f"\nchange density over the whole AOI: {density_all:.2f}% of cells at |diff| >= 3 dB")
    bands = [(0, 2, "0-2 km of the detachment"), (2, 6, "2-6 km of it"),
             (6, 15, "6-15 km"), (15, 40, "15-40 km")]
    results["density"] = {"aoi_pct": density_all}
    for low, high, label in bands:
        band = inside & (radial >= low) & (radial < high)
        if band.sum() == 0:
            continue
        density = float(np.mean(np.abs(difference[band]) >= DB_THRESHOLD) * 100)
        print(f"  {label:<26} {density:5.2f}%   ({int(band.sum())} cells)")
        results["density"][label] = {"pct": density, "cells": int(band.sum())}

    print("\nWHAT THIS IS: an independent reproduction of a published change")
    print("detection, on public data, with the same setup, so that any difference")
    print("is the data or the code rather than the choices.")
    print("WHAT IT IS NOT: an attribution.  A change in backscatter at a place and")
    print("time is not a statement about what caused it.")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(results, handle, indent=2, ensure_ascii=False, default=str)
            handle.write("\n")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
