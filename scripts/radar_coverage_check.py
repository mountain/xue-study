#!/usr/bin/env python3
"""Is the western half of the CMA radar mosaic *covered*, or merely *echo-free*?

The xue CMA-RADAR product (``l3-mst-cref``) declares in its own codebook::

    quantization: minimumCode 0, maximumCode 160, nodataCode 255

If the producer ever writes 255, then "outside radar coverage" is marked
in-band and the product can be used to measure Himalayan precipitation.  If it
never writes 255, then code 0 carries two different meanings at once ("no echo"
and "no radar here"), and a low echo fraction out west is *uninformative* --
it cannot be distinguished from a coverage hole.

That distinction is decidable from the product's own bytes plus arithmetic on
them, without any external truth.  Four predicates, each evaluated separately
for the Himalaya box and for two East-China control boxes:

  P1  the nodata code appears at all           absence is marked in-band
  P2  echo pixels form contiguous blobs        echo is precipitation, not speckle
  P3  echo persists across 6-minute frames     echo is a weather system
  P4  echo level reaches convective dBZ        echo is precipitation, not clutter

A control box that passes all four while the Himalaya box fails localises the
cause in the Himalaya box, not in the product as a whole.  Conversely, if the
Himalaya box fails P2/P3/P4 the way noise fails them, the correct statement is
"not covered", not "no rain".

Exit status 0 always (this is a measurement, not a gate); verdicts are printed
and, with --json, written out.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from urllib.parse import urljoin

import numpy as np
import xarray as xr

BASE = "https://dataset.ringsaturn.me/xue/"
UA = {"User-Agent": "xue-study/1.0 (+radar-coverage-check)"}

# box name -> (west, east, south, north) in degrees
BOXES = {
    "himalaya-tibet": (80.0, 92.0, 26.0, 32.0),
    "ctrl-east-china": (110.0, 122.0, 25.0, 35.0),
    "ctrl-north-china": (110.0, 120.0, 35.0, 42.0),
    # Far outside any Chinese radar's ~230 km range.  If these carry coherent
    # echo, the mosaic is not a pure radar-range composite and the absence of
    # echo anywhere else cannot be blamed on range.
    "offshore-bay-of-bengal": (85.0, 92.0, 15.0, 20.0),
    "offshore-south-china-sea": (110.0, 118.0, 12.0, 18.0),
    "offshore-arabian-sea": (68.0, 74.0, 12.0, 18.0),
}

DEFAULT_SUBJECT = "himalaya-tibet"

# a blob this many cells or larger is treated as a coherent weather system.
# at 0.04395 deg the cell area is ~20 km^2 near 30N, so 25 cells ~ 500 km^2.
BLOB_MIN_CELLS = 25


def fetch(url: str, attempts: int = 6, timeout: int = 60) -> bytes:
    last: Exception | None = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers=UA)
            return urllib.request.urlopen(req, timeout=timeout).read()
        except Exception as exc:  # noqa: BLE001 - transient network only
            last = exc
            time.sleep(2 + 2 * i)
    raise RuntimeError(f"failed after {attempts} attempts: {url}") from last


def fetch_json(url: str):
    return json.loads(fetch(url))


def open_latest() -> tuple[xr.Dataset, xr.Dataset, dict]:
    """Return (raw dataset, scaled dataset, item) for the latest CMA radar window."""
    ptr = fetch_json(urljoin(BASE, "latest-cma.json"))
    item_url = urljoin(BASE, ptr["manifestPath"].replace("manifest.json", "item.json"))
    item = fetch_json(item_url)
    href = urljoin(item_url, item["assets"]["cref"]["href"])
    raw = xr.open_zarr(href, mask_and_scale=False)
    scaled = xr.open_zarr(href)
    return raw, scaled, item


def component_labels(mask: np.ndarray) -> tuple[np.ndarray, dict[int, int]]:
    """4-connected run-length union-find labelling. label 0 is background."""
    height, width = mask.shape
    labels = np.zeros((height, width), dtype=np.int32)
    parent: list[int] = [0]          # parent[label]; index 0 unused
    next_label = 1

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    previous_runs: list[tuple[int, int, int]] = []
    for y in range(height):
        row = mask[y].astype(np.int8)
        delta = np.diff(np.concatenate(([0], row, [0])))
        starts = np.flatnonzero(delta == 1)
        ends = np.flatnonzero(delta == -1)
        current_runs: list[tuple[int, int, int]] = []
        for start, end in zip(starts.tolist(), ends.tolist()):
            label = 0
            for pstart, pend, plabel in previous_runs:
                if pstart < end and start < pend:      # runs overlap in columns
                    if label == 0:
                        label = plabel
                    else:
                        union(label, plabel)
            if label == 0:
                label = next_label
                parent.append(label)
                next_label += 1
            labels[y, start:end] = label
            current_runs.append((start, end, label))
        previous_runs = current_runs

    if next_label == 1:
        return labels, {}
    lookup = np.arange(next_label, dtype=np.int32)
    for i in range(1, next_label):
        lookup[i] = find(i)
    labels = lookup[labels]
    uniq, counts = np.unique(labels[labels > 0], return_counts=True)
    return labels, dict(zip(uniq.tolist(), counts.tolist()))


def run_lengths_over_time(cube: np.ndarray) -> np.ndarray:
    """Per-cell longest run of consecutive echoing frames, along axis 0."""
    frames, height, width = cube.shape
    cells = cube.reshape(frames, -1)
    best = np.zeros(cells.shape[1], dtype=np.int16)
    current = np.zeros(cells.shape[1], dtype=np.int16)
    for t in range(frames):
        current = np.where(cells[t], current + 1, 0).astype(np.int16)
        np.maximum(best, current, out=best)
    return best.reshape(height, width)


def describe_box(name: str, codes: np.ndarray, lat: np.ndarray, lon: np.ndarray,
                 nodata: int, echo_min: int, boxes: dict | None = None) -> dict:
    west, east, south, north = (boxes or BOXES)[name]
    cols = np.flatnonzero((lon >= west) & (lon < east))
    rows = np.flatnonzero((lat >= south) & (lat < north))
    cube = codes[:, rows.min():rows.max() + 1, cols.min():cols.max() + 1]

    total = cube.size
    is_nodata = cube == nodata
    is_echo = (cube >= echo_min) & (cube < nodata)
    ever = is_echo.any(axis=0)
    echo_frames_per_cell = is_echo.sum(axis=0)

    out: dict = {
        "box": list(BOXES[name]),
        "cells": int(ever.size),
        "samples": int(total),
        "nodata_pct": float(is_nodata.mean() * 100.0),
        "clear_pct": float((cube == 0).mean() * 100.0),
        "echo_pct": float(is_echo.mean() * 100.0),
        "ever_echo_cells": int(ever.sum()),
        "ever_echo_pct": float(ever.mean() * 100.0),
        "mean_echo_frames_per_echoing_cell": (
            float(echo_frames_per_cell[ever].mean()) if ever.any() else 0.0
        ),
    }

    if not ever.any():
        out.update(blobs=0, blob_pixels_in_large_blobs_pct=0.0, largest_blob_cells=0,
                   isolated_frame_cells_pct=0.0, median_run_frames=0.0,
                   max_run_frames=0, dbz_p50=None, dbz_p90=None, dbz_max=None,
                   frame_iou_mean=0.0)
        return out

    # P2: blob structure, pooled over all frames in the box
    pooled_sizes: list[int] = []
    for t in range(is_echo.shape[0]):
        _, s = component_labels(is_echo[t])
        pooled_sizes.extend(s.values())
    pooled = np.array(pooled_sizes, dtype=np.int64)
    pixels = int(is_echo.sum())
    out["blobs"] = int(pooled.size)
    out["blob_pixels_in_large_blobs_pct"] = (
        float(pooled[pooled >= BLOB_MIN_CELLS].sum() / pixels * 100.0) if pixels else 0.0
    )
    out["largest_blob_cells"] = int(pooled.max())
    out["median_blob_cells"] = float(np.median(pooled))

    # P3: temporal persistence
    per_cell = echo_frames_per_cell[ever]
    run = run_lengths_over_time(is_echo)[ever]
    out["isolated_frame_cells_pct"] = float((per_cell == 1).mean() * 100.0)
    out["median_run_frames"] = float(np.median(run))
    out["max_run_frames"] = int(run.max())

    ious = []
    for t in range(is_echo.shape[0] - 1):
        a, b = is_echo[t], is_echo[t + 1]
        union = int((a | b).sum())
        if union:
            ious.append(float((a & b).sum()) / union)
    out["frame_iou_mean"] = float(np.mean(ious)) if ious else 0.0

    # P4: echo level
    echo_values = cube[is_echo].astype(np.float64)
    out["dbz_p50"] = float(np.percentile(echo_values, 50))
    out["dbz_p90"] = float(np.percentile(echo_values, 90))
    out["dbz_max"] = float(echo_values.max())
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", metavar="PATH", help="write the measurement as JSON")
    ap.add_argument("--subject", default=DEFAULT_SUBJECT,
                    help=f"box under test (default {DEFAULT_SUBJECT})")
    ap.add_argument("--box", action="append", default=[], metavar="NAME:W,E,S,N",
                    help="add or replace a box, e.g. ocean:85,92,15,20 (repeatable)")
    args = ap.parse_args()

    boxes = dict(BOXES)
    for spec in args.box:
        name, _, coords = spec.partition(":")
        try:
            boxes[name] = tuple(float(x) for x in coords.split(","))
        except Exception:
            ap.error(f"--box {spec!r}: expected NAME:W,E,S,N")
        if len(boxes[name]) != 4:
            ap.error(f"--box {spec!r}: expected 4 coordinates")
    if args.subject not in boxes:
        ap.error(f"--subject {args.subject!r} is not one of {sorted(boxes)}")

    raw, scaled, item = open_latest()
    codes = np.asarray(raw["cref"].values)
    times = np.asarray(raw["time"].values)
    lat = np.asarray(raw["latitude"].values)
    lon = np.asarray(raw["longitude"].values)

    variable = raw["cref"].attrs["xue"]["variable"]
    quant = variable["quantization"]
    nodata = int(quant["nodataCode"])
    echo_min = int(quant["minimumCode"]) + 1
    scale = float(quant["scale"])

    print(f"store      {item['id']}")
    print(f"window     {item['properties']['start_datetime']} .. "
          f"{item['properties']['end_datetime']}")
    print(f"grid       {codes.shape[2]}x{codes.shape[1]}, {len(times)} frames, "
          f"lon {lon.min():.3f}..{lon.max():.3f}, lat {lat.min():.3f}..{lat.max():.3f}")
    print(f"codebook   min {quant['minimumCode']} max {quant['maximumCode']} "
          f"nodata {nodata} scale {scale} dBZ/code")

    # ---- P1: is the nodata code ever written? ---------------------------------
    nodata_count = int((codes == nodata).sum())
    observed_max = int(codes.max())
    uniq = np.unique(codes)
    print()
    print("P1  in-band absence marker")
    print(f"    observed code range {int(uniq.min())}..{observed_max} "
          f"({uniq.size} distinct codes)")
    print(f"    nodata code {nodata} written {nodata_count} times "
          f"out of {codes.size} samples")
    p1 = nodata_count > 0
    print(f"    {'PASS' if p1 else 'FAIL'} - absence is "
          f"{'marked in-band' if p1 else 'NOT marked in-band; code 0 is overloaded'}")

    # ---- per box --------------------------------------------------------------
    results = {name: describe_box(name, codes, lat, lon, nodata, echo_min, boxes)
               for name in boxes}

    print()
    header = (f"{'box':<26}{'nodata%':>8}{'clear%':>8}{'echo%':>8}"
              f"{'ever%':>8}{'frames':>8}{'blobs':>7}{'big%':>7}"
              f"{'iso%':>7}{'run':>6}{'IoU':>7}{'p90dBZ':>8}")
    print(header)
    print("-" * len(header))
    for name, r in results.items():
        print(f"{name:<26}{r['nodata_pct']:>8.2f}{r['clear_pct']:>8.2f}"
              f"{r['echo_pct']:>8.3f}{r['ever_echo_pct']:>8.2f}"
              f"{r['mean_echo_frames_per_echoing_cell']:>8.2f}"
              f"{r['blobs']:>7}{r['blob_pixels_in_large_blobs_pct']:>7.1f}"
              f"{r['isolated_frame_cells_pct']:>7.1f}"
              f"{r['median_run_frames']:>6.1f}{r['frame_iou_mean']:>7.3f}"
              f"{(r['dbz_p90'] or 0):>8.1f}")
    print()
    print("    nodata%  samples carrying the nodata code")
    print("    echo%    samples above the minimum code (any frame)")
    print("    ever%    cells echoing in at least one of the frames")
    print("    frames   mean echoing-frame count, over cells that ever echo")
    print(f"    big%     share of echo pixels inside blobs >= {BLOB_MIN_CELLS} cells")
    print("    iso%     share of echoing cells that echo in exactly one frame")
    print("    run      median longest consecutive-frame run, per echoing cell")
    print("    IoU      mean consecutive-frame overlap of the echo mask")

    controls = [results[n] for n in boxes if n != args.subject]
    subject = results[args.subject]
    echoing = [c for c in controls if c["ever_echo_cells"] > 0]
    ctrl_big = max((c["blob_pixels_in_large_blobs_pct"] for c in echoing), default=0.0)
    ctrl_iso = min((c["isolated_frame_cells_pct"] for c in echoing), default=0.0)

    print()
    print("P2  echo forms contiguous blobs (a weather system, not speckle)")
    print(f"    {args.subject} {subject['blob_pixels_in_large_blobs_pct']:.1f}% of echo pixels "
          f"in blobs >= {BLOB_MIN_CELLS} cells; controls reach {ctrl_big:.1f}%")
    p2 = subject["blob_pixels_in_large_blobs_pct"] >= 50.0 and subject["ever_echo_cells"] > 0
    print(f"    {'PASS' if p2 else 'FAIL'} - {args.subject} echo is "
          f"{'coherent' if p2 else 'speckle-like'}")

    print()
    print("P3  echo persists across 6-minute frames")
    print(f"    {args.subject} {subject['isolated_frame_cells_pct']:.1f}% of echoing cells "
          f"are single-frame; controls bottom out at {ctrl_iso:.1f}%; "
          f"median run {subject['median_run_frames']:.1f} frames, "
          f"frame IoU {subject['frame_iou_mean']:.3f}")
    p3 = subject["isolated_frame_cells_pct"] <= ctrl_iso * 2.0 and subject["ever_echo_cells"] > 0
    print(f"    {'PASS' if p3 else 'FAIL'} - {args.subject} echo is "
          f"{'persistent' if p3 else 'transient/flickering'}")

    print()
    print("P4  echo reaches convective levels")
    print(f"    {args.subject} p50 {subject['dbz_p50']} dBZ, p90 {subject['dbz_p90']} dBZ, "
          f"max {subject['dbz_max']} dBZ")
    p4 = (subject["dbz_p90"] or 0) >= 25.0 and subject["ever_echo_cells"] > 0
    print(f"    {'PASS' if p4 else 'FAIL'} - echo level is "
          f"{'precipitation-like' if p4 else 'weak/speckle-like'}")

    print()
    print("VERDICT")
    if not p1:
        print("  code 0 is overloaded: it means both 'no echo' and 'no radar'.")
    if p2 and p3 and p4:
        print(f"  the echo present in {args.subject} behaves like real precipitation:")
        print("  coherent in space, persistent in time, convective in level.  A low echo")
        print("  fraction there is therefore a measurement, not a coverage artefact.")
    else:
        print(f"  the echo present in {args.subject} behaves like speckle: not coherent in")
        print("  space, not persistent in time, not convective in level.  Combined with P1,")
        print("  a low echo fraction there cannot be read as 'no rain' -- the product does")
        print("  not distinguish that from 'no radar coverage'.")

    said = {"store": item["id"], "window": [item["properties"]["start_datetime"],
                                           item["properties"]["end_datetime"]],
            "shape": list(codes.shape), "frames": int(len(times)),
            "nodata_code": nodata, "nodata_written": nodata_count,
            "observed_code_max": observed_max,
            "P1_absence_marked_in_band": bool(p1),
            "P2_echo_is_coherent": bool(p2),
            "P3_echo_is_persistent": bool(p3),
            "P4_echo_is_convective": bool(p4),
            "subject": args.subject, "boxes": results}
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(said, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
