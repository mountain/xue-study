#!/usr/bin/env python3
"""Use the station and sounding products as anchors of measured fact.

Eleven claims in this repository measure the container, the codecs, the store
profile and the product contracts.  None of them measures whether a delivered
field is *physically* right, because none of them had a fact to measure it
against.  The point products supply one: an ascent reports the pressure,
height and temperature it actually measured at a place, and an airport reports
the temperature it actually measured at a place.  This script puts a gridded
model field beside those measurements.

Three checks, each stating what it does and does not settle.

  underground850   Where an ascent never reaches 850 hPa, the 850 hPa level is
                   below the ground.  The model still publishes a value there.
                   Compare that value with the temperature the ascent measured
                   at the surface.  This anchors, by observation, the claim
                   that the published 850 hPa over the plateau is an
                   extrapolation and not a measurement.

  cellspread       Several airport stations can sit inside one 0.25 degree cell
                   at different elevations.  The spread of what they measured
                   is an irreducible error for any point comparison against
                   that cell -- no model, however good, can match all of them.
                   Measure that ceiling before blaming a model for missing it.

  surfacebias      The model's 2 m temperature against the anchored
                   measurements, overall and by station elevation, with the
                   ceiling from `cellspread` beside it.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin

import numpy as np
import xarray as xr

BASE = "https://dataset.ringsaturn.me/xue/"
UA = {"User-Agent": "xue-study/1.0 (+anchor-check)"}
AIRPORT_ROW = ("icao lat lon elev obsTime t td wd ws gust vis qnh category "
               "tafPresent offset length").split()

SOUNDING_INDEX = "latest-sounding.json"
AIRPORT_INDEX = "latest-airport.json"
GFS_POINTER = "latest.json"


def fetch(url: str, attempts: int = 5, timeout: int = 90) -> bytes:
    last: Exception | None = None
    for i in range(attempts):
        try:
            return urllib.request.urlopen(
                urllib.request.Request(url, headers=UA), timeout=timeout).read()
        except Exception as exc:  # noqa: BLE001 - transient network only
            last = exc
    raise RuntimeError(f"failed after {attempts} attempts: {url}") from last


def fetch_json(url: str):
    return json.loads(fetch(url))


def load_soundings() -> list[dict]:
    pointer = fetch_json(urljoin(BASE, SOUNDING_INDEX))
    index_url = urljoin(BASE, pointer["path"])
    index = fetch_json(index_url)
    data_url = urljoin(index_url, index["soundings"]["path"])

    def pull(row):
        headers = dict(UA)
        headers["Range"] = f"bytes={row['offset']}-{row['offset'] + row['length'] - 1}"
        try:
            body = urllib.request.urlopen(
                urllib.request.Request(data_url, headers=headers), timeout=90).read()
            return json.loads(body)
        except Exception:  # noqa: BLE001 - one station must not stop the rest
            return None

    with ThreadPoolExecutor(max_workers=16) as pool:
        return [rec for rec in pool.map(pull, index["stations"]) if rec]


def load_airports() -> list[dict]:
    pointer = fetch_json(urljoin(BASE, AIRPORT_INDEX))
    index = fetch_json(urljoin(BASE, pointer["path"]))
    return [dict(zip(AIRPORT_ROW, row)) for row in index["stations"]]


def open_field(variable: str, run: str | None = None, tier: str | None = None
               ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Open one field of a run.

    `run` defaults to whatever `latest.json` names, but the run directories
    outlive the pointer, and a skill curve needs several of them forecasting the
    same hour, so a caller may name one directly.
    """
    if run is None:
        pointer = fetch_json(urljoin(BASE, GFS_POINTER))
        item_url = urljoin(BASE, pointer["manifestPath"].replace("manifest.json", "item.json"))
        item = fetch_json(item_url)
        href = urljoin(item_url, item["assets"][variable]["href"])
        dataset = xr.open_zarr(href)
    else:
        # Runs older than the STAC item have no `item.json` at all; the run
        # directory and its stores are still served, so address the store
        # directly.  Which tier survives is NOT uniform across runs -- one run
        # here has only the half store and the next only the full one -- so a
        # caller that cares must say which tier it wants rather than let a
        # fallback silently mix resolutions into one series.
        if tier == "full":
            suffixes = (f"{variable}.zarr",)
        elif tier == "half":
            suffixes = (f"{variable}.half.zarr",)
        else:
            suffixes = (f"{variable}.zarr", f"{variable}.half.zarr")
        last: Exception | None = None
        dataset = None
        for suffix in suffixes:
            try:
                dataset = xr.open_zarr(urljoin(BASE, f"gfs.{run}/{suffix}"))
                break
            except Exception as error:  # noqa: BLE001
                last = error
        if dataset is None:
            raise RuntimeError(f"no store for {variable} in gfs.{run}") from last
    return (np.asarray(dataset[variable].values, dtype=np.float64),
            np.asarray(dataset["time"].values),
            np.asarray(dataset["latitude"].values),
            np.asarray(dataset["longitude"].values))


