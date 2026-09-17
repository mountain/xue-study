"""Independent verification of the .xue container <-> Zarr v3 store equivalence.

Written from the two normative specs (docs/format.md, docs/zarr-profile.md)
WITHOUT using xuebuild.zarrstore or xuebuild.binformat helpers, so that the
parsers on both sides are an independent implementation.

Third party for the codes themselves: the Rust decoder (xuepy wheel).

Usage: uv run python verify.py <bundle.xue> <store.zarr> <variable-id>
"""

from __future__ import annotations

import json
import struct
import sys
from compression import zstd
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------- CRC-32C
# Castagnoli polynomial 0x1EDC6F41, reflected form 0x82F63B78.
# Deliberately NOT zlib.crc32 (that is CRC-32/IEEE, a different polynomial).
def _crc32c_table() -> list[int]:
    table = []
    for i in range(256):
        crc = i
        for _ in range(8):
            crc = (crc >> 1) ^ (0x82F63B78 if crc & 1 else 0)
        table.append(crc)
    return table


_TABLE = _crc32c_table()


def crc32c(data: bytes) -> int:
    crc = 0xFFFFFFFF
    for byte in data:
        crc = _TABLE[(crc ^ byte) & 0xFF] ^ (crc >> 8)
    return crc ^ 0xFFFFFFFF


