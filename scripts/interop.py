"""Can a Zarr client that knows nothing about xue read the store?

Run one (store, register) pair per process, so a registration in one case
cannot leak into the next.

Usage: uv run python interop.py <store.zarr> <register:0|1>
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path


def step(label: str, fn) -> bool:
    try:
        result = fn()
        print(f"  {label:38} OK    {result}")
        return True
    except Exception as exc:  # noqa: BLE001 - the point is to report whatever it is
        name = type(exc).__name__
        message = str(exc).strip().splitlines()[0][:90] if str(exc).strip() else ""
        print(f"  {label:38} FAIL  {name}: {message}")
        return False


def main() -> int:
    store = Path(sys.argv[1])
    register = sys.argv[2] == "1"

    import xarray
    import zarr

    if register:
        from xuebuild import zarrcodec

        zarrcodec.register()
        print(f"  (xue.delta registered via xuebuild.zarrcodec.register())")
    else:
        print(f"  (nothing registered -- a plain Zarr client)")

    # 1. the group
    group = None

    def open_group():
        nonlocal group
        group = zarr.open_group(str(store), mode="r")
        return f"arrays={sorted(group.array_keys())}"

    if not step("zarr.open_group(store)", open_group):
        return 1

    # 2. each array, a corner of the first frame
    import json

    unaffected = []
    for name in sorted(group.array_keys()):
        meta = json.loads((store / name / "zarr.json").read_text())
        codecs = meta.get("codecs") or []
        chain = (
            [codec["name"] for codec in codecs[0]["configuration"]["codecs"]]
            if codecs and codecs[0]["name"] == "sharding_indexed"
            else [codec["name"] for codec in codecs]
        )
        def corner(name=name):
            array = group[name]
            if array.ndim == 3:
                return f"corner={array[0, 0, 0:3].tolist()}"
            return f"len={array.shape[0]} head={array[0:3].tolist()}"

        ok = step(f"read {name} {chain}", corner)
        unaffected.append(ok)

    # 3. xarray on the whole group
    def xr_open():
        dataset = xarray.open_zarr(str(store))
        return f"data_vars={sorted(dataset.data_vars)}"

    def xr_load():
        dataset = xarray.open_zarr(str(store))
        dataset.load()
        return f"loaded, {sum(v.size for v in dataset.data_vars.values())} values"

    step("xarray.open_zarr(store)", xr_open)
    step("xarray ... .load()", xr_load)
    return 0 if all(unaffected) else 1


if __name__ == "__main__":
    raise SystemExit(main())
