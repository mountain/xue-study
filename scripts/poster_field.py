"""Read an archived poster as a georeferenced field.  One place, so every figure
that draws a poster draws it the same way.

WHAT IS ESTABLISHED AND WHAT IS ASSUMED
---------------------------------------
The decode chain is not a guess -- it is xue's own reader:

    zlib.inflate -> vertical un-filter (cumsum mod 256 down each column)
                 -> value = offset + code * scale, nodata/max code masked

The GEOREFERENCE was a guess until `scripts/poster_grid_check.py` tested it
against the archived airport observations.  That check swept pole order,
half-cell offsets and the longitude seam, and the winner beat the strongest
genuinely different rival by 5.5 K of MAE (1.70 K against 7.19 K).  The mapping
it established is the one hard-coded here:

    row i    ->  latitude  =  90.0 - 0.5 * i     (north to south)
    column j ->  longitude = -180.0 + 0.5 * j    (west to east, -180..179.5)

Do not "improve" this by assuming it: rerun the check instead.  A poster drawn
on the wrong corner is not a slightly wrong figure, it is a picture of a
different part of the planet.

WHAT THIS DOES NOT CLAIM
------------------------
A poster is the run's FIRST frame, decimated 2x in each axis, so it is a 0.5 deg
view of an analysis, not the model's 0.25 deg grid and not a forecast.  Figures
built on it must say so.
"""

from __future__ import annotations

import json
import zlib
from pathlib import Path

import numpy as np

# Established by scripts/poster_grid_check.py -- see the module docstring.
ROW0_LAT = 90.0
COL0_LON = -180.0
STEP = 0.5

# Saturation is "within this much of the encoding ceiling".  The threshold is
# CHOSEN, not derived, and every figure that uses it has to say so.
CEIL_TOL_K = 2.0


def unfilter(plane: bytes, width: int, height: int) -> np.ndarray:
    """Undo the poster's vertical delta encoding (PNG "Up" filter)."""
    a = np.frombuffer(plane, dtype=np.uint8).reshape(height, width).astype(np.uint64)
    return (np.cumsum(a, axis=0) % 256).astype(np.uint8)


def quantization_of(item_dir: Path, variable: str) -> dict | None:
    """A variable's quantization, from the bundle MANIFEST.

    It is NOT in the item's asset metadata.  The first version of the poster
    renderer looked there, found nothing, and silently fell back -- so the
    decode produced plausible-looking nonsense.  When this returns None, callers
    must refuse rather than decode.
    """
    man = item_dir / "manifest"
    if not man.exists():
        return None
    for b in json.loads(man.read_text()).get("bundles", []):
        if b.get("variable") != variable:
            continue
        mj = (b.get("poster") or {}).get("metadataJson")
        if not mj:
            continue
        m = json.loads(mj) if isinstance(mj, str) else mj
        for v in m.get("variables", []):
            if v.get("id") == variable and v.get("quantization"):
                return v["quantization"]
    return None


