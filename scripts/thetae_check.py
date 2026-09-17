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


from bolton import bolton_theta_e, moisture_from_rh  # noqa: F401




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
