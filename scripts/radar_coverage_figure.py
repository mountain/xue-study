#!/usr/bin/env python3
"""Draw the CMA mosaic's echo field together with the coverage edge it does not publish.

Two panels:

  left   the merged rolling window, coloured by how many of its frames echoed in
         each cell, with the reference boxes outlined.  The Bay of Bengal and the
         Arabian Sea are flat zeros while the model rains there; East China is
         solidly lit.  The edge between them is the product's coverage envelope.
  right  the two latitude transects, radar echo share against the model's rain
         share per 1-degree band.  At 80-92E the radar switches on at 29N; at
         95-100E it switches *off* there.  That the two transects disagree in
         direction is the point: the edge is ragged, and nothing in the product
         says where it is.

Reads the live rolling windows, so the picture moves as the windows advance.
"""

from __future__ import annotations

import argparse
import sys

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt                       # noqa: E402
from matplotlib.patches import Rectangle              # noqa: E402

from radar_vs_model_check import (                    # noqa: E402
    BASE, BOXES, epoch_seconds, fetch_json, iso, merge_windows, open_model,
    coarsen_onto)
from urllib.parse import urljoin                      # noqa: E402

OUTLINE = {
    "himalaya-tibet": ("#d62728", "Himalaya / Tibet (the box in question)"),
    "ctrl-east-china": ("#2ca02c", "East China (dense coverage, active weather)"),
    "offshore-bay-of-bengal": ("#1f77b4", "Bay of Bengal (out of range: flat zero)"),
    "offshore-arabian-sea": ("#17becf", "Arabian Sea (out of range: flat zero)"),
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--window", action="append", required=True, metavar="RUN/BUILD")
    ap.add_argument("--out", default="radar-coverage-edge.png")
    ap.add_argument("--stride", type=int, default=4, help="plot every Nth cell (default 4)")
    args = ap.parse_args()

    codes, keys, rlat, rlon = merge_windows(args.window)
    echo = (codes > 0).sum(axis=0).astype(np.int16)     # frames with echo, per cell

    model, mtimes, mlat, mlon, _item, _meta = open_model("prate")
    msec = epoch_seconds(mtimes)
    inside = np.flatnonzero((msec >= int(keys[0])) & (msec <= int(keys[-1]) + 3600))
    rate_max = model[inside].max(axis=0)
    fraction = coarsen_onto(echo > 0, rlat, rlon, mlat, mlon)

    figure, (left, right) = plt.subplots(
        1, 2, figsize=(17, 6.4), gridspec_kw={"width_ratios": [2.35, 1]})

    # ---- left: the echo field ------------------------------------------------
    step = args.stride
    lon2d, lat2d = np.meshgrid(rlon[::step], rlat[::step])
    mesh = left.pcolormesh(lon2d, lat2d, echo[::step, ::step],
                           cmap="magma_r", vmin=0, vmax=len(keys), shading="nearest")
    bar = figure.colorbar(mesh, ax=left, pad=0.015)
    bar.set_label(f"frames with echo, of {len(keys)}  ({iso(keys[0])[11:16]}"
                  f"-{iso(keys[-1])[11:16]}Z)")

    for name, (west, east, south, north) in BOXES.items():
        if name not in OUTLINE:
            continue
        colour, label = OUTLINE[name]
        left.add_patch(Rectangle((west, south), east - west, north - south,
                                 fill=False, edgecolor=colour, linewidth=2.0, label=label))
    # the 29N step on the 80-92E transect
    left.plot([80, 92], [29, 29], color="#ff7f0e", linewidth=2.4, linestyle="--",
              label="29N: where the 80-92E transect switches on")

    left.set_xlim(rlon.min(), rlon.max())
    left.set_ylim(10, 57)
    left.set_xlabel("longitude (deg E)")
    left.set_ylabel("latitude (deg N)")
    left.set_title("CMA radar mosaic, two rolling windows merged\n"
                   "flat zero does not distinguish 'no rain' from 'no radar'", fontsize=11)
    left.legend(loc="lower left", fontsize=8, framealpha=0.92)

    # ---- right: the transects ------------------------------------------------
    bands = [(26, 27), (27, 28), (28, 29), (29, 30), (30, 31), (31, 32), (32, 34)]
    for west, east, colour in ((80, 92, "#d62728"), (95, 100, "#9467bd")):
        radar_share, model_share, centres = [], [], []
        for south, north in bands:
            rows = np.flatnonzero((mlat >= south) & (mlat < north))
            cols = np.flatnonzero((mlon >= west) & (mlon < east))
            if rows.size == 0 or cols.size == 0:
                continue
            f = fraction[np.ix_(rows, cols)].ravel()
            r = rate_max[np.ix_(rows, cols)].ravel()
            good = np.isfinite(f)
            f, r = f[good], r[good]
            if f.size == 0:
                continue
            radar_share.append(float((f > 0).mean() * 100.0))
            model_share.append(float((r >= 0.10).mean() * 100.0))
            centres.append((south + north) / 2.0)
        right.plot(radar_share, centres, "o-", color=colour, linewidth=2.2,
                   label=f"radar echoed, {west}-{east}E")
        right.plot(model_share, centres, "s--", color=colour, alpha=0.45, linewidth=1.6,
                   label=f"model rained, {west}-{east}E")

    right.axhline(29, color="#ff7f0e", linewidth=2.4, linestyle="--")
    right.set_xlabel("share of 0.25 deg cells in the band (%)")
    right.set_ylabel("latitude (deg N)")
    right.set_title("per 1-degree band: the radar switches on at 29N\n"
                    "on one transect and off at 29N on the other", fontsize=11)
    right.set_ylim(25.5, 34.5)
    right.grid(alpha=0.3)
    right.legend(fontsize=8, loc="upper right", framealpha=0.92)

    figure.tight_layout()
    figure.savefig(args.out, dpi=140)
    print(f"wrote {args.out}")

    print()
    print("read the left panel with the right one: a band where the model rained and")
    print("the radar is flat zero is the envelope, not dry weather.  The envelope is")
    print("not published, so no echo fraction that crosses it can be read as rainfall.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
