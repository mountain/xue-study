"""Hold the published theta-e to Bolton (1980), independently of the encoder.

`derive_theta_e` is the one derived quantity with no numerical test: the
suite checks that `thetae850` is registered, published on the right models,
and built from `tmp850` + `spfh850` -- never that the number is right. What
holds the two encoders together there is byte parity, and parity is a
relational guarantee: it says Python and Rust agree, not that either agrees
with the physics.

This computes theta-e from the *published* temperature and relative humidity
(a different input path than the encoder's `spfh850` record) and compares.

Usage: uv run python thetae_check.py <run>
"""

from __future__ import annotations

import sys

import numpy as np
import xarray as xr

PRESSURE_HPA = 850.0


def moisture_from_rh(temperature_c: np.ndarray, relative_humidity: np.ndarray) -> np.ndarray:
    """Specific humidity (kg/kg) from T and RH at a fixed pressure.

    Standard Magnus saturation vapour pressure, the same constants Bolton
    (1980) eq. 10 inverts. The encoder takes `spfh850` straight from the
    GRIB record instead; deriving it here is what makes the check use a
    different input path.
    """
    t = temperature_c + 273.15
    vapour_pressure = (relative_humidity / 100.0) * 6.112 * np.exp(17.67 * temperature_c / (temperature_c + 243.5))
    return 0.622 * vapour_pressure / (PRESSURE_HPA - 0.378 * vapour_pressure)


def bolton_theta_e(temperature_c: np.ndarray, specific_humidity: np.ndarray,
                   pressure_hpa: float | np.ndarray | None = None) -> np.ndarray:
    """Bolton (1980) equivalent potential temperature, in K.

    Eq. 43 with its eq. 15 lifting-condensation-level temperature and its
    eq. 10 dew point, written here from the published formulation: the
    leading factor takes the mixing ratio in g/kg, while the parenthetical
    correction takes it in kg/kg.

    `pressure_hpa` defaults to this script's 850 hPa, so the original check is
    unchanged.  It is a parameter at all because a sounding reports the pressure
    it measured at every level, so the same formulation can be evaluated at the
    surface the ascent actually stood on rather than only at a fixed level.
    """
    pressure = PRESSURE_HPA if pressure_hpa is None else pressure_hpa
    t = temperature_c + 273.15
    q = np.maximum(specific_humidity, 1e-6)
    r = q / (1.0 - q)                                   # mixing ratio, kg/kg
    e = pressure * r / (0.622 + r)                      # vapour pressure, hPa
    ln_e = np.log(e / 6.112)
    dew_point = 243.5 * ln_e / (17.67 - ln_e) + 273.15
    t_lcl = 1.0 / (1.0 / (dew_point - 56.0) + np.log(t / dew_point) / 800.0) + 56.0
    theta = t * (1000.0 / pressure) ** (0.2854 * (1.0 - 0.28 * r))
    r_g = r * 1000.0
    return theta * np.exp((3.376 / t_lcl - 0.00254) * r_g * (1.0 + 0.00081 * r_g))


def main() -> int:
    run = sys.argv[1]
    base = f"https://dataset.ringsaturn.me/xue/gfs.{run}"
    print(f"run {run}")

    fields = {}
    for name in ("tmp850", "rh850", "thetae850"):
        dataset = xr.open_zarr(f"{base}/{name}.half.zarr")
        fields[name] = dataset[name if name != "thetae850" else "thetae850"]
    print(f"  opened 3 stores; grid {fields['tmp850'].shape[1:]} over {fields['tmp850'].shape[0]} frames")

    frames = [0, 40, 80, 120, 160]
    rows = []
    for frame in frames:
        t = np.asarray(fields["tmp850"].isel(time=frame))[::17, ::17]
        rh = np.asarray(fields["rh850"].isel(time=frame))[::17, ::17]
        published = np.asarray(fields["thetae850"].isel(time=frame))[::17, ::17]
        good = np.isfinite(t) & np.isfinite(rh) & np.isfinite(published)
        q = moisture_from_rh(t[good], rh[good])
        mine = bolton_theta_e(t[good], q)
        difference = mine - published[good]
        rows.append((frame, good.sum(), float(np.nanmin(published[good])), float(np.nanmax(published[good])),
                     float(np.mean(difference)), float(np.max(np.abs(difference)))))
        print(f"  frame {frame:3d}: {good.sum():5d} points  published {rows[-1][2]:7.2f}..{rows[-1][3]:7.2f} K"
              f"  bias {rows[-1][4]:+7.3f} K  max|diff| {rows[-1][5]:7.3f} K")

    worst = max(r[5] for r in rows)
    bias = float(np.mean([r[4] for r in rows]))
    print()
    print(f"independent Bolton vs published thetae850:  mean bias {bias:+.3f} K, worst point {worst:.3f} K")
    print("  (the encoder builds q from the GRIB's spfh850 record; this derives it from the")
    print("   published rh850, whose 1 % quantisation alone moves q by about 1 %)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