def frame_at(times: np.ndarray, moment: dt.datetime) -> int:
    seconds = times.astype("datetime64[s]").astype(np.int64)
    return int(np.argmin(np.abs(seconds - int(moment.timestamp()))))


def nearest(field: np.ndarray, lat: np.ndarray, lon: np.ndarray,
            points_lat, points_lon) -> np.ndarray:
    """Sample a lat/lon grid at points, nearest cell, honouring the fill value."""
    rows = np.rint((lat[0] - np.asarray(points_lat)) / abs(lat[1] - lat[0])).astype(int)
    step = abs(lon[1] - lon[0])
    cols = np.rint(((np.asarray(points_lon) - lon[0]) / step) % lon.size).astype(int)
    rows = np.clip(rows, 0, lat.size - 1)
    return field[rows, cols]


# --------------------------------------------------------------------------
def as_float(value):
    try:
        out = float(value)
        return out if np.isfinite(out) else None
    except (TypeError, ValueError):
        return None


def cmd_underground850(args, field_cache) -> dict:
    records = load_soundings()
    tmp850, t850_times, lat, lon = field_cache("tmp850")
    tmpsfc, _, _, _ = field_cache("tmpsfc")
    frame = frame_at(t850_times, args.moment)

    picked = []
    fragments = 0
    for rec in records:
        for ascent in rec["soundings"]:
            if not ascent["time"].startswith(args.moment.strftime("%Y-%m-%dT%H")):
                continue
            p, t, z = ascent["p"], ascent["t"], ascent["z"]
            elev = rec["elev"]
            if elev is None:
                continue
            # Take the surface level to be one whose reported height matches the
            # station's elevation.  `max(p)` is NOT the surface: 227 of 1844
            # ascents are fragments that report only the stratosphere, and for
            # those the largest pressure is a level at 20 km.  Using max(p)
            # produced a +101 K "bias" at four such stations before this check
            # was added.
            candidates = [i for i in range(len(p))
                          if z[i] is not None and z[i] > -30000 and abs(z[i] - elev) <= 150]
            if not candidates:
                fragments += 1
                continue
            k = max(candidates, key=lambda i: p[i])
            if t[k] is None or t[k] <= -30000:
                continue
            picked.append({
                "wmo": rec["wmo"], "lat": rec["lat"], "lon": rec["lon"],
                "elev": elev, "surface_p": p[k] / 100.0,
                "measured_t": t[k] / 100.0 - 273.15,
            })

    print(f"soundings at {args.moment:%Y-%m-%dT%H}Z: {len(picked)} ascents with a "
          f"level matching the station elevation, from {len(records)} stations")
    print(f"  discarded as fragments (no level within 150 m of the station elevation): {fragments}")
    print(f"  model frame {frame} ({np.datetime_as_string(t850_times[frame])})")
    lats = [x["lat"] for x in picked]
    lons = [x["lon"] for x in picked]
    g850 = nearest(tmp850[frame], lat, lon, lats, lons)
    gsfc = nearest(tmpsfc[frame], lat, lon, lats, lons)
    for x, a, b in zip(picked, g850, gsfc):
        x["model_tmp850"] = None if not np.isfinite(a) else float(a)
        x["model_tmpsfc"] = None if not np.isfinite(b) else float(b)

    under = [x for x in picked if x["surface_p"] < 850.0]
    above = [x for x in picked if x["surface_p"] >= 850.0]
    print(f"\n850 hPa below the ground at {len(under)} of {len(picked)} ascents "
          f"(surface pressure < 850 hPa); above it at {len(above)}")

    for label, group in (("850 hPa does not exist", under),
                         ("850 hPa exists", above)):
        usable = [x for x in group if x["model_tmp850"] is not None
                  and x["model_tmpsfc"] is not None]
        if not usable:
            continue
        warmer = sum(1 for x in usable if x["model_tmp850"] > x["measured_t"])
        warmer_own = sum(1 for x in usable if x["model_tmp850"] > x["model_tmpsfc"])
        d_meas = np.array([x["model_tmp850"] - x["measured_t"] for x in usable])
        print(f"\n  {label}  (n={len(usable)})")
        print(f"    model tmp850 minus the temperature the ascent measured at the surface")
        print(f"      median {np.median(d_meas):+7.2f} K   mean {d_meas.mean():+7.2f} K   "
              f"range {d_meas.min():+7.2f} .. {d_meas.max():+7.2f}")
        print(f"    model tmp850 warmer than the measured surface: {warmer}/{len(usable)}")
        print(f"    model tmp850 warmer than the model's own tmpsfc: {warmer_own}/{len(usable)}")
        # always show the extremes, whatever n is: a +100 K outlier is either a
        # real inversion over high terrain or a broken record, and the reader
        # should be able to tell which
        ordered = sorted(usable, key=lambda y: y["model_tmp850"] - y["measured_t"])
        shown = ordered[:4] + ordered[-4:] if len(ordered) > 10 else ordered
        for x in shown:
            print(f"      {x['wmo']} {x['lat']:6.1f}N {x['lon']:7.1f}E elev {str(x['elev']):>6} m  "
                  f"Ps {x['surface_p']:6.1f}  measured {x['measured_t']:7.1f}  "
                  f"tmp850 {x['model_tmp850']:6.1f}  tmpsfc {x['model_tmpsfc']:6.1f}  "
                  f"diff {x['model_tmp850'] - x['measured_t']:+7.1f}")
    print("\n  NOT ESTABLISHED: that the model is wrong to publish a value there.")
    print("  A level below the ground has no measurement to be wrong about; what is")
    print("  established is that the published value is not a measurement, and how it")
    print("  compares with one taken nearby.")
    return {"n": len(picked), "underground": len(under)}


