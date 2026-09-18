"""Render the block's own archived fields to PNG, using xue's own palettes.

WHY THIS EXISTS
---------------
The block page reported an inventory: how many items, how many bytes, what time
window.  That answers "is the collector alive" and nothing else.  The point of
the block is the DATA, and until it is drawn there is no way to see whether the
thing being archived is the field it claims to be.

A poster is not an image.  It is a zlib-deflated plane of QUANTIZED CODES, one
byte per pixel, and a code means nothing until it is decoded with that
variable's own quantization and then colored with that variable's own ramp:

    value = offset + code * scale          (code == nodataCode -> transparent)
    color = interpolate(STOPS, value)

Both come from xue: the quantization from the bundle's manifest, the ramp from
`web/src/palettes.ts`.  Nothing here invents a colormap, because a field drawn
in a made-up ramp is a picture of the author's choices rather than of the data.

Sampling is nearest-neighbour and the poster is already a reduced grid (0.5 deg
for GFS, against the store's 0.25), so this is a view of the poster, not of the
full-resolution product.  The page says so.

Usage:
  python3 scripts/poster_render.py --gallery /tmp/xue-upstream/web/public
"""

from __future__ import annotations

import argparse
import glob
import json
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# xue's own temperature ramp, copied from web/src/palettes.ts so the page shows
# the same colors the real viewer does.
TEMPERATURE_STOPS = [
    (-60, 39, 25, 89, 255), (-50, 49, 54, 149, 255), (-40, 55, 103, 190, 255),
    (-30, 65, 155, 201, 255), (-20, 111, 201, 183, 255), (-10, 181, 226, 174, 255),
    (0, 238, 239, 179, 255), (10, 254, 217, 118, 255), (20, 253, 153, 66, 255),
    (30, 230, 85, 48, 255), (40, 179, 32, 55, 255), (50, 112, 20, 65, 255),
]

# Variables drawn with the temperature ramp.  Everything else falls back to a
# neutral grey so the page never implies a palette it did not use.
TEMPERATURE_VARS = {"tmp2m", "tmpsfc", "tmp850", "tmp925", "tmp500", "dpt2m", "thetae850"}


def interpolate(stops, value):
    if value <= stops[0][0]:
        return stops[0][1:]
    if value >= stops[-1][0]:
        return stops[-1][1:]
    for i in range(1, len(stops)):
        up = stops[i]
        if value <= up[0]:
            lo = stops[i - 1]
            t = (value - lo[0]) / (up[0] - lo[0])
            return tuple(round(lo[k] + (up[k] - lo[k]) * t) for k in range(1, 5))
    return stops[-1][1:]



def unfilter_rows(plane: bytes, width: int, height: int) -> bytes:
    """Undo the poster's vertical delta encoding.

    Row 0 is stored as-is; every later row stores its difference from the row
    above, modulo 256.  So the values are the running sum down each column.
    """
    import numpy as np
    a = np.frombuffer(plane, dtype=np.uint8).reshape(height, width).astype(np.uint64)
    a = np.cumsum(a, axis=0) % 256          # mod 256 at every step is the same
    return a.astype(np.uint8).tobytes()     # as taking the sum mod 256


def write_png(path: Path, rgb_rows, width: int, height: int) -> None:
    """Minimal RGBA PNG writer -- no image library needed."""
    raw = bytearray()
    for row in rgb_rows:
        raw.append(0)                      # filter type 0
        raw.extend(row)
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
           + chunk(b"IEND", b""))
    path.write_bytes(png)


def quantization_of(item_dir: Path, variable: str):
    """Find a variable's quantization in the bundle's MANIFEST.

    The first version looked in the item's asset metadata, found nothing, and
    silently fell back to the neutral ramp for every field -- which also meant
    nodata codes were drawn as grey instead of transparent.  The quantization
    lives in the manifest, under the bundle's poster metadataJson.
    """
    man = item_dir / "manifest"
    if not man.exists():
        return None
    try:
        d = json.loads(man.read_text())
    except Exception:
        return None
    for b in d.get("bundles", []):
        if b.get("variable") != variable:
            continue
        mj = (b.get("poster") or {}).get("metadataJson")
        if not mj:
            continue
        m = json.loads(mj) if isinstance(mj, str) else mj
        for v in m.get("variables", []):
            if v.get("id") == variable and v.get("quantization"):
                return v["quantization"]
    return None


def render(archive: Path, out_dir: Path, max_per_var: int) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    made = []
    posters = sorted(glob.glob(str(archive / "*" / "*" / "*-poster")))
    seen = {}
    for p in posters:
        name = Path(p).name[:-len("-poster")]
        coll = Path(p).parts[-3]
        if seen.get(name, 0) >= max_per_var:
            continue
        item_path = Path(p).parent / "item.json"
        if not item_path.exists():
            continue
        item = json.loads(item_path.read_text())
        desc = None
        for k, v in (item.get("assets") or {}).items():
            if k == Path(p).name:
                desc = v
                break
        if not desc:
            continue
        grid = desc.get("xue:grid") or {}
        W, H = grid.get("width"), grid.get("height")
        if not W or not H:
            continue
        try:
            plane = zlib.decompress(Path(p).read_bytes())
        except Exception:
            continue
        if len(plane) != W * H:
            continue
        # POSTERS ARE VERTICALLY DELTA-ENCODED.  Each row holds the difference
        # from the row above, modulo 256, and the reader must un-filter it --
        # xue's own web/src/poster.ts runs exactly this loop.  Skipping it
        # renders the DIFFERENCES as if they were values, which is what the
        # first attempt did: horizontal streaks that no palette could fix,
        # because the wrong quantity was being drawn.
        plane = unfilter_rows(plane, W, H)
        q = quantization_of(Path(p).parent, name)
        temp = name in TEMPERATURE_VARS and q is not None
        rows = []
        for y in range(H):
            row = bytearray()
            base = y * W
            for x in range(W):
                code = plane[base + x]
                if q is not None and (code == q.get("nodataCode")
                                      or code > q.get("maximumCode", 255)):
                    row.extend((0, 0, 0, 0))
                    continue
                if temp:
                    val = q["offset"] + code * q["scale"]
                    r, g, b, a = interpolate(TEMPERATURE_STOPS, val)
                else:
                    # Neutral ramp over the codebook, alpha carried through.
                    g = int(code)
                    r = b = g
                    a = 0 if code == 0 else 255
                row.extend((int(r), int(g), int(b), int(a)))
            rows.append(row)
        fn = f"{coll}__{name}.png"
        write_png(out_dir / fn, rows, W, H)
        made.append({"file": fn, "collection": coll, "variable": name,
                     "width": W, "height": H,
                     "ramp": "temperature (xue palettes.ts)" if temp else "neutral grey",
                     "item": item.get("id"),
                     "decoded": q is not None})
        seen[name] = seen.get(name, 0) + 1
    return made


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", default=str(ROOT / "archive"))
    ap.add_argument("--gallery", default="/tmp/xue-upstream/web/public")
    ap.add_argument("--max-per-var", type=int, default=2)
    args = ap.parse_args()

    out = Path(args.gallery) / "blockimg"
    made = render(Path(args.archive), out, args.max_per_var)
    (Path(args.gallery) / "block-posters.json").write_text(
        json.dumps(made, indent=1, ensure_ascii=False))
    print(f"  渲染 {len(made)} 张 → {out}")
    for m in made:
        print(f"    {m['file']:<30} {m['width']}×{m['height']}  {m['ramp']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
