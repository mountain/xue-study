"""Plot the analytic family checked by check.py; no empirical weather data."""
import argparse
import json
import math

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    args = parser.parse_args()
    evidence = json.loads((args.run / "evidence.json").read_text())
    if evidence["status"] != "ExactModelAndNativeTargetDependentLossChecked":
        raise ValueError("expected a completed model check")
    destinations = [args.run / ("phase-and-shape."+ext) for ext in ("svg", "png")]
    if any(p.exists() for p in destinations):
        raise FileExistsError("plot outputs must be fresh")
    ts = [2*math.pi*j/800 for j in range(801)]
    fig, axes = plt.subplots(2, 1, figsize=(8.6, 6.6), sharex=True, layout="constrained")
    for w, color in [(0, "#335c81"), (0.75, "#d28b30"), (1.5, "#a54865")]:
        c = 2*w/3
        axes[0].plot(ts, [-0.75*math.cos(2*c*t) for t in ts], color=color,
                     linewidth=2, label=rf"Hidden rotation $w={w:g}$")
    axes[0].set(title="Same initial even spectrum; different future phase", ylabel=r"Fixed-axis $E(e_x,t)$")
    axes[0].legend(loc="upper right", frameon=True, fontsize=9)
    axes[0].axvline(math.pi/4, color="0.4", linestyle=":", linewidth=1)
    axes[0].annotate(r"Checked witness: $t=\pi/4$", xy=(math.pi/4, 0),
                     xytext=(1.3, -0.35), fontsize=9, arrowprops={"arrowstyle": "->", "color": "0.4"})
    axes[1].plot(ts, [0.15]*len(ts), linewidth=2.5, color="#417b5a",
                 label="All three rotations: identical shape power")
    axes[1].set(title="A shape invariant persists in this exact family", ylabel=r"$\langle E^2\rangle=3/20$",
                xlabel="Dimensionless time (not calibrated to months)", ylim=(0, 0.25))
    axes[1].legend(loc="lower right", fontsize=9)
    for axis in axes:
        axis.grid(alpha=0.2)
        axis.spines[["top", "right"]].set_visible(False)
    fig.suptitle("Ideal spherical flow · analytic curves, not weather forecasts", fontsize=12)
    for path in destinations:
        fig.savefig(path, dpi=160)
    plt.close(fig)
    print("Saved " + ", ".join(str(p) for p in destinations))


if __name__ == "__main__":
    main()