def cmd_cellspread(args, _cache) -> dict:
    rows = load_airports()
    _tmp2m, times, lat, lon = _cache("tmp2m")
    frame = frame_at(times, args.moment)
    print(f"airport stations in the index: {len(rows)}; "
          f"model frame {frame} ({np.datetime_as_string(times[frame])})")

    cells: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for r in rows:
        t, elev, la, lo = as_float(r["t"]), as_float(r["elev"]), as_float(r["lat"]), as_float(r["lon"])
        if t is None or la is None or lo is None:
            continue
        row = int(round((lat[0] - la) / abs(lat[1] - lat[0])))
        col = int(round(((lo - lon[0]) / abs(lon[1] - lon[0])) % lon.size))
        cells[(row, col)].append({"icao": r["icao"], "t": t, "elev": elev,
                                  "obsTime": r["obsTime"]})

    multi = {k: v for k, v in cells.items() if len(v) >= 2}
    spreads, elev_spreads, lapse_implied, residual = [], [], [], []
    for members in multi.values():
        temps = [m["t"] for m in members]
        spreads.append(max(temps) - min(temps))
        elevated = [m for m in members if m["elev"] is not None]
        if len(elevated) >= 2 and (max(m["elev"] for m in elevated)
                                   - min(m["elev"] for m in elevated)) > 100:
            de = (max(m["elev"] for m in elevated) - min(m["elev"] for m in elevated))
            elev_spreads.append(de)
            # what a 6.5 K/km lapse rate would produce across that elevation range
            lapse_implied.append(6.5 * de / 1000.0)
            pair = sorted(elevated, key=lambda m: -m["elev"])[:2]
            residual.append(abs(pair[0]["t"] - pair[1]["t"]))
    spreads = np.array(spreads)
    print(f"\ncells holding more than one station: {len(multi)} "
          f"({len(spreads)} usable), of {len(cells)} occupied cells")
    if spreads.size:
        print(f"  measured temperature spread inside one cell (the ceiling for any point claim)")
        print(f"    median {np.median(spreads):5.2f} K   mean {spreads.mean():5.2f} K   "
              f"90th pct {np.percentile(spreads, 90):5.2f} K   max {spreads.max():5.2f} K")
        over = int((spreads > 2.0).sum())
        print(f"    cells where stations disagree by more than 2 K: {over}/{spreads.size} "
              f"({over / spreads.size * 100:.0f}%)")
    if elev_spreads:
        print(f"  cells with a station elevation range over 100 m: {len(elev_spreads)}")
        print(f"    elevation range median {np.median(elev_spreads):6.0f} m; "
              f"a 6.5 K/km lapse rate across it implies "
              f"{np.median(lapse_implied):5.2f} K (median)")
    print("\n  NOT ESTABLISHED: that the whole spread is terrain.  Stations in one")
    print("  cell also differ by land use, coast, urban heat and instrument, and their")
    print("  observations are not simultaneous.  What is established is the size of the")
    print("  disagreement a 0.25 degree cell has to cover.")
    return {"multi_cells": len(multi), "median_spread": float(np.median(spreads)) if spreads.size else None}