class Poster:
    """One archived poster, decoded and georeferenced."""

    def __init__(self, collection, item, variable, values, valid, q, unit, run):
        self.collection = collection
        self.item = item
        self.variable = variable
        self.values = values
        self.valid = valid
        self.q = q
        self.unit = unit
        self.run = run

    @property
    def shape(self):
        return self.values.shape

    @property
    def ceiling(self):
        """The largest value the encoding can carry.  Anything at it is clipped."""
        return self.q["offset"] + self.q["maximumCode"] * self.q["scale"]

    @property
    def lat(self):
        return ROW0_LAT - STEP * np.arange(self.values.shape[0])

    @property
    def lon(self):
        return COL0_LON + STEP * np.arange(self.values.shape[1])

    def saturated(self, tol=None):
        tol = CEIL_TOL_K if tol is None else tol
        return self.valid & (self.values >= self.ceiling - tol)

    def box(self, west, east, south, north):
        """Indices of a lon/lat box, with guards in BOTH directions.

        The mask lesson from this repository: a guard that only rejects "zero
        cells selected" does not reject "all cells selected", and the second is
        the failure that actually happened.  So both bounds are enforced and the
        selected fraction is returned for the caller to print.
        """
        lat, lon = self.lat, self.lon
        # A box crossing the 0/360 seam is a UNION, not an intersection --
        # getting that backwards once selected every column on the grid.
        if west <= east:
            li = np.flatnonzero((lon >= west) & (lon <= east))
        else:
            li = np.flatnonzero((lon >= west) | (lon <= east))
        ri = np.flatnonzero((lat <= north) & (lat >= south))
        li.sort()
        ri.sort()
        h, w = self.values.shape
        if li.size == 0 or ri.size == 0:
            raise ValueError(f"box selected no cells: lon {li.size}, lat {ri.size}")
        if li.size == w and ri.size == h:
            raise ValueError("box selected the ENTIRE grid -- the box is wrong")
        if li.size > 0.5 * w or ri.size > 0.5 * h:
            raise ValueError(
                f"box selected {li.size}/{w} lon by {ri.size}/{h} lat, over half "
                "the grid; that is almost certainly a box bug, not a big region")
        return ri, li

    def box_values(self, west, east, south, north):
        ri, li = self.box(west, east, south, north)
        sub = self.values[np.ix_(ri, li)]
        m = self.valid[np.ix_(ri, li)]
        return sub, m

    def box_stats(self, west, east, south, north):
        sub, m = self.box_values(west, east, south, north)
        n = int(m.sum())
        if n == 0:
            return {"n": 0}
        v = sub[m]
        sat = sub >= (self.ceiling - CEIL_TOL_K)
        return {
            "n": n,
            "cells": int(sub.size),
            "mean": float(v.mean()),
            "median": float(np.median(v)),
            "min": float(v.min()),
            "max": float(v.max()),
            "sd": float(v.std()),
            "ceiling": float(self.ceiling),
            "saturated_frac": float(sat[m].mean()),
            "at_ceiling_frac": float((v >= self.ceiling).mean()),
        }


def load(archive: Path, collection: str, item: str, variable: str) -> Poster:
    item_dir = Path(archive) / collection / item
    poster = item_dir / f"{variable}-poster"
    if not poster.exists():
        raise FileNotFoundError(poster)
    meta = json.loads((item_dir / "item.json").read_text())
    grid = meta["assets"][f"{variable}-poster"].get("xue:grid") or {}
    w, h = grid.get("width"), grid.get("height")
    plane = zlib.decompress(poster.read_bytes())
    if len(plane) != w * h:
        raise ValueError(f"{item}/{variable}: plane {len(plane)} != {w}x{h}")
    q = quantization_of(item_dir, variable)
    if q is None:
        # Not a fallback.  Decoding without the quantization is how the first
        # attempt produced a neutral-grey picture of nothing.
        raise ValueError(f"{item}/{variable}: no quantization in the manifest")
    codes = unfilter(plane, w, h)
    values = q["offset"] + codes.astype(np.float64) * q["scale"]
    valid = (codes != q.get("nodataCode")) & (codes <= q.get("maximumCode", 255))
    # The unit lives in the VARIABLE dictionary, not in the quantization
    # dictionary.  Reading it from the quantization silently defaulted to K and
    # subtracted 273.15 from Celsius values, giving -273 degC.  Third time this
    # class of error has been made in this repository, hence the comment.
    unit = (meta["properties"].get("cube:variables", {})
            .get(variable, {}).get("unit"))
    return Poster(collection, item, variable, values, valid, q, unit,
                  meta["properties"].get("xue:runTime"))


def runs_with(archive: Path, collection: str, variable: str) -> list[str]:
    d = Path(archive) / collection
    if not d.is_dir():
        return []
    return sorted(p.name for p in d.iterdir()
                  if (p / f"{variable}-poster").exists())


# Region boxes.  The first three are the report's plateau / warm-pool /
# central-Europe comparison; the last three are controls.
BOXES = {
    "高原 80-92E,26-32N": (80.0, 92.0, 26.0, 32.0),
    "暖池 120-180E,15S-15N": (120.0, 180.0, -15.0, 15.0),
    "中欧 0-20E,45-55N": (-0.0, 20.0, 45.0, 55.0),
    "东中国海 120-130E,25-35N": (120.0, 130.0, 25.0, 35.0),
    "撒哈拉 0-20E,20-30N": (0.0, 20.0, 20.0, 30.0),
}
