"""How does a Tibetan-Plateau-covering heat dome end?  Ask 63 summers.

WHAT IS BEING STUDIED
---------------------
The planetary-scale anticyclone that sits over the plateau in summer is the
South Asian High.  Its classical level is 100-200 hPa -- well above the plateau
surface, unlike the 850 hPa field this study already showed to be an
underground extrapolation clipped at the encoding ceiling.  So this is a study
of the atmosphere, not of a rendering convention.

"Exit scheme" is made into an empirical question with three measurable exit
modes, distinguishable by what changes first as the episode ends:

    displace    the dome's centroid moves (a trough pushed it) -- position
                changes before intensity
    decay       the height falls while the centroid stays put -- intensity
                changes before position
    retreat     the centroid moves SOUTH specifically, which for this feature
                is the seasonal withdrawal rather than a synoptic displacement

THE UNIT AND THE THRESHOLD
--------------------------
Coverage is the fraction of the plateau box whose 200 hPa geopotential height
reaches 12500 gpm -- the contour classically used to delimit this high in
summer.  An episode is a run of at least MIN_DAYS consecutive JJA days above
COVER_MIN.

Sampling is daily 00Z, not 6-hourly.  That is a deliberate reduction: the store
is chunked 8 time steps at a time over ALL levels and ALL space, so 6-hourly
would read four times the data for a feature whose episode length is measured
in days.

LONGITUDE IS 0-360 IN THIS SOURCE.  The mask is built from the source's own
coordinates.  Reusing a -180-180 mask against a 0-360 grid selected zero cells
in the Andes earlier in this study.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import xarray as xr

STORE = ("https://storage.googleapis.com/gcp-public-data-arco-era5/ar/"
         "1959-2022-6h-240x121_equiangular_with_poles_conservative.zarr")
LEVEL = 200
GPM = 9.80665
COVER_MIN = 0.5          # fraction of the plateau box reaching the contour
CONTOUR = 12500.0        # gpm (literature default; normally overridden)
MIN_DAYS = 3
BOX = (26.0, 32.0, 80.0, 92.0)      # south, north, west, east


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--first", type=int, default=1979)
    ap.add_argument("--last", type=int, default=2021)
    ap.add_argument("--json", default=None)
    ap.add_argument("--percentile", type=float, default=75.0,
                    help="contour percentile within the box; default 75")
    args = ap.parse_args()

    ds = xr.open_zarr(STORE, consolidated=True)
    z = ds["geopotential"].sel(level=LEVEL)
    lat = ds["latitude"].values
    lon = ds["longitude"].values
    wrap = bool((lon > 180).any())

    s, n, w, e = BOX
    mla = (lat >= s) & (lat <= n)
    if wrap:
        # OR is only for a box that CROSSES the 0/360 seam.  Using it otherwise
        # is a union, which every longitude satisfies: the first run of this
        # script selected all 240 longitude cells and reported "lat 4 x lon 240"
        # as if that were a plateau box.  A guard that only rejects zero cells
        # cannot catch this, so the fraction is checked too.
        if w <= e:
            mlo = (lon >= w) & (lon <= e)
        else:
            mlo = (lon >= w) | (lon <= e)
    else:
        mlo = (lon >= w) & (lon <= e)
    mask = mla[:, None] & mlo[None, :]
    n_sel, n_tot = int(mask.sum()), mask.size
    if n_sel == 0:
        raise SystemExit("REFUSED: the mask selected zero cells -- wrong convention")
    if n_sel > 0.25 * n_tot:
        raise SystemExit(f"REFUSED: the mask selected {n_sel}/{n_tot} cells "
                         f"({100*n_sel/n_tot:.0f}%) -- a plateau box is a small "
                         f"part of the globe, so this is a wrap-logic bug")
    print(f"  框选占比 {100*n_sel/n_tot:.2f}%  (lat {int(mla.sum())} × lon {int(mlo.sum())})")
    print(f"  {LEVEL} hPa, 高原框掩膜 {int(mask.sum())} 格 (lat {mla.sum()} × lon {mlo.sum()})")

    times = ds["time"].values
    years = times.astype("datetime64[Y]").astype(int) + 1970
    months = times.astype("datetime64[M]").astype(int) % 12 + 1
    days = times.astype("datetime64[D]")
    keep = (years >= args.first) & (years <= args.last) & np.isin(months, (6, 7, 8))
    # Daily 00Z only.
    hours = times.astype("datetime64[h]").astype(int) % 24
    keep &= (hours == 0)
    idx = np.flatnonzero(keep)
    print(f"  JJA 每日 00Z 共 {idx.size} 个时次，{args.first}-{args.last}")

    hgt = np.asarray(z.isel(time=idx).values, dtype="float64") / GPM
    flat = np.flatnonzero(mask.ravel())
    sub = hgt.reshape(hgt.shape[0], -1)[:, flat]

    # THE CONTOUR IS TAKEN FROM THE DATA, NOT FROM THE LITERATURE.
    # The classical 12500 gpm contour never enters this box: measured maxima
    # here run 11974 gpm, so a literature threshold yields exactly zero
    # episodes and looks like "no such events exist" rather than "wrong
    # threshold".  The contour is therefore the percentile the user asked for.
    if args.percentile is not None:
        contour = float(np.percentile(sub, args.percentile))
    else:
        contour = CONTOUR
    print(f"  等值线 {contour:.0f} gpm "
          f"({'data-derived p'+str(args.percentile) if args.percentile is not None else 'literature'})")
    cover = (sub >= contour).mean(axis=1)
    day = days[idx]

    # Centroid over the box, weighting only cells above the contour.
    LA, LO = np.meshgrid(lat, lon, indexing='ij')
    la = LA.ravel()[flat]
    lo = LO.ravel()[flat]
    above = np.clip(sub - CONTOUR, 0, None)
    wsum = above.sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        clat = np.where(wsum > 0, (above * la[None, :]).sum(axis=1) / wsum, np.nan)
        clon = np.where(wsum > 0, (above * lo[None, :]).sum(axis=1) / wsum, np.nan)
    peak = sub.max(axis=1)

    # Episodes: consecutive runs above COVER_MIN, and the JJA boundary must not
    # silently join June of one year to August of the next.
    eps, i = [], 0
    while i < cover.size:
        if cover[i] >= COVER_MIN:
            j = i
            while (j + 1 < cover.size and cover[j + 1] >= COVER_MIN
                   and (day[j + 1] - day[j]).astype(int) == 1):
                j += 1
            if j - i + 1 >= MIN_DAYS:
                eps.append((i, j))
            i = j + 1
        else:
            i += 1
    print(f"\n  覆盖 ≥ {COVER_MIN:.0%} 且持续 ≥ {MIN_DAYS} 天的事件: {len(eps)} 次")
    if not eps:
        print("  → 没有事件，阈值或框选需要复核")
        return 1

    durs = [int((day[b] - day[a]).astype(int)) + 1 for a, b in eps]
    print(f"  持续时长: 中位 {int(np.median(durs))} 天  最长 {max(durs)} 天")

    # Exit classification: over the last UPTO days, which moved first?
    UPTO = 3
    kinds = []
    rows = []
    for a, b in eps:
        k = min(UPTO, b - a)
        if k < 1:
            kinds.append("too-short"); continue
        dpeak = peak[b] - peak[b - k]
        dpos = np.hypot(clon[b] - clon[b - k], clat[b] - clat[b - k])
        dlat = clat[b] - clat[b - k]
        if not np.isfinite(dpos):
            kinds.append("undefined"); continue
        # Southward retreat is called first because it means something different
        # from any other displacement: it is the seasonal withdrawal.
        if dlat < -1.0 and abs(dlat) > 0.6 * dpos:
            kind = "retreat (southward)"
        elif dpos >= 2.0 and dpos > 0.5 * abs(dpeak):
            kind = "displace"
        elif dpeak < -20.0:
            kind = "decay in place"
        else:
            kind = "ambiguous"
        kinds.append(kind)
        rows.append({"start": str(day[a]), "days": int((day[b] - day[a]).astype(int)) + 1,
                     "peak_gpm": float(peak[a]), "kind": kind,
                     "d_peak_3d": float(dpeak), "d_pos_3d_deg": float(dpos)})

    from collections import Counter
    c = Counter(kinds)
    print(f"\n  === 退出方式（结束前 {UPTO} 天）===")
    for k, v in c.most_common():
        print(f"    {k:<22}{v:>4} 次  ({100*v/len(kinds):.0f}%)")

    print(f"\n  最强 5 次事件：")
    for r in sorted(rows, key=lambda r: -r["peak_gpm"])[:5]:
        print(f"    {r['start']}  {r['days']:>3} 天  {r['peak_gpm']:.0f} gpm  "
              f"退出 {r['kind']}  Δ峰 {r['d_peak_3d']:+.0f} gpm  Δ位 {r['d_pos_3d_deg']:.1f}°")

    if args.json:
        Path(args.json).write_text(json.dumps(
            {"level": LEVEL, "contour": float(contour), "percentile": args.percentile, "cover_min": COVER_MIN,
             "n_episodes": len(eps), "median_days": int(np.median(durs)),
             "exit_modes": dict(c), "episodes": rows}, indent=1, ensure_ascii=False))
        print(f"\n  已写 {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