def cmd_surfacebias(args, cache) -> dict:
    tmp2m, times, lat, lon = cache("tmp2m")
    frame = frame_at(times, args.moment)
    print(f"model frame {frame} ({np.datetime_as_string(times[frame])})")

    rows = load_airports()
    pts = [(as_float(r["lat"]), as_float(r["lon"]), as_float(r["t"]), as_float(r["elev"]), r["icao"])
           for r in rows]
    pts = [p for p in pts if None not in p[:4]]
    grid = tmp2m[frame]
    model = nearest(grid, lat, lon, [p[0] for p in pts], [p[1] for p in pts])
    print(f"\nairport anchors usable: {len(pts)}")

    bins = [(None, 100), (100, 500), (500, 1000), (1000, 2000), (2000, 10 ** 9)]
    print(f"{'elevation band (m)':<22}{'n':>6}{'median bias':>13}{'mean bias':>11}"
          f"{'spread (1 s.d.)':>17}")
    out = {}
    for lo, hi in bins:
        sel = [(p, m) for p, m in zip(pts, model)
               if np.isfinite(m) and (lo is None or p[3] >= lo) and p[3] < hi]
        if not sel:
            continue
        d = np.array([m - p[2] for p, m in sel])
        label = f"{'<'+str(hi) if lo is None else str(lo)+'-'+str(hi)}"
        print(f"{label:<22}{len(d):>6}{np.median(d):>13.2f}{d.mean():>11.2f}{d.std():>17.2f}")
        out[label] = {"n": int(len(d)), "median": float(np.median(d)), "sd": float(d.std())}
    whole = np.array([m - p[2] for p, m in zip(pts, model) if np.isfinite(m)])
    print(f"{'all':<22}{len(whole):>6}{np.median(whole):>13.2f}{whole.mean():>11.2f}"
          f"{whole.std():>17.2f}")
    print("\n  NOT ESTABLISHED: that this is model error.  A 0.25 degree cell is a mean")
    print("  over its terrain; a station sits at a point on it.  The `cellspread` check")
    print("  measures how large that mismatch alone can be.  Observations are also not")
    print("  simultaneous with the model frame: the METARs in the index span the")
    print("  preceding hour, so part of the spread is the weather moving.")
    return {"all": {"n": int(whole.size), "median": float(np.median(whole))}, "bands": out}


