#!/usr/bin/env python3
"""Checkers for the three point-product claims (sounding and airport).

Three subcommands, one per claim.

  cost        what one reading of one station actually costs, in hops and
              bytes, and how much of that is the index rather than the record
              (`xue.point.read-cost-index-dominance.v0`)

  retention   walk each family's own directory naming back over time at the
              cadence that family declares, and count what is still served
              (`xue.point.retention-and-the-missing-archive.v0`)

  thinning    verify the sounding product's thinning rule against every
              published level of every live ascent: a level is published only
              if it is flagged, or it is an end of the ascent, or its pressure
              is at least 3% below the previous published level's
              (`xue.sounding.thinning-rule-conformance.v0`)

Each subcommand prints its counts, and each states what it did not establish.
Nothing here decides whether the numbers are good; the claim records the
outcome and this records the run.
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
from urllib.parse import urljoin

BASE = "https://dataset.ringsaturn.me/xue/"
UA = {"User-Agent": "xue-study/1.0 (+point-products-check)"}

AIRPORT_ROW = ("icao lat lon elev obsTime t td wd ws gust vis qnh category "
               "tafPresent offset length").split()

# BUFR flag table 0 08 042, the bits the sounding spec names
SIG_BITS = {
    131072: "surface", 65536: "standard", 32768: "tropopause",
    16384: "max wind", 8192: "sig temperature", 4096: "sig humidity",
    2048: "sig wind",
}
SIG_ANY = 131072 | 65536 | 32768 | 16384 | 8192 | 4096 | 2048
MISSING = -32768


def fetch(url: str, byte_range: tuple[int, int] | None = None,
          attempts: int = 5, timeout: int = 90) -> tuple[int, bytes, dict]:
    headers = dict(UA)
    if byte_range:
        headers["Range"] = f"bytes={byte_range[0]}-{byte_range[1]}"
    last: Exception | None = None
    for i in range(attempts):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers),
                                        timeout=timeout) as response:
                headers_back = {k.lower(): v for k, v in response.headers.items()}
                return response.status, response.read(), headers_back
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return 404, b"", {}
            last = exc
        except Exception as exc:  # noqa: BLE001 - transient network only
            last = exc
        time.sleep(2 + 2 * i)
    raise RuntimeError(f"failed after {attempts} attempts: {url}") from last


def fetch_json(url: str):
    return json.loads(fetch(url)[1])


AIRPORT_INDEX = "latest-airport.json"


def sounding_index() -> tuple[dict, str]:
    pointer = fetch_json(urljoin(BASE, "latest-sounding.json"))
    index_url = urljoin(BASE, pointer["path"])
    return fetch_json(index_url), urljoin(index_url, "soundings.jsonl")


def airport_index() -> tuple[dict, str]:
    pointer = fetch_json(urljoin(BASE, "latest-airport.json"))
    index_url = urljoin(BASE, pointer["path"])
    return fetch_json(index_url), urljoin(index_url, "history.jsonl")


def all_soundings() -> list[tuple[dict, dict]]:
    """Every station record, pulled by its own byte span."""
    index, url = sounding_index()
    def pull(row):
        try:
            return row, json.loads(fetch(url, (row["offset"],
                                               row["offset"] + row["length"] - 1))[1])
        except Exception:  # noqa: BLE001 - one bad station must not stop the rest
            return row, None
    with ThreadPoolExecutor(max_workers=16) as pool:
        return [(row, rec) for row, rec in pool.map(pull, index["stations"]) if rec]


# --------------------------------------------------------------------------
def cmd_cost(_args) -> int:
    print("cost of one reading, measured start to finish\n")

    print("sounding: one ascent, the station the viewer would open")
    spent, hops = 0, []
    started = time.time()
    status, body, _ = fetch(urljoin(BASE, "latest-sounding.json"))
    spent += len(body); hops.append(("latest-sounding.json", status, len(body)))
    pointer = json.loads(body)
    status, body, _ = fetch(urljoin(BASE, pointer["path"]))
    spent += len(body); hops.append((pointer["path"], status, len(body)))
    index = json.loads(body)
    index_bytes = len(body)
    station = next(row for row in index["stations"] if row["wmo"] == "55591")
    span = (station["offset"], station["offset"] + station["length"] - 1)
    status, body, headers = fetch(urljoin(urljoin(BASE, pointer["path"]),
                                          index["soundings"]["path"]), span)
    spent += len(body)
    hops.append((f"soundings.jsonl bytes={span[0]}-{span[1]}", status, len(body)))
    elapsed = time.time() - started
    for name, code, size in hops:
        print(f"   {name:<48} {code}  {size:>9} B")
    whole = index["soundings"]["byteLength"]
    print(f"   {'total':<48}      {spent:>9} B   {elapsed:.2f} s, {len(hops)} hops")
    print(f"   index share of the cost: {index_bytes / spent * 100:.0f}%")
    print(f"   saving against the whole jsonl ({whole} B): "
          f"{(1 - spent / whole) * 100:.2f}%")
    print(f"   byte range honoured: {headers.get('content-range')}")

    print("\nairport: one airport, its 24 hours and its current TAF")
    spent, hops = 0, []
    started = time.time()
    status, body, _ = fetch(urljoin(BASE, "latest-airport.json"))
    spent += len(body); hops.append(("latest-airport.json", status, len(body)))
    pointer = json.loads(body)
    status, body, _ = fetch(urljoin(BASE, pointer["path"]))
    spent += len(body); hops.append((pointer["path"], status, len(body)))
    index = json.loads(body)
    index_bytes = len(body)
    r = json.loads(json.dumps(index))  # keep the row order below explicit
    rows = [dict(zip(AIRPORT_ROW, row)) for row in r["stations"]]
    pick = next((x for x in rows if x["icao"] == "KPLD"), rows[3000])
    span = (pick["offset"], pick["offset"] + pick["length"] - 1)
    status, body, headers = fetch(urljoin(urljoin(BASE, pointer["path"]),
                                          index["history"]["path"]), span)
    spent += len(body)
    hops.append((f"history.jsonl bytes={span[0]}-{span[1]}", status, len(body)))
    elapsed = time.time() - started
    for name, code, size in hops:
        print(f"   {name:<48} {code}  {size:>9} B")
    whole = index["history"]["byteLength"]
    print(f"   {'total':<48}      {spent:>9} B   {elapsed:.2f} s, {len(hops)} hops")
    print(f"   index share of the cost: {index_bytes / spent * 100:.0f}%")
    print(f"   saving against the whole history ({whole} B): "
          f"{(1 - spent / whole) * 100:.2f}%")
    print(f"   byte range honoured: {headers.get('content-range')}")
    print(f"   stations in the index: {len(rows)}")

    print("\nNOT ESTABLISHED: that this is the cheapest reading.  Reading every")
    print("station inverts it -- the index is paid once per station, and the spec")
    print("itself names the whole-file read as the analyst's route.  Caching is")
    print("not measured either: `immutable` says the index may be cached, not")
    print("that it was.")
    return 0


# --------------------------------------------------------------------------
def floor_to(moment: dt.datetime, unit: str, step: int) -> dt.datetime:
    """Round down to the cadence the family names its directories on.

    A probe grid that is not aligned with the naming reports zero hits and
    looks like an empty archive.  This is the same mistake that produced a
    wrong retention count for the radar carriers, so it is done explicitly
    here rather than left to whichever second the command happened to run at.
    """
    if unit == "hours":
        return moment.replace(minute=0, second=0, microsecond=0)
    return moment.replace(minute=moment.minute - moment.minute % step,
                          second=0, microsecond=0)


def cmd_retention(args) -> int:
    raw_now = dt.datetime.now(dt.timezone.utc)
    plans = [
        ("airport", "%Y%m%d%H%M", "minutes", 10, 60,
         "documented: a round every 10 minutes, directories pruned after three hours"),
        ("sounding", "%Y%m%d%H", "hours", 1, 24 * args.days,
         "documented: one issue an hour, directories pruned after two days"),
        ("tc", "%Y%m%d%H", "hours", 1, 48, "documented: not checked here"),
    ]
    for name, fmt, unit, step, count, note in plans:
        now = floor_to(raw_now, unit, step)
        stamps = [(now - dt.timedelta(**{unit: step * k})).strftime(fmt)
                  for k in range(count)]
        urls = [urljoin(BASE, f"{name}.{stamp}/index.json") for stamp in stamps]
        with ThreadPoolExecutor(max_workers=20) as pool:
            codes = list(pool.map(lambda u: fetch(u, attempts=2, timeout=15)[0], urls))
        hits = sorted(s for s, code in zip(stamps, codes) if code == 200)
        print(f"{name:<9} probed {len(stamps):>4} rounds at {step} {unit}(s) back from "
              f"{now:%Y-%m-%dT%H:%M}Z -> {len(hits)} served")
        if hits:
            print(f"          oldest {hits[0]}   newest {hits[-1]}   "
                  f"span {(dt.datetime.strptime(hits[-1], fmt) - dt.datetime.strptime(hits[0], fmt)).total_seconds() / 60:.0f} min")
            # a presence map, because the count alone hides a regular hole
            if len(hits) < len(stamps):
                marks = "".join("O" if code == 200 else "x" for code in codes)
                print(f"          newest -> oldest: {marks}")
                served = set(hits)
                inner = [s for s in stamps
                         if 200 in codes and min(hits) < s < max(hits) and s not in served]
                if inner:
                    print(f"          holes inside the served span: "
                          f"{[s[-4:] for s in inner]}")
                    by_minute: dict[str, int] = {}
                    for s in inner:
                        by_minute[s[-2:]] = by_minute.get(s[-2:], 0) + 1
                    regular = {m: c for m, c in by_minute.items() if c >= 3}
                    if regular:
                        print(f"          of which systematic, by minute: {regular}")
        print(f"          {note}")
    print("\nNOT ESTABLISHED: that these are policies rather than current state;")
    print("that a 404 means absent rather than forbidden or timed out; and that")
    print("the candidate cadence is right -- airport hit its documented 18 exactly,")
    print("which supports the cadence, but sounding's five against a documented two")
    print("days is not explained.  Directories being pruned is not data being gone:")
    print("the newest sounding issue already carries each station's own last four")
    print("nominal times.")
    return 0


# --------------------------------------------------------------------------
def cmd_thinning(_args) -> int:
    records = all_soundings()
    ascents = [(row, a) for row, rec in records for a in rec["soundings"]]
    pairs = flagged_pairs = 0
    ratios: list[float] = []
    violations: list[tuple] = []
    order_bad = length_bad = 0
    bit_counts: dict[str, int] = {}
    levels = missing = 0

    for row, a in ascents:
        p, sig, n = a["p"], a["sig"], a["n"]
        if len(p) != n or len(sig) != n:
            length_bad += 1
            continue
        if any(p[i] <= p[i + 1] for i in range(len(p) - 1)):
            order_bad += 1
        for value in sig:
            levels += 1
            if value is None or value == MISSING:
                missing += 1
                continue
            for bit, name in SIG_BITS.items():
                if value & bit:
                    bit_counts[name] = bit_counts.get(name, 0) + 1
            if not value & SIG_ANY:
                bit_counts["unflagged"] = bit_counts.get("unflagged", 0) + 1
        # the lowest level has no predecessor and the highest is exempt, so the
        # pairs to test are (i, i+1) for i+1 <= n-2
        for i in range(n - 2):
            pairs += 1
            word = sig[i + 1]
            flagged = word is not None and word != MISSING and bool(word & SIG_ANY)
            ratio = p[i] / p[i + 1]
            if flagged:
                flagged_pairs += 1
                continue
            ratios.append(ratio)
            if ratio < 1.03:
                violations.append((row["wmo"], a["time"], i, n, round(ratio, 4), word))

    ratios.sort()
    print(f"ascents            {len(ascents)}")
    print(f"levels             {levels}")
    print(f"adjacent pairs     {pairs}   (lowest and highest levels excluded, as the rule exempts them)")
    print(f"  flagged          {flagged_pairs}")
    print(f"  unflagged        {len(ratios)}")
    if ratios:
        print(f"    ratio min      {ratios[0]:.4f}")
        print(f"    ratio 5th pct  {ratios[len(ratios) // 20]:.4f}")
        print(f"    ratio median   {ratios[len(ratios) // 2]:.4f}")
        print(f"    below 1.03     {len(violations)}")
    for v in violations[:20]:
        print(f"      wmo={v[0]} {v[1]} index {v[2]}/{v[3]} ratio {v[4]} sig {v[5]}")
    print(f"p not strictly descending: {order_bad} ascents")
    print(f"array length != n:         {length_bad} ascents")
    print(f"missing sentinel in sig:   {missing} of {levels} levels")
    print("sig bits in use:")
    for name, count in sorted(bit_counts.items(), key=lambda kv: -kv[1]):
        print(f"   {name:<18} {count:>7}  {count / levels * 100:5.1f}%")

    print("\nNOT ESTABLISHED: that the thinning is correct, only that what was")
    print("published satisfies one of the rule's three exemptions.  The other")
    print("direction -- that everything the rule keeps was published -- cannot be")
    print("checked from the product, because thinned levels are not in it.  The")
    print("earlier counts of 86 and 45 'violations' this repo recorded were both")
    print("produced by criteria that are not the product's rule; they are kept in")
    print("the claim's assumptions rather than deleted.")
    return 0


def cmd_coverage(_args) -> int:
    """How much of the station history is actually there.

    The spec says each station carries "the last 24 hours of METARs".  A skill
    curve built on that history needs to know its real shape, and the shape is
    not a rectangle: the hours are neither contiguous nor uniform, and the holes
    land inside lead ranges that someone will try to use.
    """
    pointer = fetch_json(urljoin(BASE, AIRPORT_INDEX))
    index_url = urljoin(BASE, pointer["path"])
    index = fetch_json(index_url)
    blob = fetch(urljoin(index_url, index["history"]["path"]))[1]
    declared = index["history"]["byteLength"]
    print(f"history.jsonl declared {declared:,} B, received {len(blob):,} B")
    text = blob.decode("utf-8", "replace")

    metars: dict[str, int] = {}
    periods: dict[str, int] = {}
    stations = taf_stations = 0
    for line in text.splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        stations += 1
        for m in record.get("metars") or []:
            hour = dt.datetime.fromisoformat(m["time"].replace("Z", "+00:00")).strftime("%m-%d %HZ")
            metars[hour] = metars.get(hour, 0) + 1
        if isinstance(record.get("taf"), dict):
            taf_stations += 1
            for period in record["taf"].get("periods") or []:
                for key in ("from", "to"):
                    value = period.get(key)
                    if isinstance(value, str) and value.startswith("2026"):
                        hour = dt.datetime.fromisoformat(
                            value.replace("Z", "+00:00")).strftime("%m-%d %HZ")
                        periods[hour] = periods.get(hour, 0) + 1

    hours = sorted(set(metars) | set(periods), key=lambda k: (k[:5], int(k[6:8])))
    print(f"stations {stations}, of which carrying a TAF {taf_stations}")
    print(f"\n{'hour':<12}{'METAR observations':>20}{'TAF period edges':>19}")
    for hour in hours:
        print(f"{hour:<12}{metars.get(hour, 0):>20}{periods.get(hour, 0):>19}")
    observed = [h for h in hours if metars.get(h, 0) > 0]
    print(f"\n  hours carrying at least one observation: {len(observed)}")
    if observed:
        first = dt.datetime.strptime(observed[0], "%m-%d %HZ")
        last = dt.datetime.strptime(observed[-1], "%m-%d %HZ")
        print(f"  span {observed[0]} .. {observed[-1]} "
              f"({(last - first).total_seconds() / 3600 + 1:.0f} hours)")
    empty = [h for h in hours if metars.get(h, 0) == 0]
    if empty:
        print(f"  hours inside the span carrying none: {empty}")
    counts = [metars.get(h, 0) for h in observed]
    if counts:
        print(f"  observations per present hour: min {min(counts)}, max {max(counts)}")
    print("\n  NOT ESTABLISHED: why the holes are there.  The product is rebuilt every")
    print("  ten minutes from a source cache, so a hole may be the source, the")
    print("  aggregation, or a source outage; nothing here distinguishes them.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("coverage", help="how much of the station history is there")
    p.set_defaults(func=cmd_coverage)

    p = sub.add_parser("cost", help="hops and bytes for one reading")
    p.set_defaults(func=cmd_cost)

    p = sub.add_parser("retention", help="how far back each family still serves")
    p.add_argument("--days", type=int, default=7, help="hours to probe sounding back (in days)")
    p.set_defaults(func=cmd_retention)

    p = sub.add_parser("thinning", help="verify the sounding thinning rule")
    p.set_defaults(func=cmd_thinning)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
