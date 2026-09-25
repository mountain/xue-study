"""One finite exact period-three example and one analytic spacetime-spectrum check.

Limits: one 3-state rational orbit, powers only through 3, 128 synthetic times,
degree 6, 24x48 quadrature points. No search, fit to weather, or Adva identities.
"""
from fractions import Fraction as Q
import argparse
import json
from pathlib import Path
import numpy as np

from spectrum import SphereBasis, gaussian_grid
from temporal import paired_modes, time_spectrum


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    M = ((Q(-1, 2), Q(-3, 2)), (Q(1, 2), Q(-1, 2)))
    I = ((Q(1), Q(0)), (Q(0), Q(1)))
    mul = lambda A, B: tuple(tuple(sum(A[i][k]*B[k][j] for k in range(2)) for j in range(2)) for i in range(2))
    mv = lambda v: tuple(sum(M[i][j]*v[j] for j in range(2)) for i in range(2))
    power = lambda v: v[0]**2+3*v[1]**2
    G = ((Q(1), Q(0)), (Q(0), Q(3)))
    MT = tuple(zip(*M))
    assert mul(mul(M, M), M) == I
    assert mul(mul(MT, G), M) == G
    orbit = [(Q(1), Q(0))]
    for _ in range(3):
        orbit.append(mv(orbit[-1]))
    assert len(set(orbit[:3])) == 3 and orbit[3] == orbit[0]
    assert all(power(v) == 1 for v in orbit)
    assert orbit[1][0] == orbit[2][0] and mv(orbit[1])[0] != mv(orbit[2])[0]
    for s in orbit[:3]:
        for t in orbit[:3]:
            difference = tuple(x-y for x, y in zip(s, t))
            assert power(mv(difference)) == power(difference)
    # f=A(x²-y²)+2*sqrt(3)*B*x*y is entirely l=2. M advances its
    # phase by 2*pi/3 and preserves its L2 norm. The state domain is an ellipse,
    # not a real interval with a closed scalar return law.
    r, weights = gaussian_grid(24, 48)
    basis = SphereBasis(r, 6)
    times = np.arange(128)*2*np.pi/128
    x = np.cos(times[:, None])*r[:, 0]+np.sin(times[:, None])*r[:, 1]
    y = -np.sin(times[:, None])*r[:, 0]+np.cos(times[:, None])*r[:, 1]
    fields = 280+3*x+2*(x*x-y*y)+.7*x*r[:, 2]
    gram = basis.scalar.T@(weights[:, None]*basis.scalar)
    coefficients = np.linalg.solve(gram, (fields@(weights[:, None]*basis.scalar)).T).T
    series, modes = paired_modes(coefficients, basis.scalar_labels)
    spectrum = time_spectrum(series, times, window="rectangular")
    results = []
    for l, m, expected in [(1, 1, 1.), (2, 1, 1.), (2, 2, 2.)]:
        index = next(i for i, label in enumerate(modes) if label["l"] == l and label["m"] == m)
        peak = int(np.argmax(spectrum["bin_power"][:, index]))
        omega = float(2*np.pi*spectrum["frequency"][peak])
        fraction = float(spectrum["bin_power"][peak, index]/spectrum["bin_power"][:, index].sum())
        assert abs(omega-expected) < 1e-10 and fraction > 1-1e-10
        results.append({"l": l, "m": m, "angular_frequency": omega, "peak_power_fraction": fraction})
    # Parseval: paired real coefficients retain their squared norm.
    anomaly = series-series.mean(axis=0)
    parseval = float(np.max(abs(np.mean(abs(anomaly)**2, axis=0)-spectrum["bin_power"].sum(axis=0))))
    assert parseval < 1e-10
    try:
        irregular = times.copy(); irregular[10] += .01
        time_spectrum(series, irregular)
        raise AssertionError("Irregular-time control was accepted")
    except ValueError:
        pass
    # Finite samples cannot distinguish aliases without a band limit assumption.
    dt = times[1]-times[0]
    alias_error = float(np.max(abs(np.exp(1j*times)-np.exp(1j*(1+2*np.pi/dt)*times))))
    assert alias_error < 1e-10
    record = {
        "scope": "finite exact algebra and synthetic Fourier calibration only",
        "period_three": {"matrix": [[str(x) for x in row] for row in M],
                         "orbit": [[str(x) for x in row] for row in orbit],
                         "M_cubed_is_identity": True, "preserves_metric_diag_1_3": True,
                         "scalar_A_projection_fails_descent": True,
                         "power_projection_descends_to_identity": True,
                         "spatial_field": "A*(x*x-y*y)+2*sqrt(3)*B*x*y, degree l=2 only",
                         "not_a_sharkovsky_interval_witness": True},
        "spacetime": {"sample_count": len(times), "time_units": "dimensionless",
                      "omega_driver": 1, "modes": results, "parseval_error": parseval,
                      "irregular_times_refused": True, "alias_pair_max_difference": alias_error,
                      "conclusion": "Time frequency tracks m*Omega for this transport law, not spatial degree l; general atmosphere may have damping, drift and broad spectra."},
    }
    args.output.write_text(json.dumps(record, indent=2)+"\n")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
