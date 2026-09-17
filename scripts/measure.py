"""Measure the container vs Zarr store size, and the cost of leaving the
temporal residual out of the store (i.e. not passing --delta).

Usage: uv run python measure.py <bundle.xue> [<store-without-delta.zarr> <store-with-delta.zarr>]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def store_bytes(store: Path) -> int:
    """Every object in the store, as a bucket would bill and a client fetch."""
    return sum(p.stat().st_size for p in store.rglob("*") if p.is_file())


def payload_bytes(store: Path, variable: str) -> int:
    shard = store / variable / "c" / "0" / "0" / "0"
    return shard.stat().st_size if shard.exists() else 0


def chain(store: Path, variable: str) -> list[str]:
    meta = json.loads((store / variable / "zarr.json").read_text())
    return [c["name"] for c in meta["codecs"][0]["configuration"]["codecs"]]


def main() -> int:
    bundle = Path(sys.argv[1])
    container = bundle.stat().st_size
    print(f"bundle: {bundle.name}  container(.xue) = {container:,} bytes\n")
    print(f"{'store':40} {'objects':>9} {'total(B)':>13} {'vs container':>13}  chain")
    for raw in sys.argv[2:]:
        store = Path(raw)
        variable = bundle.stem
        c = chain(store, variable) if (store / variable / "zarr.json").exists() else []
        total = store_bytes(store)
        objects = sum(1 for p in store.rglob("*") if p.is_file())
        print(f"{store.name:40} {objects:9,} {total:13,} {total / container:12.2f}x  {c}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