# ------------------------------------------------------- container v2 index
def parse_container(path: Path) -> dict:
    """docs/format.md 'Container v2': header, index, chunk spans."""
    raw = path.read_bytes()
    assert raw[:8] == b"XUE\0\0\0\0\0", "magic"
    assert len(raw) == struct.unpack_from("<Q", raw, 16)[0], "fileSize"
    (version,) = struct.unpack_from("<H", raw, 8)
    assert version == 2, f"expected container v2, got v{version}"
    (metadata_offset, metadata_length, index_offset, index_length, data_offset,
     dict_offset, dict_length) = struct.unpack_from("<QQQQQQQ", raw, 24)
    metadata = json.loads(raw[metadata_offset:metadata_offset + metadata_length])

    assert raw[index_offset:index_offset + 4] == b"IDX2", "IDX2 magic"
    (idx_version, header_size, tile_w, tile_h, group_count,
     variable_count) = struct.unpack_from("<HHHHHB", raw, index_offset + 4)
    (chunk_count,) = struct.unpack_from("<I", raw, index_offset + 16)
    assert idx_version == 2 and header_size == 32

    pos = index_offset + 32
    variables = []
    for _ in range(variable_count):
        vid, predictor, reserved = struct.unpack_from("<BBH", raw, pos)
        assert reserved == 0
        variables.append({"id": vid, "predictor": predictor})
        pos += 4
    groups = []
    for _ in range(group_count):
        first_frame, frame_count_, reserved = struct.unpack_from("<HBB", raw, pos)
        assert reserved == 0
        groups.append({"first_frame": first_frame, "frame_count": frame_count_})
        pos += 4
    chunks = []
    for _ in range(chunk_count):
        comp_len, crc = struct.unpack_from("<II", raw, pos)
        chunks.append({"compressed_length": comp_len, "crc32": crc})
        pos += 8
    assert index_length == pos - index_offset, "indexLength"

    # Offsets are a prefix sum, not stored (docs/format.md 'ChunkEntry and
    # chunk order'); position = (g * tileCount + t) * variableCount + v.
    grid_w, grid_h = metadata["grid"]["width"], metadata["grid"]["height"]
    tile_columns, tile_rows = -(-grid_w // tile_w), -(-grid_h // tile_h)
    tile_count = tile_columns * tile_rows
    assert chunk_count == group_count * tile_count * variable_count, "chunkCount"

    offset = data_offset
    for i, chunk in enumerate(chunks):
        chunk["offset"] = offset
        offset += chunk["compressed_length"]
    end = (offset + 7) & ~7
    assert end == len(raw), f"fileSize != align8(last chunk) ({end} vs {len(raw)})"
    assert all(b == 0 for b in raw[offset:end]), "nonzero padding"

    return {"raw": raw, "metadata": metadata, "variables": variables,
            "groups": groups, "chunks": chunks, "tile": (tile_w, tile_h),
            "tile_count": tile_count, "tile_columns": tile_columns,
            "variable_count": variable_count}


def container_chunk_span(container: dict, group: int, tile: int, variable: int) -> tuple[int, int]:
    position = (group * container["tile_count"] + tile) * container["variable_count"] + variable
    chunk = container["chunks"][position]
    return chunk["offset"], chunk["offset"] + chunk["compressed_length"]


# --------------------------------------------------------- Zarr v3 shard
def zarr_index_location(array_meta: dict) -> str:
    codecs = array_meta["codecs"]
    assert len(codecs) == 1 and codecs[0]["name"] == "sharding_indexed", "one sharding codec"
    return codecs[0]["configuration"].get("index_location", "end")


def zarr_inner_chain(array_meta: dict) -> list[str]:
    return [c["name"] for c in array_meta["codecs"][0]["configuration"]["codecs"]]


def zarr_inner_shape(array_meta: dict) -> tuple[int, int, int]:
    return tuple(array_meta["codecs"][0]["configuration"]["chunk_shape"])


def read_shard_index(shard: bytes, count: int, index_location: str) -> list[tuple[int, int]]:
    """16 bytes per inner chunk (offset u64, nbytes u64) + trailing CRC-32C."""
    if index_location == "end":
        block = shard[len(shard) - (16 * count + 4):]
    else:
        block = shard[:16 * count + 4]
    stored = struct.unpack_from("<I", block, 16 * count)[0]
    assert stored == crc32c(block[:16 * count]), "shard index CRC-32C"
    return [struct.unpack_from("<QQ", block, 16 * i) for i in range(count)]


def delta_decode(block: np.ndarray) -> np.ndarray:
    """docs/zarr-profile.md 'The xue.delta codec': running sum mod 256 on axis 0."""
    out = np.empty_like(block)
    acc = block[0].copy()
    out[0] = acc
    for i in range(1, block.shape[0]):
        acc = (acc + block[i]) & 0xFF
        out[i] = acc
    return out


def read_store_plane(store: Path, variable: str, frame_index: int) -> np.ndarray:
    group = json.loads((store / "zarr.json").read_text())
    array_meta = json.loads((store / variable / "zarr.json").read_text())
    metadata = group["attributes"]["xue"]
    width, height = metadata["grid"]["width"], metadata["grid"]["height"]

    inner_t, tile_h, tile_w = zarr_inner_shape(array_meta)
    shard_shape = array_meta["chunk_grid"]["configuration"]["chunk_shape"]
    tile_columns = -(-width // tile_w)
    tile_rows = -(-height // tile_h)
    tile_count = tile_columns * tile_rows
    time_chunks_per_shard = shard_shape[0] // inner_t
    chunks_per_shard = time_chunks_per_shard * tile_count
    index_location = zarr_index_location(array_meta)
    chain = zarr_inner_chain(array_meta)

    time_chunk = frame_index // inner_t
    frame_in_chunk = frame_index % inner_t
    shard_number = (time_chunk * inner_t) // shard_shape[0]
    shard = (store / variable / "c" / str(shard_number) / "0" / "0").read_bytes()
    index = read_shard_index(shard, chunks_per_shard, index_location)

    plane = np.zeros(height * width, dtype=np.uint8)
    for tile in range(tile_count):
        row, column = divmod(tile, tile_columns)
        first_row, first_column = row * tile_h, column * tile_w
        position = ((time_chunk * inner_t) % shard_shape[0]) // inner_t * tile_count + tile
        offset, nbytes = index[position]
        assert offset != 2**64 - 1, "chunk never written"
        payload = shard[offset:offset + nbytes]
        decoded = np.frombuffer(zstd.decompress(payload), dtype=np.uint8)
        assert decoded.size == inner_t * tile_h * tile_w, "decompressed length"
        block = decoded.reshape(inner_t, tile_h, tile_w)
        if "xue.delta" in chain:
            block = delta_decode(block)
        # Trim padding past the grid ('Trimming the padding').
        rows = min(tile_h, height - first_row)
        columns = min(tile_w, width - first_column)
        view = block[frame_in_chunk, :rows, :columns].reshape(-1)
        start = first_row * width + first_column
        for r in range(rows):
            plane[start + r * width: start + r * width + columns] = view[r * columns:(r + 1) * columns]
    return plane


# ---------------------------------------------------------------- compare
def main() -> int:
    import xue

    xue_path, store_path, variable = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    container = parse_container(xue_path)
    bundle = xue.Bundle.open(xue_path)

    name_to_numeric = {v["id"]: v["numericId"] for v in container["metadata"]["variables"]}
    numeric = name_to_numeric[variable]
    variable_index = [v["id"] for v in container["variables"]].index(numeric)
    predictor = container["variables"][variable_index]["predictor"]

    frames = container["metadata"]["time"]
    offsets = ([frames["firstFrameOffset"] + i * frames["frameStep"] for i in range(frames["frameCount"])]
               if "frameStep" in frames else frames["frameOffsets"])
    inner_t = zarr_inner_shape(json.loads((store_path / variable / "zarr.json").read_text()))[0]

    print(f"variable={variable} numericId={numeric} predictor={predictor} "
          f"container=v2 tile={container['tile']} frames={len(offsets)}")

    # (a) every frame: store codes == Rust decoder codes
    mismatched = 0
    for index, offset in enumerate(offsets):
        expected = np.frombuffer(bundle.decode(numeric, offset), dtype=np.uint8)
        actual = read_store_plane(store_path, variable, index)
        if not np.array_equal(expected, actual):
            mismatched += 1
            differing = int((expected != actual).sum())
            print(f"  MISMATCH frame {index} (offset {offset}): {differing} cells")
    print(f"  (a) frames identical to Rust decoder: {len(offsets) - mismatched}/{len(offsets)}")

    # (b) byte identity of chunks where the two layouts coincide, computed
    #     here from the specs rather than from the exporter's own report.
    tile_w, tile_h = container["tile"]
    width, height = container["metadata"]["grid"]["width"], container["metadata"]["grid"]["height"]
    tile_columns = container["tile_columns"]
    array_meta = json.loads((store_path / variable / "zarr.json").read_text())
    chain = zarr_inner_chain(array_meta)
    shard_shape = array_meta["chunk_grid"]["configuration"]["chunk_shape"]
    tile_count = container["tile_count"]
    chunks_per_shard = (shard_shape[0] // inner_t) * tile_count
    index_location = zarr_index_location(array_meta)
    shard = (store_path / variable / "c" / "0" / "0" / "0").read_bytes()
    index = read_shard_index(shard, chunks_per_shard, index_location)

    comparable = identical = 0
    for group_i, group in enumerate(container["groups"]):
        first = group["first_frame"]
        # The store's time grid is a fixed `inner_t` frames from the axis
        # start; the container cuts its groups inside segments of constant
        # step. The two coincide only where a group starts on a multiple of
        # the time chunk AND has the same length -- after the GFS step change
        # at f120 the container's groups start at axis index 121, 127, ...
        # and none of them lines up. Pairing group i with time chunk i would
        # silently compare the wrong chunks.
        if group["frame_count"] != inner_t or first % inner_t:
            continue
        time_chunk = first // inner_t
        for tile in range(tile_count):
            row, column = divmod(tile, tile_columns)
            clipped = (min(tile_h, height - row * tile_h) != tile_h
                       or min(tile_w, width - column * tile_w) != tile_w)
            if clipped:
                continue
            comparable += 1
            start, end = container_chunk_span(container, group_i, tile, variable_index)
            offset, nbytes = index[time_chunk * tile_count + tile]
            identical += shard[offset:offset + nbytes] == container["raw"][start:end]
    # "No comparable chunk existed" must not be readable as a comparison that
    # passed (zero mismatches) or as one that failed. The counts are the same
    # number in both cases, so the verdict is stated instead of implied.
    # What the counts mean depends on the chain and the bundle's predictor, so
    # the verdict says which of the profile's cases this is rather than
    # leaving the reader to infer it. (docs/zarr-profile.md "Equivalence with
    # the container": identical under the delta chain for a predicted
    # variable, and under either chain for a RAW one.)
    differenced = "xue.delta" in chain
    expected_identity = predictor == 0 or (predictor == 2 and differenced)
    if comparable == 0:
        verdict = ("NOT COMPARED — no chunk here coincides with a container group (short axis, "
                   "clipped tile row, or a change of step), so this establishes nothing")
    elif identical == comparable:
        verdict = (f"ALL COMPARED CHUNKS IDENTICAL ({identical}/{comparable})"
                   + ("" if expected_identity else " [identity was NOT expected on this chain]"))
    elif identical == 0:
        verdict = (f"NONE IDENTICAL ({comparable} compared) — "
                   + ("EXPECTED: a predicted variable on the standard chain stores its codes "
                      "where the container stores residuals"
                      if not expected_identity else
                      "UNEXPECTED: identity was expected on this chain"))
    else:
        verdict = (f"MIXED — {identical} identical of {comparable}; "
                   "neither all nor none, which the profile does not predict")
    print(f"  (b) comparable chunks={comparable} byte-identical={identical} "
          f"chain={chain} index_location={index_location}")
    print(f"      verdict: {verdict}")

    # (c) shard index CRC-32C already asserted inside read_shard_index.
    print(f"  (c) shard index CRC-32C verified over {chunks_per_shard} entries")
    return 1 if mismatched else 0


if __name__ == "__main__":
    raise SystemExit(main())
