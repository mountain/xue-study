"""Mean surface elevation per forecast grid cell, from Copernicus DEM GLO-90.

The plateau work needed terrain and did without it: the mechanism claim rests on
"the Tibetan Plateau is about 4500 m", a textbook value written in as an
assumption rather than measured. This measures it, per 0.25 degree cell, so the
height of a pressure level above the ground can be computed at every gridpoint
instead of argued from a box mean.

Source and rights, recorded because this repository's own publication boundary
requires it: Copernicus DEM GLO-90, ESA, on the AWS Open Data bucket
`copernicus-dem-90m`. It is free of charge and redistributable with attribution,
but it is **not** public domain and **not** CC0 -- so under
`PUBLICATION_BOUNDARY.md` it is not admissible into the project's public
repositories. Nothing here is vendored: the tiles are read over HTTPS through
GDAL's /vsicurl/ and only the derived per-cell means are kept.

Usage: uv run python scripts/dem_elevation.py <out.npz> [west east south north] [decimated]
"""

from __future__ import annotations

import sys

import numpy as np
import rasterio
from rasterio.windows import from_bounds

BUCKET = "https://copernicus-dem-90m.s3.amazonaws.com"
TILE = ("{bucket}/Copernicus_DSM_COG_30_N{lat:02d}_00_E{lon:03d}_00_DEM/"
         "Copernicus_DSM_COG_30_N{lat:02d}_00_E{lon:03d}_00_DEM.tif")


def tile_href(lat: int, lon: int) -> str:
    return TILE.format(bucket=BUCKET, lat=lat, lon=lon)


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else "dem-elevation.npz"
    west, east, south, north = (float(v) for v in sys.argv[2:6]) if len(sys.argv) > 5 else (80.0, 100.0, 27.0, 38.0)
    step = float(sys.argv[6]) if len(sys.argv) > 6 else 0.25
    decimated = int(sys.argv[7]) if len(sys.argv) > 7 else 200

    latitudes = np.arange(south, north, step)
    longitudes = np.arange(west, east, step)
    total_sum = np.zeros((latitudes.size, longitudes.size))
    total_count = np.zeros((latitudes.size, longitudes.size), dtype=int)

    lat_tiles = range(int(np.floor(south)), int(np.ceil(north)))
    lon_tiles = range(int(np.floor(west)), int(np.ceil(east)))
    total = len(list(lat_tiles)) * len(list(lon_tiles))
    print(f"网格 {latitudes.size} x {longitudes.size}（{step}°，{west}-{east}E, {south}-{north}N）")
    print(f"DEM 瓦片 {total} 个，每个读 {decimated}x{decimated} 概视\n")

    done = 0
    for lat in range(int(np.floor(south)), int(np.ceil(north))):
        for lon in range(int(np.floor(west)), int(np.ceil(east))):
            href = tile_href(lat, lon)
            try:
                with rasterio.open(f"/vsicurl/{href}") as src:
                    bounds = src.bounds
                    # One decimated read per tile: GDAL picks an overview, so the
                    # transfer is a few KB rather than the whole COG.
                    window = from_bounds(bounds.left, bounds.bottom, bounds.right, bounds.top, src.transform)
                    block = src.read(1, window=window, out_shape=(decimated, decimated),
                                     resampling=rasterio.enums.Resampling.average)
                    block = block.astype("float64")
                    block[block < -1000] = np.nan
            except Exception as exc:  # noqa: BLE001 - report and keep going
                print(f"  {lat}N {lon}E  SKIPPED — {type(exc).__name__}: {str(exc)[:70]}")
                continue

            # The tile's own bounds say what it covers; scatter its samples into
            # the cells by their own coordinates rather than assuming an origin.
            rows = np.linspace(bounds.top, bounds.bottom, decimated, endpoint=False)
            columns = np.linspace(bounds.left, bounds.right, decimated, endpoint=False)
            row_index = np.searchsorted(latitudes, rows, side="right") - 1
            column_index = np.searchsorted(longitudes, columns, side="right") - 1
            for i, r in enumerate(row_index):
                if not 0 <= r < latitudes.size:
                    continue
                for j, c in enumerate(column_index):
                    if not 0 <= c < longitudes.size:
                        continue
                    value = block[i, j]
                    if np.isfinite(value):
                        # A mean, not a running average of two: a cell takes
                        # samples from several tiles once one is missing.
                        total_sum[r, c] += value
                        total_count[r, c] += 1

            done += 1
            if done % 20 == 0:
                print(f"  ... {done}/{total} 瓦片")

    with np.errstate(invalid="ignore"):
        elevation = np.where(total_count > 0, total_sum / np.maximum(total_count, 1), np.nan)
    finite = np.isfinite(elevation)
    print(f"\n完成 {done}/{total} 瓦片；{finite.sum()} 个格点有高程")
    if finite.any():
        print(f"高程范围 {np.nanmin(elevation):.0f} .. {np.nanmax(elevation):.0f} m；均值 {np.nanmean(elevation):.0f} m")
        # The number the claim previously assumed.
        plateau = elevation
        print(f"高原框内均值 {np.nanmean(plateau):.0f} m（claim 里原来写的是假设值约 4500 m）")
    np.savez(out, elevation=elevation, latitudes=latitudes, longitudes=longitudes)
    print(f"写入 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
