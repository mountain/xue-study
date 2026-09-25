"""Finite annual/perturbation calibration under annual-contract.json."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from temporal import time_spectrum


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    contract_path = Path(__file__).with_name("annual-contract.json")
    contract = json.loads(contract_path.read_text())
    nt = contract["time"]["years"]*contract["time"]["samples_per_year"]
    t = np.arange(nt)/contract["time"]["samples_per_year"]
    theta = 2*np.pi*t
    omega = 2*np.pi/contract["perturbation"]["period_years"]
    eps = contract["perturbation"]["amplitude"]
    baseline = np.cos(theta)+.3*np.sin(2*theta)
    cases = {
        "additive": baseline+eps*np.cos(omega*t),
        "amplitude": baseline+eps*np.cos(omega*t)*np.cos(theta),
        "phase": np.cos(theta+eps*np.cos(omega*t))+.3*np.sin(2*theta),
    }
    design = np.column_stack([np.ones(nt)]+[v for k in range(1, 3)
                            for v in (np.cos(k*theta), np.sin(k*theta))])
    train = t < contract["seasonal_fit"]["training_years"]
    model = np.linalg.lstsq(design[train], cases["additive"][train], rcond=None)[0]
    fitted = design@model
    fit_error = float(np.max(abs(fitted-baseline)))
    assert fit_error < contract["tolerance"]
    # Poison held-out samples: a training-only seasonal fit must not change.
    poisoned = cases["additive"].copy()
    poisoned[~train] = 1e9
    other = np.linalg.lstsq(design[train], poisoned[train], rcond=None)[0]
    assert np.array_equal(model, other)
    results = {}
    for name, values in cases.items():
        spec = time_spectrum((values-baseline)[:, None], t, window="rectangular")
        positive = np.flatnonzero(spec["frequency"] > 0)
        selected = positive[np.argsort(spec["bin_power"][positive, 0])[-5:][::-1]]
        peaks = [{"cycles_per_year": float(spec["frequency"][k]),
                  "sinusoid_amplitude": float(2*abs(spec["amplitude"][k, 0]))}
                 for k in selected if 2*abs(spec["amplitude"][k, 0]) > 1e-10]
        if name == "additive":
            assert len(peaks) == 1 and peaks[0]["cycles_per_year"] == .25
            assert abs(peaks[0]["sinusoid_amplitude"]-eps) < 1e-10
        elif name == "amplitude":
            assert {p["cycles_per_year"] for p in peaks} == {.75, 1.25}
            assert all(abs(p["sinusoid_amplitude"]-eps/2) < 1e-10 for p in peaks)
        results[name] = {"anomaly_peaks": peaks}
    phase_linear = baseline-eps*np.cos(omega*t)*np.sin(theta)
    phase_error = float(np.max(abs(cases["phase"]-phase_linear)))
    assert phase_error <= eps**2/2+1e-12
    # Signed temporal frequency retains the propagation direction of a pair.
    negative = time_spectrum(np.exp(-1j*theta)[:, None], t, window="rectangular")
    assert negative["frequency"][np.argmax(negative["bin_power"][:, 0])] == -1
    # Parseval with Hann taper must use the taper-weighted time-domain power.
    hann = time_spectrum(cases["additive"][:, None], t, window="hann")
    taper = np.hanning(nt)
    expected = np.mean(((cases["additive"]-cases["additive"].mean())*taper)**2)/np.mean(taper**2)
    hann_error = float(abs(hann["bin_power"].sum()-expected))
    assert hann_error < 1e-10
    gamma = contract["floquet_scalar_example"]["gamma_per_year"]
    kappa = contract["floquet_scalar_example"]["kappa_per_year"]
    solution = lambda s: np.exp(-gamma*s+kappa/(2*np.pi)*np.sin(2*np.pi*s))
    annual_multiplier = float(np.exp(-gamma))
    ratio_error = float(np.max(abs(solution(t+1)/solution(t)-annual_multiplier)))
    assert ratio_error < 1e-10
    record = {"scope": contract["scope"],
              "contract_sha256": hashlib.sha256(contract_path.read_bytes()).hexdigest(),
              "sample_count": nt, "training_samples": int(train.sum()),
              "seasonal_fit_max_error": fit_error, "heldout_poison_does_not_change_fit": True,
              "cases": results, "phase_first_order_max_error": phase_error,
              "phase_first_order_error_bound": eps**2/2,
              "negative_frequency_retained": True, "hann_parseval_error": hann_error,
              "scalar_floquet": {"annual_multiplier": annual_multiplier,
                                 "same_phase_annual_ratio_max_error": ratio_error},
              "note": "A pure annual baseline can be predicted without predicting anomalies; none of these synthetic checks establishes weather forecast skill."}
    args.output.write_text(json.dumps(record, indent=2)+"\n")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
