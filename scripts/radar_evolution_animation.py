#!/usr/bin/env python3
"""Animate the merged CMA radar window so the mosaic's coverage is visible as motion.

The point of watching it rather than a still: over the covered area echoes are
born, drift and die between consecutive six-minute frames; over the uncovered
area the picture stays flat for all thirty frames.  The difference between those
two behaviours is the coverage envelope, and the product never states it.

Writes a GIF and, if asked, a contact sheet of every Nth frame.
"""

from __future__ import annotations

import argparse
import sys

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt                       # noqa: E402
import matplotlib.animation as animation              # noqa: E402
from matplotlib.patches import Rectangle              # noqa: E402

from radar_vs_model_check import BOXES, iso, merge_windows   # noqa: E402

BOX_STYLE = {
    "himalaya-tibet": ("#00d0ff", "Himalaya / Tibet"),
    "ctrl-east-china": ("#22cc44", "East China"),
    "offshore-bay-of-bengal": ("#ffdd33", "Bay of Bengal"),
    "offshore-arabian-sea": ("#ff66cc", "Arabian Sea"),
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--window", action="append", required=True, metavar="RUN/BUILD")
    ap.add_argument("--out", default="cma-radar-evolution.gif")
    ap.add_argument("--sheet", metavar="PATH", help="also write a contact sheet")
    ap.add_argument("--stride", type=int, default=4, help="plot every Nth cell (default 4)")
    ap.add_argument("--fps", type=float, default=4.0)
    args = ap.parse_args()

    codes, keys, rlat, rlon = merge_windows(args.window)
    frames = np.where(codes > 0, codes, np.nan).astype(np.float32) * 0.5   # dBZ
    step = args.stride
    lon2d, lat2d = np.meshgrid(rlon[::step], rlat[::step])
    plotted = frames[:, ::step, ::step]

    figure, axes = plt.subplots(figsize=(11.5, 6.2))
    mesh = axes.pcolormesh(lon2d, lat2d, plotted[0], cmap="turbo",
                           vmin=0, vmax=60, shading="nearest")
    bar = figure.colorbar(mesh, ax=axes, pad=0.015)
    bar.set_label("composite reflectivity (dBZ)")
    for name, (west, east, south, north) in BOXES.items():
        if name not in BOX_STYLE:
            continue
        colour, label = BOX_STYLE[name]
        axes.add_patch(Rectangle((west, south), east - west, north - south,
                                 fill=False, edgecolor=colour, linewidth=1.4, label=label))
    axes.set_xlim(rlon.min(), rlon.max())
    axes.set_ylim(10, 57)
    axes.set_xlabel("longitude (deg E)")
    axes.set_ylabel("latitude (deg N)")
    axes.legend(loc="lower left", fontsize=7.5, framealpha=0.9, ncol=2)
    title = axes.set_title("", fontsize=11)

    def draw(index: int):
        mesh.set_array(plotted[index].ravel())
        title.set_text(f"CMA radar mosaic  {iso(int(keys[index]))[11:16]}Z   "
                       f"frame {index + 1}/{len(keys)}   "
                       f"(blank = no echo OR no radar; the product does not say which)")
        return mesh, title

    writer = animation.PillowWriter(fps=args.fps)
    with writer.saving(figure, args.out, dpi=110):
        for index in range(len(keys)):
            draw(index)
            writer.grab_frame()
    print(f"wrote {args.out}  ({len(keys)} frames, {iso(int(keys[0]))[11:16]}"
          f"-{iso(int(keys[-1]))[11:16]}Z)")

    if args.sheet:
        picks = list(range(0, len(keys), max(1, len(keys) // 8)))[:8]
        cols, rows = 4, 2
        sheet, cells = plt.subplots(rows, cols, figsize=(19, 6.4))
        for cell, index in zip(cells.ravel(), picks):
            cell.pcolormesh(lon2d, lat2d, plotted[index], cmap="turbo",
                            vmin=0, vmax=60, shading="nearest")
            for name, (west, east, south, north) in BOXES.items():
                if name not in BOX_STYLE:
                    continue
                cell.add_patch(Rectangle((west, south), east - west, north - south,
                                         fill=False, edgecolor=BOX_STYLE[name][0],
                                         linewidth=1.2))
            cell.set_xlim(rlon.min(), rlon.max())
            cell.set_ylim(10, 57)
            cell.set_title(f"{iso(int(keys[index]))[11:16]}Z", fontsize=9)
            cell.set_xticks([])
            cell.set_yticks([])
        for cell in cells.ravel()[len(picks):]:
            cell.axis("off")
        sheet.suptitle("CMA radar mosaic, merged rolling windows -- the Bay of Bengal and "
                       "Arabian Sea stay blank for every frame", fontsize=11)
        sheet.tight_layout()
        sheet.savefig(args.sheet, dpi=130)
        print(f"wrote {args.sheet}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
