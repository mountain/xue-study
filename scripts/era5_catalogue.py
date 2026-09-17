#!/usr/bin/env python3
"""Catalogue the ERA5 collection on the portable drive, without copying it.

The drive holds roughly 304 GB, and this machine has about 21 GB free, so the
bytes stay where they are and only a catalogue enters the repository.  That is
also the right answer on licensing grounds:

    ERA5 is a Copernicus product.  It is free to use, but it is NOT public
    domain, and this repository's admission rule (inherited from Adva's
    PUBLICATION_BOUNDARY.md) admits public domain only.  The same rule already
    keeps Copernicus DEM out of the tree and in /tmp.  So: raw bytes are read in
    place, derived numbers are recorded with their provenance, and nothing is
    vendored.

Integrity.  Hashing 304 GB would take longer than the rest of this work, so each
file is fingerprinted by its size, its mtime and the SHA-256 of its first and
last mebibyte.  That is not a full digest and the catalogue says so; it is enough
to notice a file that changed, was truncated, or was replaced.

Structure.  One file per day per variable, NetCDF-4, read here through GDAL
(rasterio) because the usual Python readers are not installed and the network is
not always available.  Band metadata carries the packing, the level and the time,
so the catalogue records those too -- a reader should not have to open a file to
learn that temperature is packed int16 with an offset of 251.456 K.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import warnings

ROOT = "/Volumes/Newsmy"
CATEGORIES = ("单层变量", "多层变量")
CHUNK = 1024 * 1024


def partial_digest(path: str, size: int) -> str:
    """SHA-256 over the first and last mebibyte, tagged so it cannot be mistaken
    for a whole-file digest."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        digest.update(handle.read(CHUNK))
        if size > 2 * CHUNK:
            handle.seek(size - CHUNK)
            digest.update(handle.read(CHUNK))
        else:
            handle.seek(0)
            digest.update(handle.read())
    return "partial-1MiB-ends:" + digest.hexdigest()[:32]


def probe_netcdf(path: str) -> dict:
    """Dimensions, bands, packing and levels, via GDAL."""
    import rasterio
    warnings.filterwarnings("ignore")
    out: dict = {}
    try:
        with rasterio.open(path) as dataset:
            subs = dataset.subdatasets
            if subs:
                out["subdatasets"] = [s.rsplit(":", 1)[-1] for s in subs]
                with rasterio.open(subs[0]) as inner:
                    out.update(bands=inner.count, height=inner.height,
                               width=inner.width)
                    out["band_metadata"] = _band_tags(inner, 1)
                return out
            out.update(bands=dataset.count, height=dataset.height,
                       width=dataset.width)
            out["band_metadata"] = _band_tags(dataset, 1)
            if "level" in dataset.tags():
                levels = []
                for band in range(1, min(dataset.count, 600) + 1):
                    value = dataset.tags(band).get("NETCDF_DIM_level")
                    if value is not None and value not in levels:
                        levels.append(int(value))
                    if len(levels) > 1 and value == levels[0] and band > 1:
                        break
                out["levels_hpa"] = levels
    except Exception as error:  # noqa: BLE001 - a catalogue reports failures
        out["error"] = f"{type(error).__name__}: {str(error)[:120]}"
    return out


def _band_tags(dataset, band: int) -> dict:
    tags = dataset.tags(band)
    keep = {}
    for key, value in tags.items():
        if any(s in key for s in ("NETCDF_DIM", "scale_factor", "add_offset",
                                  "units", "long_name", "_FillValue")):
            keep[key] = value
    return keep


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="docs/era5-catalogue.json")
    ap.add_argument("--skip-digest", action="store_true")
    ap.add_argument("--probe-one-per-variable", action="store_true", default=True)
    args = ap.parse_args()

    if not os.path.isdir(ROOT):
        print(f"REFUSED the drive is not mounted at {ROOT}")
        return 1

    entries = []
    for category in CATEGORIES:
        base = os.path.join(ROOT, category)
        if not os.path.isdir(base):
            continue
        for variable in sorted(os.listdir(base)):
            directory = os.path.join(base, variable)
            if not os.path.isdir(directory):
                continue
            files = sorted(f for f in os.listdir(directory) if f.endswith(".nc"))
            dates = sorted(set(re.findall(r"(\d{8})", " ".join(files))))
            total = 0
            per_file = []
            for index, name in enumerate(files):
                path = os.path.join(directory, name)
                size = os.path.getsize(path)
                total += size
                record = {"file": name, "bytes": size,
                          "mtime": int(os.path.getmtime(path))}
                if not args.skip_digest:
                    record["digest"] = partial_digest(path, size)
                if index == 0 and args.probe_one_per_variable:
                    record["structure"] = probe_netcdf(path)
                per_file.append(record)
            entries.append({
                "category": category, "variable": variable,
                "files": len(files), "bytes": total,
                "first_date": dates[0] if dates else None,
                "last_date": dates[-1] if dates else None,
                "per_file": per_file,
            })
            print(f"  {category}/{variable:<32} {len(files):>3} files "
                  f"{total / 1e9:>7.2f} GB", flush=True)

    catalogue = {
        "source": {
            "holder": "ECMWF",
            "product": "ERA5",
            "path": ROOT,
            "grid": "0.25 degree regular lat/lon, 721 x 1440",
            "period": "2024-01-01 .. 2024-01-31",
            "format": "NetCDF-4, one file per day per variable",
        },
        "licence": {
            "name": "Copernicus Licence / ERA5 terms of use",
            "public_domain": False,
            "consequence": "raw bytes are NOT vendored into this repository; they "
                           "are read in place from the drive. Derived numbers may "
                           "be recorded with this provenance attached.",
            "admission_rule": "Adva PUBLICATION_BOUNDARY.md admits public domain "
                              "only; CC BY and Apache are not a public-domain basis.",
        },
        "integrity": {
            "method": "size + mtime + SHA-256 of the first and last MiB",
            "is_full_digest": False,
            "note": "enough to notice a changed, truncated or replaced file; not "
                    "enough to certify a bit-exact copy.",
        },
        "totals": {
            "variables": len(entries),
            "files": sum(e["files"] for e in entries),
            "bytes": sum(e["bytes"] for e in entries),
        },
        "entries": entries,
    }

    out = ROOT_PATH = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), args.out) if not args.out.startswith("/") else args.out
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(catalogue, handle, indent=1, ensure_ascii=False)
        handle.write("\n")
    print(f"\n{len(entries)} variables, {catalogue['totals']['files']} files, "
          f"{catalogue['totals']['bytes'] / 1e9:.1f} GB")
    print(f"wrote {out}")
    print("\nNOT ESTABLISHED: that these bytes equal what ECMWF served. A partial")
    print("digest cannot certify that, and no download record was supplied.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