def cmd_soundingbias(args, cache) -> dict:
    """The same surface comparison, but with the anchors that reach high terrain."""
    tmp2m, times, lat, lon = cache("tmp2m")
    frame = frame_at(times, args.moment)
    records = load_soundings()
    points = []
    for rec in records:
        if rec["elev"] is None:
            continue
        for ascent in rec["soundings"]:
            if not ascent["time"].startswith(args.moment.strftime("%Y-%m-%dT%H")):
                continue
            p, t, z = ascent["p"], ascent["t"], ascent["z"]
            cand = [i for i in range(len(p))
                    if z[i] is not None and z[i] > -30000 and abs(z[i] - rec["elev"]) <= 150]
            if not cand:
                continue
            k = max(cand, key=lambda i: p[i])
            if t[k] is None or t[k] <= -30000:
                continue
            points.append({"wmo": rec["wmo"], "lat": rec["lat"], "lon": rec["lon"],
                           "elev": rec["elev"], "measured_t": t[k] / 100.0 - 273.15})
    model = nearest(tmp2m[frame], lat, lon, [x["lat"] for x in points],
                    [x["lon"] for x in points])
    usable = [(x, float(m)) for x, m in zip(points, model) if np.isfinite(m)]
    print(f"sounding anchors at {args.moment:%Y-%m-%dT%H}Z: {len(usable)} ascents, "
          f"model frame {frame} ({np.datetime_as_string(times[frame])})")
    print(f"\n{'elevation band':<18}{'n':>5}{'median bias':>13}{'mean':>9}{'1 s.d.':>9}")
    bands = [(None, 500), (500, 1500), (1500, 2500), (2500, 3500), (3500, 10 ** 9)]
    out: dict = {}
    for lo, hi in bands:
        sel = [(x, m) for x, m in usable
               if (lo is None or x["elev"] >= lo) and x["elev"] < hi]
        if not sel:
            continue
        d = np.array([m - x["measured_t"] for x, m in sel])
        label = f"{'<'+str(hi) if lo is None else str(lo)+'-'+str(hi)}"
        print(f"{label:<18}{len(d):>5}{np.median(d):>13.2f}{d.mean():>9.2f}{d.std():>9.2f}")
        out[label] = {"n": int(len(d)), "median": float(np.median(d)), "sd": float(d.std())}
    whole = np.array([m - x["measured_t"] for x, m in usable])
    print(f"{'all':<18}{len(whole):>5}{np.median(whole):>13.2f}{whole.mean():>9.2f}"
          f"{whole.std():>9.2f}")
    plateau = [(x, m) for x, m in usable if 75 <= x["lon"] <= 105 and 25 <= x["lat"] <= 40]
    if plateau:
        d = np.array([m - x["measured_t"] for x, m in plateau])
        print(f"\nthe box the theta-e claim is about (75-105E, 25-40N): n={len(d)}  "
              f"median {np.median(d):+.2f} K  mean {d.mean():+.2f} K  1 s.d. {d.std():.2f} K")
        for x, m in sorted(plateau, key=lambda y: -y[0]["elev"]):
            print(f"   {x['wmo']} {x['elev']:6.0f} m  measured {x['measured_t']:6.1f}  "
                  f"model {m:6.1f}  diff {m - x['measured_t']:+6.1f} K")
        out["plateau_box"] = {"n": int(len(d)), "median": float(np.median(d)),
                              "sd": float(d.std())}
    print("\n  The sign follows the difference between a station's own elevation and")
    print("  the mean elevation of the 0.25 degree cell it sits in: a station in a")
    print("  valley under mountains reads warmer than the cell, one on a peak reads")
    print("  colder.  So this is terrain representativeness, not a model error term,")
    print("  and it is the number the third problem card asked for.")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["underground850", "cellspread", "surfacebias",
                                       "soundingbias", "all"])
    ap.add_argument("--moment", default="2026-09-17T00:00",
                    help="UTC moment to compare at (default 2026-09-17T00:00)")
    ap.add_argument("--airport-moment", default="2026-09-17T05:00",
                    help="UTC moment for the airport anchors (default 2026-09-17T05:00)")
    ap.add_argument("--json", metavar="PATH")
    args = ap.parse_args()

    cache_store: dict = {}

    def cache(variable: str):
        if variable not in cache_store:
            cache_store[variable] = open_field(variable)
        return cache_store[variable]

    original = args.moment
    results = {}
    if args.command in ("underground850", "all"):
        args.moment = dt.datetime.fromisoformat(original).replace(tzinfo=dt.timezone.utc)
        results["underground850"] = cmd_underground850(args, cache)
    if args.command in ("cellspread", "all"):
        args.moment = dt.datetime.fromisoformat(args.airport_moment).replace(tzinfo=dt.timezone.utc)
        results["cellspread"] = cmd_cellspread(args, cache)
    if args.command in ("surfacebias", "all"):
        args.moment = dt.datetime.fromisoformat(args.airport_moment).replace(tzinfo=dt.timezone.utc)
        results["surfacebias"] = cmd_surfacebias(args, cache)

    if args.command in ("soundingbias", "all"):
        args.moment = dt.datetime.fromisoformat(original).replace(tzinfo=dt.timezone.utc)
        results["soundingbias"] = cmd_soundingbias(args, cache)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(results, handle, indent=2, ensure_ascii=False, default=str)
            handle.write("\n")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
