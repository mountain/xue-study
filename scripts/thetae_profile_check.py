"""Test the theta-e clamp per gridpoint, keyed on height above ground.

`xue.derived.theta-e-plateau-clamp.v0` currently rests on a box mean: 62-66% of
the Tibetan Plateau box sits at the codebook ceiling, against 0-4 of 7021 in the
warm pool. That number says *where*, not *why*, and the mechanism it names --
below-ground extrapolation -- predicts something sharper: the clamp should be a
function of how far the 850 hPa level lies under the ground.

This measures that, with the same terrain the temperature profile used.

Usage: uv run python scripts/thetae_profile_check.py <dem.npz> [run]
"""

from __future__ import annotations

import sys

import numpy as np
import xarray as xr

BASE = "https://dataset.ringsaturn.me/xue/gfs.{run}"
BAND = (27.0, 38.0)
BINS = [-4000, -3000, -2000, -1000, 0, 500, 6000]


def main() -> int:
    dem_path = sys.argv[1]
    run = sys.argv[2] if len(sys.argv) > 2 else "2026091618"

    archive = np.load(dem_path)
    elevation, dem_lat, dem_lon = archive["elevation"], archive["latitudes"], archive["longitudes"]

    dataset = xr.open_zarr(f"{BASE.format(run=run)}/thetae850.half.zarr").sel(latitude=slice(BAND[1], BAND[0]))
    theta = np.asarray(dataset["thetae850"].isel(time=0), dtype="float64")

    heights = xr.open_zarr(f"{BASE.format(run=run)}/hgt850.half.zarr").sel(latitude=slice(BAND[1], BAND[0]))
    geopotential = np.asarray(heights["hgt850"].isel(time=0), dtype="float64")

    # The codebook's top, read from the published metadata rather than typed in:
    # a hard-coded ceiling is a number this script would then be checking itself
    # against.
    import json
    import urllib.request

    request = urllib.request.Request(
        f"{BASE.format(run=run)}/thetae850.half.zarr/thetae850/zarr.json",
        headers={"User-Agent": "xue-study/1.0 (theta-e profile check)"})
    with urllib.request.urlopen(request, timeout=25) as response:
        quant = json.load(response)["attributes"]["xue"]["variable"]["quantization"]
    ceiling = quant["offset"] + quant["scale"] * quant["maximumCode"]
    assert quant["type"] == "linear", quant["type"]

    # DEM onto the field's grid, matched by latitude value (the DEM runs south
    # to north and the field north to south, so never by row index).
    height, width = theta.shape
    coarse = np.full((height, width), np.nan)
    lat_step = 180.0 / height
    lon_step = 360.0 / width
    cell_lat, cell_lon = dataset["latitude"].values, dataset["longitude"].values
    for i in range(height):
        rows = (dem_lat >= cell_lat[i] - lat_step / 2) & (dem_lat < cell_lat[i] + lat_step / 2)
        for j in range(width):
            columns = (dem_lon >= cell_lon[j] - lon_step / 2) & (dem_lon < cell_lon[j] + lon_step / 2)
            block = elevation[np.ix_(np.flatnonzero(rows), np.flatnonzero(columns))]
            with np.errstate(invalid="ignore"):
                coarse[i, j] = np.nanmean(block) if np.isfinite(block).any() else np.nan

    above = geopotential - coarse
    good = np.isfinite(theta) & np.isfinite(above)
    at_ceiling = theta >= ceiling - 1e-9
    print(f"run {run}   theta-e 码本上限 {ceiling:.1f} K  "
          f"（offset 230 + scale 0.5 × maximumCode 254）")
    print(f"可判格点 {int(good.sum())} 个；其中发布值恰好顶在上限的 {int((good & at_ceiling).sum())} 个\n")
    print(f"{'850 hPa 离地高度':>18} {'格点数':>7} {'顶在上限':>9} {'占比':>7} {'θe 均值':>9}")
    for low, high in zip(BINS, BINS[1:]):
        mask = good & (above >= low) & (above < high)
        count = int(mask.sum())
        if count == 0:
            continue
        clamped = int((mask & at_ceiling).sum())
        print(f"  [{low:>5}, {high:>5}) m {count:7d} {clamped:9d} {clamped / count * 100:6.1f}% "
              f"{theta[mask].mean():8.2f}")
    print("\nOBSERVED HERE  verdict: the prediction is a clamp fraction that falls as the level")
    print("               rises from under the ground to above it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
