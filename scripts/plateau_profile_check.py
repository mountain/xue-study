"""Test the plateau mechanism per gridpoint, keyed on height above ground.

The box-mean version compared a 20x11 degree plateau against the rest of its
latitude band and asked whether the mean was warm. That cannot separate the two
things it needs to separate: a level that is *under* the local ground is filled
by extrapolation, and a level that is *above* a heated plateau is genuinely warm.
Both show up as a positive anomaly.

This asks the sharper question instead. Height above ground is
`hgt(level) - elevation`, measured per gridpoint from the published geopotential
height and Copernicus DEM GLO-90, and the prediction is that the anomaly is a
function of it: strongly warm where the level is under the ground, and no
longer a function of it where the level is well above.

Usage: uv run python scripts/plateau_profile_check.py <dem.npz> [run]
"""

from __future__ import annotations

import sys

import numpy as np
import xarray as xr

BASE = "https://dataset.ringsaturn.me/xue/gfs.{run}"
BAND = (27.0, 38.0)
BINS = [-4000, -3000, -2000, -1000, 0, 500, 1500, 3000, 6000]


def load(dem_path: str, run: str, name: str):
    archive = np.load(dem_path)
    elevation, dem_lat, dem_lon = archive["elevation"], archive["latitudes"], archive["longitudes"]

    dataset = xr.open_zarr(f"{BASE.format(run=run)}/{name}.half.zarr").sel(latitude=slice(BAND[1], BAND[0]))
    field = dataset[name]

    # The DEM is 0.25 degree and the half tier is 0.5; average the DEM onto the
    # field's own grid so the two describe the same cells.
    height, width = field.sizes["latitude"], field.sizes["longitude"]
    coarse = np.full((height, width), np.nan)
    lat_step = 180.0 / field.sizes["latitude"]
    lon_step = 360.0 / field.sizes["longitude"]
    cell_lat = dataset["latitude"].values
    cell_lon = dataset["longitude"].values
    for i in range(height):
        # A cell centred at `la` spans [la - step/2, la + step/2). The DEM rows
        # run south to north, the field rows north to south, so the two are
        # matched by latitude value and never by row index.
        south, north = cell_lat[i] - lat_step / 2, cell_lat[i] + lat_step / 2
        rows = (dem_lat >= south) & (dem_lat < north)
        for j in range(width):
            west, east = cell_lon[j] - lon_step / 2, cell_lon[j] + lon_step / 2
            columns = (dem_lon >= west) & (dem_lon < east)
            block = elevation[np.ix_(rows, columns)]
            with np.errstate(invalid="ignore"):
                coarse[i, j] = np.nanmean(block) if np.isfinite(block).any() else np.nan
    values = np.asarray(field.isel(time=0), dtype="float64")
    finite = np.isfinite(coarse) & np.isfinite(values)
    print(f"  对齐检查：场 {values.size} 格点，其中场有限 {int(np.isfinite(values).sum())}、"
          f"DEM 有限 {int(np.isfinite(coarse).sum())}、两者皆有限 {int(finite.sum())}")
    if finite.any():
        print(f"           高程 {np.nanmin(coarse[finite]):.0f}..{np.nanmax(coarse[finite]):.0f} m")
    return field, coarse


def main() -> int:
    dem_path = sys.argv[1]
    run = sys.argv[2] if len(sys.argv) > 2 else "2026091618"

    print(f"run {run}   纬度带 {BAND}   离地高度 = hgt(层) − 地面高程（Copernicus GLO-90）\n")
    for level, height_field in (("tmp850", "hgt850"), ("tmp500", "hgt500")):
        field, elevation = load(dem_path, run, level)
        heights, _ = load(dem_path, run, height_field)

        temperature = np.asarray(field.isel(time=0), dtype="float64")
        geopotential = np.asarray(heights.isel(time=0), dtype="float64")
        above = geopotential - elevation
        latitude = field["latitude"].values

        # The band's own mean at each latitude row, so the latitudinal structure
        # divides out and what is left is each column's departure.
        with np.errstate(invalid="ignore"):
            row_mean = np.nanmean(temperature, axis=1, keepdims=True)
            anomaly = temperature - row_mean

        good = np.isfinite(anomaly) & np.isfinite(above)
        print(f"{level}（对照 {height_field}）")
        print(f"  {'离地高度':>16} {'格点数':>7} {'异常均值':>9} {'异常标准差':>10}")
        for low, high in zip(BINS, BINS[1:]):
            mask = good & (above >= low) & (above < high)
            count = int(mask.sum())
            if count == 0:
                continue
            values = anomaly[mask]
            print(f"  [{low:>5}, {high:>5}) m {count:7d} {values.mean():+8.2f} K {values.std():9.2f}")
        underground = good & (above < 0)
        aloft = good & (above > 1500)
        if underground.any() and aloft.any():
            print(f"  → 地下（h-a-g<0）{int(underground.sum())} 点，异常 {anomaly[underground].mean():+.2f} K；"
                  f"高空（>1500 m）{int(aloft.sum())} 点，异常 {anomaly[aloft].mean():+.2f} K")
        print()

    print("OBSERVED HERE  verdict: see the bins above. The prediction is a warm anomaly that")
    print("               depends on height above ground below zero and stops depending on it above.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
