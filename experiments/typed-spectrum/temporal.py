"""Joint spatial-mode/time-frequency coordinates; no temporal predictor.

For a real cosine/sine harmonic pair use C=a_real+i*a_imag. With this
convention eastward rigid transport gives C(t)=C(0)*exp(i*m*Omega*t), so the
standard FFT peak is at +m*Omega. This C is not the conventional complex-Y
coefficient (which uses the conjugate convention).
"""
import numpy as np


def paired_modes(coefficients, labels):
    coefficients = np.asarray(coefficients)
    if coefficients.ndim != 2 or coefficients.shape[1] != len(labels) or not np.isfinite(coefficients).all():
        raise ValueError("Expected finite time x harmonic coefficients")
    groups = {}
    for index, label in enumerate(labels):
        key = (label.get("family", "scalar"), label["l"], label["m"])
        if label["phase"] in groups.setdefault(key, {}):
            raise ValueError("Repeated harmonic coordinate")
        groups[key][label["phase"]] = index
    series, modes = [], []
    for (family, l, m), indices in groups.items():
        if set(indices) != ({"real"} if m == 0 else {"real", "imag"}):
            raise ValueError("Incomplete cosine/sine pair")
        c = coefficients[:, indices["real"]].astype(complex)
        if m:
            c += 1j*coefficients[:, indices["imag"]]
        series.append(c)
        modes.append({"family": family, "l": l, "m": m})
    return np.stack(series, axis=1), modes


def time_spectrum(series, times, *, window="hann", remove_mean=True):
    """Two-sided frequency in cycles per supplied time unit, with retained phase.

    Regular sampling is required. NaNs/gaps are not interpolated. Frequency
    resolution and Nyquist are sampling properties, not detected physical periods.
    No taper is used for the analytic integer-period experiment; Hann is available
    for finite observed windows. All samples are the caller's declared time window.
    """
    series, times = np.asarray(series), np.asarray(times, dtype=float)
    if series.ndim != 2 or times.ndim != 1 or len(times) != len(series) or len(times) < 4:
        raise ValueError("Expected time x modes and at least four times")
    if not np.isfinite(series).all() or not np.isfinite(times).all():
        raise ValueError("Missing values need an explicit observation model")
    steps = np.diff(times)
    dt = steps[0]
    if dt <= 0 or not np.allclose(steps, dt, rtol=1e-9, atol=abs(dt)*1e-10):
        raise ValueError("Time sampling must be increasing and uniform")
    if window not in {"hann", "rectangular"}:
        raise ValueError("Unknown window")
    taper = np.hanning(len(times)) if window == "hann" else np.ones(len(times))
    mean = series.mean(axis=0) if remove_mean else np.zeros(series.shape[1], dtype=series.dtype)
    transformed = np.fft.fftshift(np.fft.fft((series-mean)*taper[:, None], axis=0)/len(times), axes=0)
    return {
        "frequency": np.fft.fftshift(np.fft.fftfreq(len(times), d=dt)),
        "amplitude": transformed, "bin_power": abs(transformed)**2/np.mean(taper**2),
        "mean": mean, "frequency_resolution": 1/(len(times)*dt),
        "nyquist": .5/dt, "window": window,
        "power_meaning": "window-weighted mean-square power per frequency bin; not a probability or forecast score",
    }
