"""Check live ARCO metadata; optionally read ONE historical frame per field.

This does not collect a training history or run a learner. No silent replacement
of absent relative humidity. Raw sample arrays must stay outside the repository.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from urllib.request import urlopen

from variables import FIELDS, STATIC_FIELDS, cds_monthly_requests

BUCKET = "https://storage.googleapis.com/gcp-public-data-arco-era5/ar/"
STORES = {
    "arco_1p5deg_6h": BUCKET + "1959-2022-6h-240x121_equiangular_with_poles_conservative.zarr",
    "arco_0p25deg_1h": BUCKET + "full_37-1h-0p25deg-chunk-1.zarr-v3",
}


def canonical_unit(unit: str) -> str:
    unit = unit.replace("**", "").replace("^", "").strip()
    return {"(0 - 1)": "1", "m of water equivalent": "m water equivalent"}.get(unit, unit)


def audit() -> dict:
    result = {"checked_at": datetime.now(timezone.utc).isoformat(),
              "scope": "array metadata; pressure coordinate values require a data read",
              "training_performed": False, "sources": {}, "fields": {}}
    all_meta = {}
    for source, url in STORES.items():
        with urlopen(url + "/.zmetadata", timeout=60) as response:
            raw = response.read()
        meta = json.loads(raw)["metadata"]
        all_meta[source] = meta
        result["sources"][source] = {
            "url": url, "metadata_sha256": hashlib.sha256(raw).hexdigest(),
            "metadata_bytes": len(raw), "attributes": meta.get(".zattrs", {}),
        }
    for field in (*FIELDS, *STATIC_FIELDS):
        options = {}
        for source, meta in all_meta.items():
            arr = meta.get(field.arco_name + "/.zarray")
            if arr is None:
                options[source] = {"array_present": False}
                continue
            attrs = meta[field.arco_name + "/.zattrs"]
            units = attrs.get("units", "")
            dims = attrs["_ARRAY_DIMENSIONS"]
            options[source] = {
                "array_present": True, "units": units,
                "units_match": canonical_unit(units) == field.units,
                "dimensions": dims, "shape": arr["shape"], "chunks": arr["chunks"],
                "uncompressed_chunk_bytes": math.prod(arr["chunks"]) * int(arr["dtype"][-1]),
                "pressure_level_coordinate_read": False if field.level_hpa else None,
            }
        result["fields"][field.code] = {**field.record(), "sources": options}
    result["missing_from_both_arco_stores"] = [
        c for c, f in result["fields"].items()
        if not any(s["array_present"] for s in f["sources"].values())]
    result["unit_errors"] = [
        f"{code}:{source}" for code, f in result["fields"].items()
        for source, s in f["sources"].items() if s.get("units_match") is False]
    return result


def sample(report: dict, date: str, output: Path) -> dict:
    import numpy as np
    import xarray as xr

    repository = Path(__file__).resolve().parents[2]
    output = output.expanduser().resolve()
    if output.is_relative_to(repository):
        raise ValueError("Raw ERA5 samples must be stored outside the repository")
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    result = {"date": date, "purpose": "source read smoke check, not monthly training",
              "files": [], "unavailable": report["missing_from_both_arco_stores"]}
    selected = {s: [] for s in STORES}
    for field in (*FIELDS, *STATIC_FIELDS):
        for source in STORES:  # Prefer bounded low-resolution chunks for this sample.
            if report["fields"][field.code]["sources"][source]["array_present"]:
                selected[source].append(field)
                break
    for source, fields in selected.items():
        if not fields:
            continue
        ds = xr.open_zarr(STORES[source], chunks=None, consolidated=True)
        try:
            # Exact time and level selections: no nearest-match substitution.
            one = ds.sel(time=np.datetime64(date))
            arrays = {"latitude": one.latitude.values, "longitude": one.longitude.values}
            stats, loaded = {}, {}
            for field in fields:
                if field.arco_name not in loaded:
                    loaded[field.arco_name] = one[field.arco_name].load()
                data = loaded[field.arco_name]
                if field.level_hpa is not None:
                    data = data.sel(level=field.level_hpa)
                value = np.asarray(data.transpose("latitude", "longitude"), dtype=np.float32)
                arrays[field.code] = value
                finite = np.isfinite(value)
                if not finite.any():
                    raise ValueError(f"All sample values missing for {field.code}")
                stats[field.code] = {
                    "shape": list(value.shape), "finite_fraction": float(finite.mean()),
                    "minimum": float(value[finite].min()), "maximum": float(value[finite].max()),
                    "source_units": data.attrs.get("units"),
                    "level_hpa": field.level_hpa,
                    "masked": False, "radiation_converted": False,
                }
            path = output / (source + ".npz")
            np.savez_compressed(path, **arrays)
            result["files"].append({"source": STORES[source], "path": str(path),
                                    "bytes": path.stat().st_size,
                                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                                    "fields": stats})
        finally:
            ds.close()
    (output / "receipt.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--sample-date", help="Exact historical UTC time, e.g. 2020-01-01T00:00")
    parser.add_argument("--sample-output", type=Path)
    parser.add_argument("--request-year", type=int, default=2020)
    args = parser.parse_args()
    if bool(args.sample_date) != bool(args.sample_output):
        parser.error("--sample-date and --sample-output must be used together")
    report = audit()
    report["cds_monthly_plan"] = {"submitted": False,
        "requests": cds_monthly_requests(args.request_year, list(range(1, 13))),
        "note": "Static masks requested separately. Credentials/licence access not tested."}
    if report["unit_errors"]:
        raise ValueError(report["unit_errors"])
    if args.sample_date:
        report["sample"] = sample(report, args.sample_date, args.sample_output)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(args.report),
                      "missing_from_arco": report["missing_from_both_arco_stores"],
                      "unit_errors": report["unit_errors"],
                      "sample_files": len(report.get("sample", {}).get("files", [])),
                      "training_performed": False}))


if __name__ == "__main__":
    main()
