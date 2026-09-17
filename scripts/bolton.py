"""Bolton (1980) equivalent potential temperature, with no dependencies.

Extracted from `thetae_check.py` so that the same implementation can be imported
by checkers that run without xarray, and so that there is exactly one copy of the
formulation in the tree.  `thetae_check.py` imports from here; nothing is
duplicated.

The formulation is Bolton (1980) eq. 43 with its eq. 15 lifting-condensation-level
temperature and its eq. 10 dew point, written here from the published paper: the
leading factor takes the mixing ratio in g/kg, while the parenthetical correction
takes it in kg/kg.

`pressure_hpa` defaults to the 850 hPa the original check was written for, so
existing callers are unaffected.  It is a parameter at all because a sounding
reports the pressure it measured at every level, so the same formulation can be
evaluated at the surface an ascent actually stood on rather than only at a fixed
level.
"""

from __future__ import annotations

import numpy as np

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
