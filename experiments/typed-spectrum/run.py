"""Run the fixed representation experiment and write reviewable artifacts."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
from scipy.linalg import expm

from spectrum import (SphereBasis, advection_operator, fit, gaussian_grid,
                      latlon_points, local_tensor_response, local_vector_response,
                      recover_local_tensor, recover_local_vector, response)

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("basic_variables", HERE.parent / "basic-state/variables.py")
variables = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = variables
spec.loader.exec_module(variables)


def synthetic(contract):
    points, weights = gaussian_grid(*contract["synthetic_grid"])
    b = SphereBasis(points, contract["degree"])
    v = np.array([1.3, -.5, 2.1])
    tensor = np.array([[2., .3, -.4], [.3, -1., .2], [-.4, .2, .5]])
    wind = b.cartesian_to_tangent(np.cross([0, 0, 1], points))
    wf = fit(b.vector, wind, weights)
    _, curl = b.wind_channels(wf.coefficients)
    initial = 280+3*points[:, 0]+2*(points[:, 0]**2-points[:, 1]**2)
    sf = fit(b.scalar, initial, weights)
    operator = advection_operator(b, wind, weights, radius=1)
    time = np.pi/4
    future_c = expm(time*operator)@sf.coefficients
    future = b.scalar@future_c
    x0 = np.cos(time)*points[:, 0]+np.sin(time)*points[:, 1]
    y0 = -np.sin(time)*points[:, 0]+np.cos(time)*points[:, 1]
    exact = 280+3*x0+2*(x0*x0-y0*y0)
    # The inversion of only the original even rotational response sets all
    # unobserved channels to zero. It cannot infer Omega from this snapshot.
    retained = np.array([label["family"] == "rotation" and label["l"] % 2 == 0
                         for label in b.vector_labels])
    truncated_wind = np.einsum("ncp,p->nc", b.vector, wf.coefficients*retained)
    omitted = b.scalar@(expm(time*advection_operator(b, truncated_wind, weights, radius=1))@sf.coefficients)
    error = {
        "local_vector_inverse": float(np.max(abs(recover_local_vector(local_vector_response(v, points), points, weights)-v))),
        "local_tensor_inverse": float(np.max(abs(recover_local_tensor(local_tensor_response(tensor, points), points, weights)-tensor))),
        "scalar_gram": float(np.max(abs(b.scalar.T@(weights[:, None]*b.scalar)-np.eye(49)))),
        "transport_against_analytic_max": float(np.max(abs(future-exact))),
        "transport_mean_drift": float(abs(future_c[0]-sf.coefficients[0])),
        "transport_anomaly_power_drift": float(abs(np.sum(future_c[1:]**2)-np.sum(sf.coefficients[1:]**2))),
        "original_even_wind_response_max": float(np.max(abs(response(curl, points, b.degree, kernel="even")))),
    }
    if max(error.values()) > contract["analytic_tolerance"]:
        raise AssertionError(error)
    report = {"scope": "analytic unit-sphere example, not weather prediction",
              "time_units": "dimensionless", "time": float(time), "omega": 1.,
              "error_checks": error, "full_transport_rmse": float(np.sqrt(np.sum(weights*(future-exact)**2))),
              "omitted_driver_transport_rmse": float(np.sqrt(np.sum(weights*(omitted-exact)**2))),
              "initial_anomaly_power": float(np.sum(sf.coefficients[1:]**2)),
              "future_anomaly_power": float(np.sum(future_c[1:]**2)),
              "interpretation": "Identical initial even wind responses can drive different future scalar fields. This is not a proof that an even-spectrum model with scalar history must fail."}
    arrays = {"scalar_initial": sf.coefficients, "scalar_future": future_c,
              "wind_coefficients": wf.coefficients, "transport_operator": operator}
    return report, arrays


def real_snapshot(contract, input_path):
    with np.load(input_path) as data:
        lat, lon = data["latitude"], data["longitude"]
        keep = abs(lat) < 90
        points = latlon_points(lat[keep], lon)
        b = SphereBasis(points, contract["degree"])
        w = np.broadcast_to(np.cos(np.deg2rad(lat[keep]))[:, None], (int(keep.sum()), len(lon))).ravel().copy()
        w /= w.sum()
        fields = {name: data[name][keep].ravel() for name in data.files if name not in {"latitude", "longitude"}}
    options = dict(relative_ridge=contract["real_fit"]["relative_ridge"],
                   rank_tolerance=contract["real_fit"]["unregularized_rank_tolerance"])
    results, arrays = [], {}
    for code in contract["scalar_codes"]:
        field = variables.BY_CODE[code]
        valid_domain = variables.domain_mask(field, surface_pressure=fields["sp"], land_sea_mask=fields["lsm"])
        if np.ndim(valid_domain) == 0:
            valid_domain = np.full(len(points), bool(valid_domain))
        f = fit(b.scalar, fields[code], w, mask=valid_domain, **options)
        row = {"code": code, "kind": "scalar", "units": field.units,
               "role": field.role, "domain": field.domain, **f.diagnostics}
        if code == "sst":
            zero = fit(b.scalar, np.where(f.valid, fields[code], 0), w, **options)
            bad_error = b.scalar[f.valid]@zero.coefficients-fields[code][f.valid]
            row["zero_fill_control_observed_rmse"] = float(np.sqrt(np.sum(w[f.valid]*bad_error**2)/w[f.valid].sum()))
        arrays[code+"_coefficients"] = f.coefficients
        arrays[code+"_gram"] = f.gram
        results.append(row)
    for ucode, vcode in contract["vector_pairs"]:
        field = variables.BY_CODE[ucode]
        mask = variables.domain_mask(field, surface_pressure=fields["sp"])
        wind = np.stack([fields[ucode], fields[vcode]], axis=1)
        f = fit(b.vector, wind, w, mask=mask, **options)
        code = "wind"+str(field.level_hpa)
        div, curl = b.wind_channels(f.coefficients)
        arrays[code+"_coefficients"] = f.coefficients
        arrays[code+"_gram"] = f.gram
        arrays[code+"_angular_divergence"] = div
        arrays[code+"_angular_curl"] = curl
        results.append({"code": code, "components": [ucode, vcode], "kind": "tangent_vector",
                        "units": "m s-1", "domain": field.domain, "role": "state", **f.diagnostics})
    return {"scope": "single-time representation; not temporal training or held-out forecast skill",
            "time": "2020-01-01T00:00:00Z", "input": str(input_path),
            "input_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
            "source_receipt": str(input_path.parent / "receipt.json"),
            "degree": contract["degree"], "scalar_coefficients": len(b.scalar_labels),
            "vector_coefficients_per_level": len(b.vector_labels),
            "exact_poles_excluded": True, "points": len(points),
            "field_results": results, "scalar_labels": b.scalar_labels, "vector_labels": b.vector_labels,
            "not_read": ["ssr", "str", "sd", "r850", "r700"],
            "not_read_reason": "Fine-grid flux/snow need a separate common-grid/domain path; RH absent from the downloaded mirror."}, arrays


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("/home/ubuntu/climatetensor-inputs/era5/basic-state-smoke-20200101/arco_1p5deg_6h.npz"))
    parser.add_argument("--output", type=Path, default=HERE.parents[1] / "archive/typed-spectrum-v1")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Refusing to replace experiment evidence: " + str(args.output))
    contract_path = HERE / "contract.json"
    contract = json.loads(contract_path.read_text())
    synthetic_report, synthetic_arrays = synthetic(contract)
    real_report, real_arrays = real_snapshot(contract, args.input)
    report = {"version": contract["version"], "generated_at": datetime.now(timezone.utc).isoformat(),
              "contract_sha256": hashlib.sha256(contract_path.read_bytes()).hexdigest(),
              "weather_model_trained": False, "native_adva": False, "assimilation": False,
              "synthetic": synthetic_report, "real_snapshot": real_report}
    args.output.mkdir(parents=True)
    np.savez_compressed(args.output / "synthetic.npz", **synthetic_arrays)
    np.savez_compressed(args.output / "era5-representation.npz", **real_arrays)
    (args.output / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False)+"\n")
    template = (HERE / "demo.html").read_text()
    embedded = json.dumps(report, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c")
    (args.output / "demo.html").write_text(template.replace("__REPORT_JSON__", embedded))
    print(json.dumps({"output": str(args.output), "synthetic": synthetic_report,
                      "real_fields": [{k: row[k] for k in ("code", "area_fraction", "observed_domain_rmse", "unregularized_condition")}
                                      for row in real_report["field_results"]]}, indent=2))


if __name__ == "__main__":
    main()
