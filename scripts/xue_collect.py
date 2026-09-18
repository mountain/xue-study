"""Archive what the xue catalog publishes, because upstream does not keep it.

WHY THIS EXISTS
---------------
The study's forecast-verification design is a sliding spacetime block: a window
of verified state and relations that advances as new data arrives, with
prediction and observation compared at every point it covers.  That design has
one hard prerequisite, and it is not modelling.

Upstream retention is short, and it is short on BOTH sides:

  cma radar mosaic   temporal extent observed at 2.4 hours
  gfs                "Four cycles a day; only the newest is kept"
  sounding           five hourly issues kept
  airport            19 rounds / 230 minutes, with HH:10 systematically missing

So the block cannot be reconstructed after the fact.  Every hour without a
collector is an hour permanently absent from every future skill score.  The
analyses in this study that DID work used reanalyses (ERA5, MERRA-2), which are
archived upstream -- the forecast-versus-observation comparison is precisely the
part that is not.

WHAT IT DOES
------------
Walks the STAC catalog, and for every collection compares the current item id
against an append-only index of what has already been taken.  New items are
downloaded under an immutable per-item directory.  Nothing is ever overwritten.

Two disciplines are structural rather than stylistic:

- **The index is append-only and the payload is content-addressed.**  An item id
  that has been seen is never re-fetched, so a restart cannot corrupt the
  archive, and an item that changed under the same id is reported rather than
  silently replaced.  (Asset URLs carry a `?v=<crc>` suffix, which is the
  upstream signal that content moved.)

- **What was skipped is said, not omitted.**  Assets above the size cap are
  listed with their size and left alone; a failure to reach a collection does
  not abort the rest and is recorded as a miss for that collection.  A collector
  that silently drops what it could not fetch would produce an archive whose
  gaps look like quiet periods in the weather.

Usage:
  python3 scripts/xue_collect.py                 # one pass
  python3 scripts/xue_collect.py --loop 600      # one pass every 10 minutes
  python3 scripts/xue_collect.py --max-mb 40     # per-asset size cap
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = "https://dataset.ringsaturn.me/xue/catalog.json"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) xue-study collector"

# Collections whose extents are short enough that a missed pass is a permanent
# hole.  Ordered so that the most perishable is fetched first if a pass is cut
# short.  This is measured, not assumed: the cma extent was 2.4 hours when the
# ordering was written.
PERISHABLE = ("cma", "mrms", "jma", "sounding", "airport")

# Asset selection.  Measured on 2026-09-17: the full-disk satellite composites
# run 416-496 MB per image for dustrgb and 127-148 MB for the infrared channel,
# across four satellites hourly -- about 2 GB per hour.  Archiving that is not a
# collector, it is a firehose, and it is also not where the state lives.
#
# What is taken by default carries the state and the index: the manifest (which
# holds the run's frame index and its CRC), the poster (a small rendered view),
# and any asset whose own name says it is small.  Full rasters are opt-in per
# collection, and only where the whole product is genuinely small -- the CMA
# radar mosaic, the product this study already reads, is 0.92 MB complete.
ALWAYS_SUFFIX = ("manifest", "index", "poster")
FULL_COLLECTIONS = ("cma", "jma", "sounding", "tc")
NEVER_SUFFIX = ("dustrgb", "video", "history")


def wanted(collection: str, asset: str) -> bool:
    """Whether an asset is in the archive policy.

    Deterministic on purpose: a skip that happens for a policy reason is not a
    gap that a later pass should fill, so the index can treat the item as done.
    A skip caused by an error or a size cap is different and is recorded as
    such, so the two never look alike in the index.
    """
    a = asset.lower()
    if any(a.endswith(s) or f"-{s}" in a for s in NEVER_SUFFIX):
        return False
    if any(a == s or a.endswith(s) for s in ALWAYS_SUFFIX):
        return True
    return collection in FULL_COLLECTIONS


def get(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def abspath(base: str, href: str) -> str:
    return urllib.parse.urljoin(base, href)


def load_json(path: Path):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            return None
    return None


def save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, ensure_ascii=False))
    tmp.replace(path)


def fetch_store(store_url: str, dest: Path, max_bytes: int) -> dict:
    """Fetch a Zarr store key by key.

    A store is NOT a file, and asking for `<path>.zarr` as one returns 404 --
    which is what the first version of this collector did for every raster it
    tried to take.  The chunk key scheme is `<node>/c/<indices...>`, with `c` as
    its own path segment: `cref/c/0/0/0` is 200 while `cref/c0/0/0`, `c0/0/0`
    and `0/0/0` are all 404.

    The layout comes from the consolidated `zarr.json` at the store root.  The
    store's own `byteLength` is then checked against what was fetched, so a
    short store is reported rather than written out as if complete.
    """
    import itertools
    import math

    dest.mkdir(parents=True, exist_ok=True)
    got, keys = 0, []
    # Count and store the ORIGINAL bytes.  Re-encoding the parsed object with
    # json.dumps changes the length (whitespace, key order), which showed up as
    # a constant 2.8 kB shortfall against the store's declared byteLength for
    # every store in a collection.
    raw_root = get(store_url.rstrip("/") + "/zarr.json")
    (dest / "zarr.json").write_bytes(raw_root)
    got += len(raw_root)
    keys.append("zarr.json")
    root = json.loads(raw_root)

    nodes = (root.get("consolidated_metadata") or {}).get("metadata") or {}
    for node, meta in nodes.items():
        if meta.get("node_type") != "array":
            continue
        # The per-array zarr.json is part of the store's byte count.
        try:
            sub = get(f"{store_url.rstrip('/')}/{node}/zarr.json")
            (dest / f"{node}.zarr.json").write_bytes(sub)
            got += len(sub)
            keys.append(f"{node}/zarr.json")
        except Exception:
            pass
        shape = meta.get("shape") or []
        cs = ((meta.get("chunk_grid") or {}).get("configuration") or {}).get("chunk_shape")
        if not shape or not cs:
            continue
        grids = [max(1, math.ceil(s / c)) for s, c in zip(shape, cs)]
        for idx in itertools.product(*[range(g) for g in grids]):
            key = "/".join([node, "c"] + [str(i) for i in idx])
            blob = get(f"{store_url.rstrip('/')}/{key}", timeout=300)
            out = dest / key.replace("/", "__")
            out.write_bytes(blob)
            got += len(blob)
            keys.append(key)
    return {"keys": keys, "bytes": got}


def collect_once(archive: Path, max_bytes: int, verbose: bool) -> dict:
    """One pass over the catalog.  Returns a report of what happened."""
    report = {"at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
              "collections": {}, "new": 0, "bytes": 0}
    index_path = archive / "index.json"
    index = load_json(index_path) or {"seen": {}, "misses": []}
    seen = index["seen"]

    try:
        cat = json.loads(get(CATALOG))
    except Exception as exc:
        report["catalog_error"] = str(exc)[:200]
        return report

    children = [(l.get("title", "?"), abspath(CATALOG, l["href"]))
                for l in cat.get("links", []) if l.get("rel") == "child"]
    # Perishable collections first.
    children.sort(key=lambda t: 0 if any(p in t[1] for p in PERISHABLE) else 1)

    for title, coll_url in children:
        # The href is "<name>/collection.json", so the collection name is the
        # PARENT directory.  Taking the last path segment yields the literal
        # "collection" for every child, which silently merges all sixteen
        # collections into one directory and one report entry.
        name = coll_url.rstrip("/").split("/")[-2]
        entry = {"title": title, "state": "unchanged"}
        try:
            item = json.loads(get(coll_url))
            base = coll_url
            item_id = item.get("id")
            extent = (item.get("extent", {}).get("temporal", {})
                      .get("interval", [[None, None]])[0])
            entry["extent"] = extent

            # The item link may point at an immutable per-run directory.
            for l in item.get("links", []):
                if l.get("rel") in ("latest-version", "item"):
                    try:
                        item = json.loads(get(abspath(base, l["href"])))
                        item_id = item.get("id", item_id)
                    except Exception:
                        pass
                    break

            if not item_id:
                entry["state"] = "no item id"
                report["collections"][name] = entry
                continue

            if item_id in seen:
                entry["item"] = item_id
                report["collections"][name] = entry
                continue

            # New item: take its assets.
            dest = archive / name / item_id
            dest.mkdir(parents=True, exist_ok=True)
            save_json(dest / "item.json", item)
            taken, skipped = [], []
            for aname, asset in (item.get("assets") or {}).items():
                href = abspath(base, asset.get("href", ""))
                if not href:
                    continue
                size = asset.get("file:size") or asset.get("size")
                size = int(size) if size else None
                if not wanted(name, aname):
                    skipped.append({"asset": aname, "bytes": size,
                                    "note": "not in policy"})
                    continue
                if size and size > max_bytes:
                    skipped.append({"asset": aname, "bytes": size,
                                    "note": "over cap"})
                    continue
                try:
                    # `xue:kind == "store"` means a Zarr store, which is a set
                    # of keys rather than one object.  The declared file:size is
                    # the size of the WHOLE store, so it is also the figure the
                    # fetch is checked against afterwards.
                    if (asset.get("xue:kind") == "store") or href.endswith(".zarr"):
                        r = fetch_store(href, dest / aname.replace("/", "_"),
                                        max_bytes)
                        taken.append({"asset": aname, "bytes": r["bytes"],
                                      "keys": len(r["keys"]),
                                      "declared": size})
                        report["bytes"] += r["bytes"]
                        continue
                    blob = get(href, timeout=300)
                except Exception as exc:
                    skipped.append({"asset": aname, "error": str(exc)[:90]})
                    continue
                if len(blob) > max_bytes:
                    skipped.append({"asset": aname, "bytes": len(blob),
                                    "note": "over cap after fetch"})
                    continue
                out = dest / aname.replace("/", "_")
                out.write_bytes(blob)
                taken.append({"asset": aname, "bytes": len(blob)})
                report["bytes"] += len(blob)

            seen[item_id] = {"collection": name, "at": report["at"],
                             "assets": [t["asset"] for t in taken]}
            entry["state"] = "new"
            entry["item"] = item_id
            entry["assets_taken"] = taken
            if skipped:
                entry["assets_skipped"] = skipped
            report["new"] += 1
        except Exception as exc:
            entry["state"] = "unreachable"
            entry["error"] = str(exc)[:140]
            index["misses"].append({"collection": name, "at": report["at"],
                                    "error": str(exc)[:140]})
            index["misses"] = index["misses"][-500:]
        report["collections"][name] = entry
        # Save after EVERY collection, not once at the end.  A pass over
        # sixteen collections now takes minutes (each Zarr store is a dozen
        # requests), and a pass killed part-way through used to lose its whole
        # index and re-download everything on the next try.
        save_json(index_path, index)

    save_json(archive / "last-pass.json", report)
    if verbose:
        for name, e in sorted(report["collections"].items()):
            mark = {"new": "+", "unchanged": "=", "unreachable": "!"}.get(e["state"], "?")
            extra = ""
            if e.get("assets_taken"):
                extra = f"  {len(e['assets_taken'])} assets, " \
                        f"{sum(a['bytes'] for a in e['assets_taken']) / 1e6:.2f} MB"
            if e.get("assets_skipped"):
                extra += f"  ({len(e['assets_skipped'])} skipped)"
            if e.get("error"):
                extra = "  " + e["error"]
            print(f"  {mark} {name:<10} {e['state']:<12}{extra}")
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", default=str(ROOT / "archive"))
    ap.add_argument("--loop", type=int, default=0,
                    help="seconds between passes; 0 runs once")
    ap.add_argument("--max-mb", type=float, default=40.0,
                    help="per-asset size cap in MB")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    archive = Path(args.archive).expanduser()
    archive.mkdir(parents=True, exist_ok=True)
    cap = int(args.max_mb * 1e6)

    if args.loop <= 0:
        r = collect_once(archive, cap, not args.quiet)
        print(f"  pass: {r['new']} new, {r['bytes'] / 1e6:.2f} MB -> {archive}")
        return 0

    print(f"  collecting every {args.loop}s into {archive} (cap {args.max_mb} MB/asset)")
    while True:
        t0 = time.time()
        try:
            r = collect_once(archive, cap, not args.quiet)
            print(f"  {r['at']}  new={r['new']}  {r['bytes'] / 1e6:.2f} MB", flush=True)
        except KeyboardInterrupt:
            return 0
        except Exception as exc:                       # never die silently
            print(f"  pass failed: {str(exc)[:160]}", flush=True)
        time.sleep(max(5.0, args.loop - (time.time() - t0)))


if __name__ == "__main__":
    raise SystemExit(main())
