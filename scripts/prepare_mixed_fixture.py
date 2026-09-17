"""Build a store whose two arrays use different inner codec chains.

`tests/prepare_web_fixture.py` writes `wind10m.zarr` with both arrays on the
standard `[bytes, zstd]` chain and, separately, a single-variable
`tmp2m.delta.zarr` on `[xue.delta, bytes, zstd]`. What it does not write is a
store that mixes the two — which is what `export_bundle(delta="auto")`
produces, since it decides per array.

The frontend reads each array's own metadata (`zarr/session.ts`), and its
"every array of a store must be cut the same way" check looks at the tiling
and the time chunk rather than the codec chain, so a mixed store should play.
This builds one so that claim is executed rather than read.

Usage: python tests/prepare_mixed_fixture.py
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from xuebuild import zarrstore

ROOT = Path(__file__).resolve().parent / "fixtures" / "generated" / "web"
STANDARD = ROOT / "wind10m.zarr"
MIXED = ROOT / "wind10m.mixed.zarr"
DELTA = ROOT / "wind10m.deltaall.zarr"
# One array standard, one differenced. `vgrd10m` is the one that changes.
DIFFERENCED = "vgrd10m"


def main() -> int:
    if MIXED.exists():
        shutil.rmtree(MIXED)
    zarrstore.export_bundle(ROOT / "wind10m.xue", DELTA, delta=True)
    shutil.copytree(STANDARD, MIXED)
    for name in (DIFFERENCED,):
        shutil.rmtree(MIXED / name)
        shutil.copytree(DELTA / name, MIXED / name)
    shutil.rmtree(DELTA)

    # The group document repeats every array document verbatim for clients
    # that cannot list the store; keep it true of the store as it now is.
    group = json.loads((MIXED / "zarr.json").read_text())
    group["consolidated_metadata"]["metadata"] = {
        name: json.loads((MIXED / name / "zarr.json").read_text())
        for name in group["consolidated_metadata"]["metadata"]
    }
    (MIXED / "zarr.json").write_text(json.dumps(group, indent=2, ensure_ascii=False) + "\n")

    for name in sorted(group["consolidated_metadata"]["metadata"]):
        array = json.loads((MIXED / name / "zarr.json").read_text())
        codecs = array.get("codecs") or []
        chain = (
            [codec["name"] for codec in codecs[0]["configuration"]["codecs"]]
            if codecs and codecs[0]["name"] == "sharding_indexed"
            else [codec["name"] for codec in codecs]
        )
        print(f"  {name}: {chain}")
    print(f"wrote {MIXED}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
