#!/usr/bin/env python3
"""Amplitude offset tracking on Sentinel-1, against a measured detection floor.

Why this and not NISAR.  The third problem card records that the precursor the
literature names -- flow velocity, on the order of 0.4 m per day -- is in no
atmospheric dataset, and that synthetic aperture radar measures it.  NISAR's
GOFF product is purpose-built for exactly that and the event has four of them
over this valley.  They are not reachable: ASF's search API answers anonymously
and the files answer HEAD with 200 now and then, but GET returns 401 and the
responses are not consistent between requests, which is an authenticated product
behind an intermittent edge.  A result built on a 200 that happens once is not a
result, so this uses the Sentinel-1 RTC data that is reliably anonymous, and says
what that costs: a geocoded, terrain-corrected amplitude product is a worse
substrate for sub-pixel offsets than the product designed for it.

The discipline is the one this repository has settled on: measure the floor
before claiming a signal.  Two same-orbit pairs are used, each twelve days apart:

    path 19 descending   08-12 -> 08-24   the interval in which the reported
                                          0.4 m/day acceleration was observed,
                                          and two days before the collapse
    path 85 ascending    08-04 -> 08-16   a pre-event pair with nothing in it

Patch-wise normalized cross-correlation on the amplitude, peak refined by a
parabolic fit, and the displacement field of the quiet pair IS the detection
floor.  A displacement in the event pair is a detection only if it stands clear
of that floor.
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
UA = {"User-Agent": "xue-study/1.0 (+sar-offset)"}
CORRIDOR = (85.15, 28.10, 85.60, 28.40)
SOURCE = (28.2853, 85.5252)
PATCH = 48          # pixels
STEP = 12           # pixels between patch centres
SEARCH = 6          # pixels of search radius
TARGET_RES = 20.0


def post(url: str, body: dict) -> dict:
    request = urllib.request.Request(url, data=json.dumps(body).encode(),
                                     headers={**UA, "Content-Type": "application/json"},
                                     method="POST")
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.loads(response.read())


def get_json(url: str) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90) as response:
        return json.loads(response.read())


def read_amplitude(day: str, path: int, polarization: str = "vv"):
    """The corridor window at 20 m, in dB, with its projected geometry."""
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.warp import transform, transform_bounds
    from rasterio.windows import from_bounds
    warnings.filterwarnings("ignore")
    result = post(f"{API}/search", {
        "collections": ["sentinel-1-rtc"], "bbox": list(CORRIDOR),
        "datetime": f"{day}T00:00:00Z/{day}T23:59:59Z", "limit": 20})
    feature = None
    for f in result.get("features", []):
        if f["properties"].get("sat:relative_orbit") == path:
            feature = f
            break
    if feature is None:
        raise KeyError(f"no scene for {day} path {path}")
    href = get_json(f"{SAS}/sign?href=" + urllib.parse.quote(
        feature["assets"][polarization]["href"], safe=""))["href"]
    print(f"    {day} path {path} {polarization}", flush=True)
    with rasterio.open(href) as dataset:
        bounds = transform_bounds("EPSG:4326", dataset.crs, *CORRIDOR)
        window = from_bounds(*bounds, dataset.transform)
        factor = dataset.res[0] / TARGET_RES
        out_shape = (max(1, round(window.height * factor)),
                     max(1, round(window.width * factor)))
        data = dataset.read(1, window=window, out_shape=out_shape,
                            resampling=Resampling.average)
        transform_out = dataset.window_transform(window) * rasterio.Affine.scale(
            window.width / out_shape[1], window.height / out_shape[0])
        nodata = dataset.nodata
        xs, ys = transform("EPSG:4326", dataset.crs, [SOURCE[1]], [SOURCE[0]])
    data = data.astype(np.float64)
    data[data == nodata] = np.nan
    data[data <= 0] = np.nan
    with np.errstate(divide="ignore", invalid="ignore"):
        decibels = 10.0 * np.log10(data)
    return decibels, transform_out, (float(xs[0]), float(ys[0]))


def normalized_correlation(reference: np.ndarray, target: np.ndarray) -> np.ndarray:
    """Correlation of a zero-mean reference against every placement in target.

    Computed through FFT so the search is a single transform rather than a loop
    over offsets; the reference is padded to the target's shape.
    """
    ref = reference - reference.mean()
    ref_norm = np.sqrt((ref ** 2).sum())
    tgt = target - target.mean()
    tgt_norm = np.sqrt((tgt ** 2).sum())
    if ref_norm == 0 or tgt_norm == 0:
        return np.zeros_like(target)
    shape = (reference.shape[0] + target.shape[0] - 1,
             reference.shape[1] + target.shape[1] - 1)
    spectrum = (np.fft.rfft2(tgt, shape) * np.conj(np.fft.rfft2(ref, shape)))
    correlated = np.fft.irfft2(spectrum, shape)[:target.shape[0], :target.shape[1]]
    return correlated / (ref_norm * tgt_norm)


def subpixel_peak(correlation: np.ndarray, row: int, col: int) -> tuple[float, float, float]:
    """Parabolic refinement of a correlation peak, in pixels."""
    def refine(centre: float, before: float, after: float) -> float:
        denominator = before - 2.0 * centre + after
        if denominator == 0:
            return 0.0
        return 0.5 * (before - after) / denominator
    peak = correlation[row, col]
    dr = dc = 0.0
    if 0 < row < correlation.shape[0] - 1:
        dr = refine(peak, correlation[row - 1, col], correlation[row + 1, col])
    if 0 < col < correlation.shape[1] - 1:
        dc = refine(peak, correlation[row, col - 1], correlation[row, col + 1])
    return col + dc, row + dr, peak


def offset_field(reference: np.ndarray, target: np.ndarray, mask: np.ndarray):
    """Displacement in metres, its correlation, and where it was measured.

    The search is done patch by patch over a padded window, so a displacement is
    only reported where the whole patch fits inside the searched area.
    """
    height, width = reference.shape
    pad = SEARCH + PATCH // 2
    displacements, qualities, positions = [], [], []
    for row in range(pad, height - pad, STEP):
        for col in range(pad, width - pad, STEP):
            if not mask[row, col]:
                continue
            ref_patch = reference[row - PATCH // 2:row + PATCH // 2,
                                  col - PATCH // 2:col + PATCH // 2]
            tgt_window = target[row - PATCH // 2 - SEARCH:row + PATCH // 2 + SEARCH,
                                col - PATCH // 2 - SEARCH:col + PATCH // 2 + SEARCH]
            if not (np.isfinite(ref_patch).all() and np.isfinite(tgt_window).all()):
                continue
            correlation = normalized_correlation(ref_patch, tgt_window)
            peak_index = np.unravel_index(int(np.argmax(correlation)), correlation.shape)
            dx, dy, quality = subpixel_peak(correlation, *peak_index)
            # The peak sits at (SEARCH, SEARCH) when nothing moved, and a shift of
            # the scene by +s moves the peak to SEARCH - s.  A synthetic test with
            # known shifts established both: the first version used
            # `peak - (PATCH//2 + SEARCH - 0.5)`, which has the sign inverted AND
            # the wrong origin, and it reported a flat 664 m for every pair --
            # identical on the quiet pair and the event pair, which is what an
            # artefact looks like and not what a displacement looks like.
            displacements.append(((SEARCH - dx) * TARGET_RES, (SEARCH - dy) * TARGET_RES))
            qualities.append(quality)
            positions.append((row, col))
    return (np.array(displacements), np.array(qualities), np.array(positions))


def synthesize_shift_test() -> list[str]:
    """Recover known synthetic shifts, or say which ones came back wrong.

    Exposed as a function so `methodology_check.py` can run it every time, which
    is the only reason this particular bug cannot come back.
    """
    generator = np.random.default_rng(7)
    scene = generator.normal(size=(200, 200))
    failures = []
    for true_row, true_col in ((0, 0), (3, 0), (0, -4), (5, 2), (-6, 1)):
        reference = scene[60:60 + PATCH, 60:60 + PATCH]
        top = 60 + true_row - SEARCH
        left = 60 + true_col - SEARCH
        window = scene[top:top + PATCH + 2 * SEARCH, left:left + PATCH + 2 * SEARCH]
        correlation = normalized_correlation(reference, window)
        peak_index = np.unravel_index(int(np.argmax(correlation)), correlation.shape)
        dc, dr, _ = subpixel_peak(correlation, *peak_index)
        got_row, got_col = SEARCH - dr, SEARCH - dc
        if abs(got_row - true_row) > 0.2 or abs(got_col - true_col) > 0.2:
            failures.append(f"shift ({true_row:+d},{true_col:+d}) recovered as "
                            f"({got_row:+.2f},{got_col:+.2f})")
    return failures


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", metavar="PATH")
    args = ap.parse_args()

    PAIRS = [
        {"label": "floor (pre-event)", "path": 85, "days": ("2026-08-04", "2026-08-16")},
        {"label": "event window", "path": 19, "days": ("2026-08-12", "2026-08-24")},
    ]
    out: dict = {}
    print(f"corridor {CORRIDOR}, patches {PATCH}px step {STEP}px search +-{SEARCH}px, "
          f"{TARGET_RES:.0f} m cells\n")
    for pair in PAIRS:
        print(f"=== {pair['label']}: path {pair['path']} "
              f"{pair['days'][0]} -> {pair['days'][1]} ===")
        reference, transform, source_xy = read_amplitude(pair["days"][0], pair["path"])
        target, _, _ = read_amplitude(pair["days"][1], pair["path"])
        height, width = reference.shape
        rows = np.arange(height)[:, None]
        cols = np.arange(width)[None, :]
        east = np.broadcast_to(transform.c + transform.a * (cols + 0.5), (height, width))
        north = np.broadcast_to(transform.f + transform.e * (rows + 0.5), (height, width))
        distance = np.hypot(east - source_xy[0], north - source_xy[1]) / 1000.0
        near = distance <= 3.0
        usable = np.isfinite(reference) & np.isfinite(target)
        print(f"    window {height}x{width}; {int(near.sum())} cells within 3 km of "
              f"the detachment")

        displacement, quality, positions = offset_field(reference, target, usable)
        if displacement.size == 0:
            print("    no patches")
            continue
        magnitude = np.hypot(displacement[:, 0], displacement[:, 1])
        good = quality >= 0.15
        print(f"    patches {displacement.size // 2}, of which correlation >= 0.15: "
              f"{int(good.sum())}")
        if good.sum():
            row_col = positions[good]
            ring = np.hypot(east[row_col[:, 0], row_col[:, 1]] - source_xy[0],
                            north[row_col[:, 0], row_col[:, 1]] - source_xy[1]) / 1000.0
            local = ring <= 3.0
            print(f"    displacement magnitude, all patches with good correlation: "
                  f"median {np.median(magnitude[good]):.2f} m")
            if local.sum():
                print(f"    within 3 km of the detachment ({int(local.sum())} patches): "
                      f"median {np.median(magnitude[good][local]):.2f} m, "
                      f"90th pct {np.percentile(magnitude[good][local], 90):.2f} m")
            out[pair["label"]] = {
                "patches": int(displacement.size // 2),
                "good": int(good.sum()),
                "median_m": float(np.median(magnitude[good])),
                "median_near_m": (float(np.median(magnitude[good][local]))
                                  if local.sum() else None),
                "p90_near_m": (float(np.percentile(magnitude[good][local], 90))
                               if local.sum() else None),
            }
        del reference, target

    if len(out) == 2:
        floor = out["floor (pre-event)"]
        event = out["event window"]
        print("\n=== the test ===")
        print(f"  floor pair  median displacement {floor['median_m']:.2f} m, "
              f"near the detachment {floor['median_near_m']} m")
        print(f"  event pair  median displacement {event['median_m']:.2f} m, "
              f"near the detachment {event['median_near_m']} m")
        if floor["median_near_m"] and event["median_near_m"]:
            ratio = event["median_near_m"] / floor["median_near_m"]
            print(f"  ratio {ratio:.2f}")
            out["ratio"] = ratio
        print("\n  DECLARED BEFORE RUNNING: a displacement at the glacier is a")
        print("  detection only if it stands clear of the same measurement on a pair")
        print("  where nothing happened.  The reported precursor is 0.4 m/day, which")
        print("  over a 12-day pair is about 4.8 m; the search window here is "
              f"+-{SEARCH * TARGET_RES:.0f} m, so a displacement of that size is inside")
        print("  the search range but is about a quarter of one 20 m cell, which is")
        print("  where a terrain-corrected amplitude product stops being the right")
        print("  instrument.  Stated here rather than discovered later.")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(out, handle, indent=2, ensure_ascii=False, default=str)
            handle.write("\n")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
