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
    print(f"  {len(features)} scenes, {len(by_key)} distinct (day, path, orbit)")

    def pick(day, path):
        for (d, p, o), f in by_key.items():
            if d == day and p == path:
                return f
        raise KeyError(f"{day} path {path}")

    # Three independent geometries over the same ground.  Each orbit contributes
    # a pre-event pair -- where by construction nothing happened, so its change
    # areas ARE that orbit's noise floor -- and a pair straddling 08-26.  The
    # scatter between the three orbits is the empirical repeatability of the
    # whole pipeline, which no single orbit can supply: one orbit gives a number,
    # three give a number and the spread of that number.
    ORBITS = [
        {"path": 85, "orbit": "ascending", "floor": ("2026-08-04", "2026-08-16"),
         "event": ("2026-08-16", "2026-08-28")},
        {"path": 121, "orbit": "descending", "floor": ("2026-08-07", "2026-08-19"),
         "event": ("2026-08-19", "2026-08-31")},
        {"path": 19, "orbit": "descending", "floor": ("2026-08-12", "2026-08-24"),
         "event": ("2026-08-24", "2026-09-05")},
    ]

    results: dict = {"orbits": {}}
    summary = []
    for spec in ORBITS:
        path = spec["path"]
        print(f"\n=== path {path} {spec['orbit']} ===")
        days = [spec["floor"][0], spec["floor"][1], spec["event"][1]]
        scenes = {}
        try:
            for day in days:
                scenes[day] = {pol: read_scene(pick(day, path), pol, box=CORRIDOR)
                               for pol in ("vv", "vh")}
        except Exception as error:  # noqa: BLE001
            print(f"  unavailable: {type(error).__name__} {str(error)[:80]}")
            continue

        before_floor, before_event, after_event = days
        reference = scenes[before_event]["vv"]
        cell = reference[4]
        height, width = reference[0].shape
        rows = np.arange(height)[:, None]
        cols = np.arange(width)[None, :]
        transform = reference[1]
        east = np.broadcast_to(transform.c + transform.a * (cols + 0.5), (height, width))
        north = np.broadcast_to(transform.f + transform.e * (rows + 0.5), (height, width))
        region = np.ones((height, width), dtype=bool)
        source_x, source_y = reference[3]
        radial = np.hypot(east - source_x, north - source_y) / 1000.0

        entry: dict = {"orbit": spec["orbit"], "path": path, "cell_m2": cell,
                       "scenes": days}
        print(f"  window {height}x{width} cells of {cell:.0f} m2")
        difference = None
        for label, before, after in (("floor", before_floor, before_event),
                                     ("event", before_event, after_event)):
            for pol in ("vv", "vh"):
                area = change_area(scenes[before][pol][0], scenes[after][pol][0],
                                   cell, region)
                entry[f"{label}_{pol}_brighten_km2"] = area["brighten"]
                entry[f"{label}_{pol}_darken_km2"] = area["darken"]
                if label == "event" and pol == "vv":
                    difference = area["difference"]
            print(f"  {label:<6} VV brighten {entry[f'{label}_vv_brighten_km2']:6.2f} "
                  f"darken {entry[f'{label}_vv_darken_km2']:6.2f} km2")
        ratio = (entry["event_vv_brighten_km2"] / entry["floor_vv_brighten_km2"]
                 if entry["floor_vv_brighten_km2"] > 0 else float("inf"))
        entry["vv_brighten_ratio"] = ratio
        print(f"  VV brighten over its own floor: {ratio:.1f}x")

        inside = region & np.isfinite(difference)
        entry["density"] = {}
        for low, high, label in ((0, 2, "0-2 km"), (2, 6, "2-6 km"),
                                 (6, 15, "6-15 km"), (15, 40, "15-40 km")):
            band = inside & (radial >= low) & (radial < high)
            if band.sum() == 0:
                continue
            entry["density"][label] = float(
                np.mean(np.abs(difference[band]) >= DB_THRESHOLD) * 100)
        entry["density"]["whole window"] = float(
            np.mean(np.abs(difference[inside]) >= DB_THRESHOLD) * 100)
        print("  density: " + "  ".join(f"{k} {v:.2f}%" for k, v in entry["density"].items()))
        results["orbits"][f"path {path} {spec['orbit']}"] = entry
        summary.append(entry)

    if len(summary) >= 2:
        print("\n=== the test: do independent geometries agree? ===")
        print(f"{'orbit':<26}{'floor VV br':>12}{'event VV br':>12}{'ratio':>7}"
              f"{'0-2 km':>9}{'2-6 km':>9}{'15-40 km':>10}")
        for e in summary:
            print(f"path {e['path']} {e['orbit']:<16}"
                  f"{e['floor_vv_brighten_km2']:>12.2f}{e['event_vv_brighten_km2']:>12.2f}"
                  f"{e['vv_brighten_ratio']:>6.1f}x"
                  f"{e['density'].get('0-2 km', float('nan')):>8.2f}%"
                  f"{e['density'].get('2-6 km', float('nan')):>8.2f}%"
                  f"{e['density'].get('15-40 km', float('nan')):>9.2f}%")
        near = [e["density"].get("0-2 km") for e in summary if e["density"].get("0-2 km") is not None]
        far = [e["density"].get("15-40 km") for e in summary if e["density"].get("15-40 km") is not None]
        if len(near) >= 2 and len(near) == len(far):
            all_above = all(n > f for n, f in zip(near, far))
            print(f"\n  source-region density across {len(near)} geometries: "
                  f"{[round(v, 2) for v in near]}   spread {max(near) - min(near):.2f} points")
            print(f"  far-field density: {[round(v, 2) for v in far]}   "
                  f"spread {max(far) - min(far):.2f} points")
            print(f"  every geometry shows the source region above the far field: {all_above}")
            results["convergence"] = {
                "source_density": near, "far_density": far,
                "source_spread": max(near) - min(near),
                "far_spread": max(far) - min(far),
                "source_above_far_in_all": all_above,
            }
            print("\n  DECLARED BEFORE RUNNING: the three orbits observe the same ground")
            print("  change, so their density profiles should agree to within the spread")
            print("  of their own measured floors.  A larger spread would mean either")
            print("  that the geometries see different things -- layover and shadow fall")
            print("  on opposite slopes in ascending and descending passes -- or that the")
            print("  pipeline is not stable.  This run does not separate the two.")
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
