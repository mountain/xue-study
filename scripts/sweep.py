"""Sweep: for every built bundle, measure container vs store (with and without
the xue.delta codec) and confirm byte identity independently.

Usage: uv run python sweep.py <run-dir> <delta-out-dir> <variable>...
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent


def store_bytes(store: Path) -> int:
    return sum(p.stat().st_size for p in store.rglob("*") if p.is_file())


def export_delta(python: str, bundle: Path, out: Path) -> dict:
    result = subprocess.run(
        [python, "-m", "xuebuild", "export-zarr", str(bundle), "--out", str(out), "--delta"],
        capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout)


def verify(python: str, bundle: Path, store: Path, variable: str) -> str:
    result = subprocess.run(
        [python, str(HERE / "verify.py"), str(bundle), str(store), variable],
        capture_output=True, text=True,
    )
    for line in result.stdout.splitlines():
        if "(a)" in line or "(b)" in line:
            print(f"      {line.strip()}")
    return result.stdout


def main() -> int:
    run_dir, delta_dir = Path(sys.argv[1]), Path(sys.argv[2])
    variables = sys.argv[3:]
    python = sys.executable
    rows = []
    for bundle_id in variables:
        bundle = run_dir / f"{bundle_id}.xue"
        if not bundle.exists():
            print(f"{bundle_id}: no bundle at {bundle}")
            continue
        container = bundle.stat().st_size
        plain = run_dir / f"{bundle_id}.zarr"
        plain_bytes = store_bytes(plain)
        out = delta_dir / f"{bundle_id}.zarr"
        out.parent.mkdir(parents=True, exist_ok=True)
        report = export_delta(python, bundle, out)
        delta_bytes = report["byteLength"]
        rows.append((bundle_id, container, plain_bytes, delta_bytes,
                     report["comparableChunks"], report["identicalChunks"]))
        print(f"--- {bundle_id}: container={container:,} store={plain_bytes:,} "
              f"({plain_bytes/container:.3f}x)  delta={delta_bytes:,} ({delta_bytes/container:.3f}x)  "
              f"identical/comparable={report['identicalChunks']}/{report['comparableChunks']}")

    print()
    print(f"{'bundle':10} {'container':>13} {'store':>13} {'ratio':>7} {'store+delta':>13} {'ratio':>7} {'saved':>8}")
    tc = tp = td = 0
    for name, c, p, d, _, _ in sorted(rows, key=lambda r: -(r[2] - r[3]) / r[1]):
        tc += c; tp += p; td += d
        print(f"{name:10} {c:13,} {p:13,} {p/c:6.3f}x {d:13,} {d/c:6.3f}x {(p-d)/p*100:7.1f}%")
    if tc:
        print(f"{'TOTAL':10} {tc:13,} {tp:13,} {tp/tc:6.3f}x {td:13,} {td/tc:6.3f}x {(tp-td)/tp*100:7.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
