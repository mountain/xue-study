"""Which predictor wins, per variable, measured directly on the quantized codes.

For one six-frame chunk, every tile is compressed twice at the store's own
settings -- once as the codes (RAW) and once as the modulo-256 difference
against the previous frame (the container's PREVIOUS predictor / the
`xue.delta` codec) -- and the totals are compared. Nothing here uses the
container's or the store's own accounting.

Usage: uv run python predictors.py <run-dir> [manifest.json]
"""

from __future__ import annotations

import json
import sys
from compression import zstd
from pathlib import Path

import numpy as np
import xue

LEVEL = 15
FRAMES = 6


def measure(bundle_path: Path) -> list[tuple[str, int, int]]:
    """(variable, raw bytes, residual bytes) for every variable in the bundle."""
    bundle = xue.Bundle.open(bundle_path)
    height, width = bundle.metadata["grid"]["height"], bundle.metadata["grid"]["width"]
    tile_width, tile_height = bundle.tile or (width, height)
    offsets = bundle.frame_offsets[:FRAMES]
    names = {v["numericId"]: v["id"] for v in bundle.metadata["variables"]}
    out = []
    for numeric_id in bundle.variable_ids:
        planes = np.stack([
            np.frombuffer(bundle.decode(numeric_id, offset), dtype=np.uint8).reshape(height, width)
            for offset in offsets
        ])
        raw = residual = 0
        for row in range(0, height, tile_height):
            for column in range(0, width, tile_width):
                block = planes[:, row:row + tile_height, column:column + tile_width].copy()
                raw += len(zstd.compress(block.tobytes(), level=LEVEL))
                delta = block.copy()
                delta[1:] = (block[1:] - block[:-1]).astype(np.uint8)
                residual += len(zstd.compress(delta.tobytes(), level=LEVEL))
        out.append((names.get(numeric_id, str(numeric_id)), raw, residual))
    bundle.clear_cache()
    return out


def main() -> int:
    run_dir = Path(sys.argv[1])
    manifest = json.loads(Path(sys.argv[2]).read_text()) if len(sys.argv) > 2 else None
    published = {}
    if manifest:
        for entry in manifest["bundles"]:
            zarr = entry.get("zarr") or {}
            published[entry["variable"]] = zarr.get("byteLength")

    rows = []
    for bundle_path in sorted(run_dir.glob("*.xue")):
        measured = measure(bundle_path)
        # A bundle may hold two variables (wind10m, qflux850, wave); the
        # manifest names one store per bundle, so each variable's share of it
        # is its own byte count divided by the bundle's variable count.
        share = published.get(bundle_path.stem)
        share = share / len(measured) if share else None
        for name, raw, residual in measured:
            rows.append((bundle_path.stem, name, raw, residual, share))

    print(f"{'bundle':10} {'variable':10} {'RAW':>10} {'residual':>10} {'res/raw':>8}  winner   {'share':>13} {'est. saving':>12}")
    total_pub = total_save = 0
    for bundle_id, name, raw, residual, share in sorted(rows, key=lambda r: r[3] / r[2]):
        ratio = residual / raw
        winner = "residual" if ratio < 1 else "RAW"
        saving = share * (1 - ratio) if (share and ratio < 1) else 0
        total_pub += share or 0
        total_save += saving
        pub_text = f"{share:,.0f}" if share else "—"
        print(f"{bundle_id:10} {name:10} {raw:10,} {residual:10,} {ratio:7.3f}  {winner:8} {pub_text:>13} {saving:12,.0f}")
    print()
    print(f"measured variables: {len(rows)}")
    print(f"residual wins: {sum(1 for r in rows if r[3] < r[2])}   RAW wins: {sum(1 for r in rows if r[3] >= r[2])}")
    if total_pub:
        print(f"published (full-res stores named in the manifest): {total_pub:,} bytes")
        print(f"estimated saving from per-variable predictor choice: {total_save:,.0f} bytes "
              f"({total_save / total_pub * 100:.1f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
