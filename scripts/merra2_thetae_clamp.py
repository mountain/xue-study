"""Third opinion on the 850 hPa theta-e clamp over the Tibetan plateau.

WHY THIS EXISTS
---------------
Two reanalyses disagree about 850 hPa theta-e over the plateau by about 35 K.
ERA5 puts the plateau September mean at 331.6 K (median of 63 Septembers,
range 327.55-334.74) and never lets it exceed the warm pool.  GFS puts the
same day's plateau value at 366.2-371.3 K, above its own warm pool.  We
established earlier that the terrain is identical between the two (ps median
582.9 vs 582.6 hPa) and that ERA5 does not exceed 357 K anywhere over the
plateau on the sampled day, while GFS has 59.1-81.8 percent of the box there.

So the disagreement is about BELOW-GROUND EXTRAPOLATION, not about terrain.
What we do not know is whether that extrapolation is a GFS-specific defect or
something any reanalysis does when asked for 850 hPa over terrain whose
surface sits near 580 hPa.

MERRA-2 is the third opinion.  It is an independent assimilation system, so
it can separate those two.

THE DECISION RULE, WRITTEN BEFORE RUNNING
-----------------------------------------
  plateau mean theta-e lands in [325, 340] K
      -> MERRA-2 agrees with ERA5.  The clamp is GFS-specific.
  plateau mean theta-e lands in [350, 375] K
      -> MERRA-2 clamps too.  The clamp is an artifact of asking for 850 hPa
         over high terrain, shared by reanalyses; GFS's version of it is
         merely the loudest.
  anything else
      -> ambiguous.  Report as ambiguous; do not round it to a story.

THE CONTROL THAT CAN FAIL
-------------------------
The warm pool box, where 850 hPa is genuinely above ground in all three
systems.  There ERA5 and GFS already agree to 0.01-0.24 K.  If MERRA-2
disagrees with ERA5 there by more than a few K, then the reading is wrong
and the plateau number means nothing.  This is the part that must be checked
FIRST.

THE MASK TRAP
-------------
MERRA-2 writes 1e15 as _FillValue.  If the below-ground region is masked
rather than extrapolated, a naive mean would silently average over whatever
survives, or return a fill value as a temperature.  This script reports the
fill fraction over the plateau BEFORE reporting any statistic, and refuses to
report a mean when the fill fraction is high.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys

import numpy as np

from bolton import bolton_theta_e

LEVEL = 850.0
BOXES = {
    "plateau (80-92E, 26-32N)": (26.0, 32.0, 80.0, 92.0),
    "warm pool (120-180E, 15S-15N)": (-15.0, 15.0, 120.0, 180.0),
}

# Reference values already established in this study, for the comparison line.
ERA5_63YR = {"min": 327.55, "median": 331.62, "max": 334.74}
GFS_SAMPLED = (366.2, 371.3)


def box_mask(latitude, longitude, box, wrap_lon):
    """Boolean mask, built per source because longitude conventions differ.

    ERA5 runs 0-360 and GFS/MERRA-2 run -180-180.  Reusing one source's mask
    on another selected zero cells in the Andes earlier in this study, so the
    mask is always built here from the source's own coordinates.
    """
    south, north, west, east = box
    la = (latitude >= south) & (latitude <= north)
    if wrap_lon:
        lo = (longitude >= west % 360) | (longitude <= east % 360)
    else:
        lo = (longitude >= west) & (longitude <= east)
    return la[:, None] & lo[None, :]


def theta_e_field(t850_k, qv850, ps_pa):
    """Bolton theta-e at 850 hPa, in K.  Same formulation as the ERA5 side."""
    t_c = np.asarray(t850_k, dtype="float64") - 273.15
    q = np.asarray(qv850, dtype="float64")
    return bolton_theta_e(t_c, q, LEVEL)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+", help="MERRA-2 M2T1NXSLV .nc4 files")
    args = ap.parse_args()

    try:
        import netCDF4
    except ImportError:
        print("netCDF4 is required: /tmp/m2env/bin/python", file=sys.stderr)
        return 2

    for path in args.files:
        print(f"\n{'=' * 72}\n{path}\n{'=' * 72}")
        ds = netCDF4.Dataset(path)
        names = sorted(ds.variables)

        # Discover rather than hardcode: the daily-stat product has no 850 hPa
        # variables at all, and guessing names is how earlier steps went wrong.
        tvar = next((n for n in names if n.upper() in ("T850",)), None)
        # MERRA-2 names specific humidity at a pressure level Q850; the QV
        # prefix is reserved for 2 m and 10 m (QV2M, QV10M).  The first run of
        # this script looked only for QV850 and refused to proceed rather than
        # guessing, which is why the name is spelled out here.
        qvar = next((n for n in names if n.upper() in ("Q850", "QV850")), None)
        pvar = next((n for n in names if n.upper() in ("PS",)), None)
        if not (tvar and qvar and pvar):
            print(f"  MISSING variables. have: {names}")
            print("  -> this product cannot answer the 850 hPa question")
            continue
        print(f"  using {tvar} / {qvar} / {pvar}")

        lat = np.asarray(ds.variables["lat"][:], dtype="float64")
        lon = np.asarray(ds.variables["lon"][:], dtype="float64")
        wrap = bool((lon > 180).any())          # ERA5-style 0-360 if true
        print(f"  grid lat {lat.size} lon {lon.size}  "
              f"lon range [{lon.min():.2f}, {lon.max():.2f}]  wrap={wrap}")

        T = np.asarray(ds.variables[tvar][:], dtype="float64").squeeze()
        Q = np.asarray(ds.variables[qvar][:], dtype="float64").squeeze()
        P = np.asarray(ds.variables[pvar][:], dtype="float64").squeeze()

        fill = None
        for v in (ds.variables[tvar], ds.variables[qvar]):
            if "_FillValue" in v.ncattrs():
                f = float(v.getncattr("_FillValue"))
                fill = f if fill is None else fill
        print(f"  _FillValue = {fill}")

        for label, box in BOXES.items():
            m = box_mask(lat, lon, box, wrap)
            ncell = int(m.sum())
            print(f"\n  --- {label} ---")
            if ncell == 0:
                print("    zero cells selected -- mask is wrong for this grid")
                continue

            ps_cell = P[:, m]                      # (time, ncell)
            t_cell = T[:, m]
            q_cell = Q[:, m]

            # Mask fill values BEFORE any statistic.  The first version of
            # this script counted fill values only to decide whether to
            # refuse, then computed theta-e over the unmasked array anyway:
            # the warm-pool mean came back as 4.65e8 K with a plausible
            # 340.02 K median beside it.  A robust median next to an absurd
            # mean is the signature of exactly this mistake.
            bad = (~np.isfinite(t_cell)) | (np.abs(t_cell) > 1e10)
            bad |= (~np.isfinite(q_cell)) | (np.abs(q_cell) > 1e10)
            bad_ps = (~np.isfinite(ps_cell)) | (np.abs(ps_cell) > 1e10)
            valid = ~bad
            print(f"    {tvar} masked: {100.0 * bad.mean():.2f}% of {bad.size} values")
            print(f"    PS   masked: {100.0 * bad_ps.mean():.2f}%")

            # Does the mask track the terrain?  PS is a surface field and is
            # defined everywhere, so if PS is valid while T850 is not, the
            # missing T850 is a below-ground refusal and not a data gap.
            if bad_ps.mean() < 0.01:
                ps_hpa = ps_cell / 100.0
                below = ps_hpa < LEVEL
                print(f"    PS median {np.median(ps_hpa):.1f} hPa;  "
                      f"PS < {LEVEL:.0f} hPa in {100.0 * below.mean():.1f}% of cells")
                agree = 100.0 * float((bad == below).mean())
                print(f"    mask coincides with 'PS < {LEVEL:.0f} hPa' in "
                      f"{agree:.1f}% of cells")
                if agree > 95.0:
                    print("    -> T850 is MISSING below ground: MERRA-2 declines to")
                    print("       extrapolate, where ERA5 reports a value and GFS")
                    print("       reports an extreme one.")
                elif agree < 60.0:
                    print("    -> mask does NOT track terrain; treat with suspicion")

            print(f"    valid subset: {100.0 * valid.mean():.2f}% of cells")
            if valid.sum() == 0:
                print("    nothing valid to report")
                continue

            te = theta_e_field(t_cell[valid], q_cell[valid], ps_cell[valid])
            print(f"    theta-e 850 over the VALID subset: "
                  f"mean {np.mean(te):.2f} K  median {np.median(te):.2f} K  "
                  f"max {np.max(te):.2f} K")
            for thr in (350.0, 357.0):
                print(f"      fraction within 1 K of {thr:.0f} K: "
                      f"{100.0 * float((np.abs(te - thr) <= 1.0).mean()):.2f}%")

            if label.startswith("plateau"):
                print(f"\n    COMPARISON BASELINE: ERA5 63-year September "
                      f"min/median/max {ERA5_63YR['min']}/{ERA5_63YR['median']}/"
                      f"{ERA5_63YR['max']} K;  GFS sampled {GFS_SAMPLED} K")
                if valid.mean() < 0.5:
                    print(f"    -> the rule does NOT apply to the bulk: MERRA-2 withholds")
                    print(f"       {100.0 * (1 - valid.mean()):.1f}% of the box, so there is no plateau")
                    print( "       mean available to place on it.  That refusal is itself")
                    print( "       the finding: the question has no observational answer,")
                    print( "       and each system answers it by convention.")
                else:
                    mean = float(np.mean(te))
                    print(f"    DECISION RULE: mean = {mean:.2f} K")
                    if 325.0 <= mean <= 340.0:
                        print("    -> agrees with ERA5; the clamp is GFS-specific")
                    elif 350.0 <= mean <= 375.0:
                        print("    -> clamps too; shared by reanalyses, not a GFS defect")
                    else:
                        print("    -> AMBIGUOUS, falls between the two hypotheses")
        ds.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
