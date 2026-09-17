"""Pull the published STAC catalog and inventory every artifact it names.

The catalog is the machine-readable index of everything live: one collection
per source, one Item per run / issue / case, one asset per artifact with its
byte size and CRC-32 in the asset's own fields. It is the right source for
those numbers -- this study once reverse-engineered a store's size out of the
manifest's `bandwidth`, which is an HLS bitrate at 12 fps and not a byte
count, and got a wrong answer from it.

It also opens a store the way the project's own README says to, so the
ecosystem path is exercised rather than assumed.

Usage: uv run python scripts/catalog_inventory.py [catalog-url] [out.json]
"""

from __future__ import annotations

import json
import sys

import pystac

DEFAULT_URL = "https://dataset.ringsaturn.me/xue/catalog.json"


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    out = sys.argv[2] if len(sys.argv) > 2 else None
    catalog = pystac.Catalog.from_file(url)
    print(f"catalog {catalog.id} / {catalog.title}  <- {url}\n")

    print(f"{'collection':11} {'live item':30} {'时间':17} {'assets':>6}")
    print("-" * 70)
    collections = []
    for child in catalog.get_children():
        items = list(child.get_items())
        if not items:
            print(f"{child.id:11} (无 live item)")
            collections.append({"id": child.id, "item": None})
            continue
        item = items[0]
        when = str(item.properties.get("datetime") or item.properties.get("start_datetime") or "")
        print(f"{child.id:11} {item.id[:29]:30} {when[:16]:17} {len(item.assets):>6}")
        collections.append({"id": child.id, "item": item.id, "assets": len(item.assets)})

    # Every asset the catalog names, with the numbers it publishes for it.
    rows = []
    for child in catalog.get_children():
        for item in child.get_items():
            for name, asset in item.assets.items():
                extra = asset.extra_fields or {}
                rows.append({
                    "collection": child.id,
                    "item": item.id,
                    "asset": name,
                    "kind": extra.get("xue:kind"),
                    "tier": extra.get("xue:tier"),
                    "mediaType": asset.media_type,
                    "size": extra.get("file:size"),
                    "crc32": extra.get("xue:crc32"),
                    "href": asset.get_absolute_href(),
                })
    stores = [r for r in rows if r["kind"] == "store"]
    full = sum(r["size"] for r in stores if r["tier"] == "full")
    half = sum(r["size"] for r in stores if r["tier"] == "half")
    print(f"\nassets {len(rows)} 个；其中 store {len(stores)} 个"
          f"（全分辨率 {full:,} 字节，半分辨率 {half:,} 字节，合计 {full + half:,}）")

    # The README's own recipe, exercised rather than assumed.
    run = next(catalog.get_child("gfs").get_items())
    href = run.assets["tmp2m"].get_absolute_href()
    print(f"\nREADME 的方子: xr.open_zarr({href})")
    try:
        import xarray as xr

        dataset = xr.open_zarr(href)
        field = dataset["tmp2m"]
        print(f"  打开成功 — dims {dict(field.sizes)}，"
              f"解码后 {float(field.isel(time=0).min()):.1f}..{float(field.isel(time=0).max()):.1f} °C")
    except Exception as exc:  # noqa: BLE001 - report whatever it is
        print(f"  打开失败 — {type(exc).__name__}: {str(exc)[:120]}")

    if out:
        with open(out, "w", encoding="utf-8") as handle:
            json.dump({"catalog": url, "collections": collections, "assets": rows},
                      handle, ensure_ascii=False, indent=1)
        print(f"\n写入 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
