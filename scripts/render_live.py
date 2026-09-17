"""Render the live Xue dataset to a contact sheet and an animation.

Reads the store the site itself plays, with plain xarray -- no xue decoder,
no registration, nothing but the published Zarr. The point is both to look at
the forecast and to show that the ecosystem path works.

Usage:
    uv run python render_live.py [store-url] [run-time-iso] [out-dir]
"""

from __future__ import annotations

import io
import sys
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import xarray as xr
from PIL import Image

DEFAULT_URL = "https://dataset.ringsaturn.me/xue/gfs.2026091606/tmp2m.half.zarr"
VMIN, VMAX = -40.0, 45.0


def load(url: str) -> xr.DataArray:
    dataset = xr.open_zarr(url)
    field = dataset["tmp2m"]
    print(f"opened {url}")
    print(f"  dims={field.dims} shape={field.shape} dtype={field.dtype}")
    field = field.load()  # one pass over the store
    print(f"  decoded °C range: {float(field.min()):.1f} .. {float(field.max()):.1f}")
    return field


def valid_time(run_time: datetime, moment: np.datetime64) -> str:
    stamp = moment.astype("datetime64[s]").astype(datetime).replace(tzinfo=timezone.utc)
    lead = int((stamp - run_time).total_seconds()) // 3600
    return f"F{lead:03d}   {stamp:%m-%d %HZ}"


def contact_sheet(field: xr.DataArray, run_time: datetime, out: Path, panels: int = 8) -> None:
    picks = np.linspace(0, field.sizes["time"] - 1, panels).astype(int)
    figure, axes = plt.subplots(2, panels // 2, figsize=(4 * (panels // 2), 4.6), constrained_layout=True)
    for axis, index in zip(axes.ravel(), picks, strict=True):
        axis.imshow(
            field.isel(time=int(index)),
            origin="upper",
            extent=(-180, 180, -90, 90),
            cmap="RdYlBu_r",
            vmin=VMIN,
            vmax=VMAX,
            interpolation="bilinear",
        )
        axis.set_title(valid_time(run_time, field["time"].isel(time=int(index)).values), fontsize=10)
        axis.set_xticks([])
        axis.set_yticks([])
    figure.suptitle(f"2 m temperature  ·  GFS 0.25°  ·  run {run_time:%Y-%m-%d %HZ}", fontsize=13)
    figure.savefig(out, dpi=110)
    plt.close(figure)
    print(f"wrote {out}  ({panels} panels)")


def animation(field: xr.DataArray, run_time: datetime, out: Path, stride: int = 3, scale: int = 2) -> None:
    frames = []
    for index in range(0, field.sizes["time"], stride):
        plane = np.asarray(field.isel(time=index))
        label = valid_time(run_time, field["time"].isel(time=index).values)

        figure, axis = plt.subplots(figsize=(7.2, 3.9), constrained_layout=True)
        image = axis.imshow(
            plane, origin="upper", extent=(-180, 180, -90, 90), cmap="RdYlBu_r",
            vmin=VMIN, vmax=VMAX, interpolation="bilinear",
        )
        axis.set_xticks([])
        axis.set_yticks([])
        axis.set_title(f"2 m temperature   {label}", fontsize=12)
        figure.colorbar(image, ax=axis, orientation="horizontal", pad=0.04, fraction=0.05, label="°C")

        buffer = io.BytesIO()
        figure.savefig(buffer, format="png", dpi=100)
        plt.close(figure)
        buffer.seek(0)
        frame = Image.open(buffer).convert("RGB")
        if scale > 1:
            frame = frame.resize((frame.width // scale, frame.height // scale), Image.LANCZOS)
        frames.append(frame)

    frames[0].save(out, save_all=True, append_images=frames[1:], duration=120, loop=0, optimize=True)
    print(f"wrote {out}  ({len(frames)} frames)")


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    run_time = (
        datetime.fromisoformat(sys.argv[2].replace("Z", "+00:00"))
        if len(sys.argv) > 2
        else datetime(2026, 9, 16, 6, tzinfo=timezone.utc)
    )
    out_dir = Path(sys.argv[3]) if len(sys.argv) > 3 else Path(".")
    out_dir.mkdir(parents=True, exist_ok=True)

    field = load(url)
    contact_sheet(field, run_time, out_dir / "live-tmp2m-contact-sheet.png")
    animation(field, run_time, out_dir / "live-tmp2m-animation.gif")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
