"""Render the state of the block into the viewer's own static directory.

WHY A SNAPSHOT RATHER THAN A LIVE FEED
--------------------------------------
The viewer is a Vite dev server whose `publicDir` is served at the same origin
as the app, so a file written there is reachable at the same host and port with
no second server and no CORS.  What it shows is a SNAPSHOT of the archive as of
the last regeneration, and the page says so, because a monitoring page that
looks live while showing stale numbers is worse than one that is honestly
static.

WHAT IT DELIBERATELY DOES NOT CLAIM
-----------------------------------
The archive is NOT in the upstream catalog's layout.  Upstream is a STAC tree
(`catalog.json` -> `<collection>/collection.json` -> items with asset hrefs);
this archive is `<collection>/<item id>/<asset>`, with Zarr stores flattened to
avoid deep paths.  So this page reports the block; it does not feed the existing
player, and pretending otherwise would produce a page that silently shows
nothing.

Usage:
  python3 scripts/block_page.py                     # write into the viewer
  python3 scripts/block_page.py --out /somewhere    # write elsewhere
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = Path("/tmp/xue-upstream/web/public")

# Perishability, as measured: the collection whose upstream window is shortest
# is listed first, because that is the one whose absence is permanent.
ORDER = ["cma", "mrms", "jma", "sounding", "airport", "gfs", "ecmwf", "aifs",
         "sflux", "hrrr", "himawari", "goeseast", "goeswest", "meteosat",
         "tc", "showcase"]


def parse_ts(s):
    if not isinstance(s, str):
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def collection_summary(archive: Path, name: str) -> dict:
    d = archive / name
    out = {"name": name, "items": 0, "bytes": 0, "first": None, "last": None,
           "assets": {}, "note": ""}
    if not d.is_dir():
        return out
    ids = []
    for item in sorted(d.iterdir()):
        if not item.is_dir():
            continue
        out["items"] += 1
        ids.append(item.name)
        for f in item.rglob("*"):
            if f.is_file():
                out["bytes"] += f.stat().st_size
                key = f.name.split("__")[0] if "__" in f.name else f.name
                out["assets"][key] = out["assets"].get(key, 0) + 1
        # Prefer the item's own declared window; fall back to the id.
        ij = item / "item.json"
        if ij.exists():
            try:
                props = json.loads(ij.read_text()).get("properties", {})
                a, b = parse_ts(props.get("start_datetime")), parse_ts(props.get("end_datetime"))
                if a:
                    out["first"] = min(out["first"], a) if out["first"] else a
                if b:
                    out["last"] = max(out["last"], b) if out["last"] else b
            except Exception:
                pass
    # Emit ISO strings, not datetimes: the first run of this script died here
    # with "Object of type datetime is not JSON serializable".
    for k in ("first", "last"):
        if out[k] is not None:
            out[k] = out[k].isoformat(timespec="seconds")
    out["id_first"], out["id_last"] = (ids[0], ids[-1]) if ids else (None, None)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", default=str(ROOT / "archive"))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    archive = Path(args.archive)
    out_dir = Path(args.out)

    cols = [collection_summary(archive, n) for n in ORDER]
    for extra in sorted(p.name for p in archive.iterdir()
                        if p.is_dir() and p.name not in ORDER):
        cols.append(collection_summary(archive, extra))

    idx_path = archive / "index.json"
    idx = json.loads(idx_path.read_text()) if idx_path.exists() else {"seen": {}, "misses": []}
    last = archive / "last-pass.json"
    last_pass = json.loads(last.read_text()) if last.exists() else {}

    unreachable = sorted(k for k, v in (last_pass.get("collections") or {}).items()
                         if v.get("state") == "unreachable")

    block = {
        "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "archive": str(archive),
        "items_indexed": len(idx.get("seen", {})),
        "misses_recorded": len(idx.get("misses", [])),
        "last_pass": last_pass.get("at"),
        "unreachable": unreachable,
        "total_bytes": sum(c["bytes"] for c in cols),
        "collections": cols,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "block.json").write_text(json.dumps(block, indent=1, ensure_ascii=False))
    (out_dir / "block.html").write_text(PAGE, encoding="utf-8")
    print(f"  wrote {out_dir/'block.json'} and block.html")
    print(f"  {block['items_indexed']} items, {block['total_bytes']/1e6:.1f} MB, "
          f"{len(unreachable)} unreachable")
    return 0


PAGE = """<!doctype html>
<html lang="zh">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>团块 · block</title>
<style>
 :root { color-scheme: dark; --fg:#e8eaed; --dim:#9aa0a6; --line:#2b2f33;
         --ok:#57d9a3; --warn:#f5c26b; --bad:#ff7b72; --bg:#16181b; }
 body { margin:0; padding:24px; background:var(--bg); color:var(--fg);
        font:14px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace; }
 h1 { font-size:17px; margin:0 0 4px; font-weight:600; }
 .sub { color:var(--dim); font-size:12px; margin-bottom:18px; }
 .stale { color:var(--warn); }
 table { border-collapse:collapse; width:100%; max-width:1000px; }
 th,td { text-align:left; padding:5px 10px 5px 0; border-bottom:1px solid var(--line);
         font-size:13px; white-space:nowrap; }
 th { color:var(--dim); font-weight:500; }
 td.n { text-align:right; font-variant-numeric:tabular-nums; }
 .bar { display:inline-block; height:9px; background:var(--ok); vertical-align:middle;
        border-radius:2px; min-width:1px; }
 .absent { color:var(--bad); }
 .warnrow { color:var(--warn); }
 .note { color:var(--dim); font-size:12px; margin-top:16px; max-width:1000px; }
 code { color:var(--ok); }
</style>
<h1>团块 · block</h1>
<div class="sub" id="sub">读取中…</div>
<div id="body"></div>
<div class="note">
 本页显示的是 <code>archive/</code> 的<strong>快照</strong>，不是实时流 ——
 由 <code>scripts/block_page.py</code> 生成。上游最易失的是 <code>cma</code>
 （实测窗口仅 2.4 小时），故排序把它放最前。<br>
 「不可达」是上游声明了却取不到的源，与「尚未收到」区分开：
 前者是上游的问题，后者只是还没轮到。
</div>
<script>
const pct = (v,mx) => mx>0 ? Math.max(1, Math.round(100*v/mx)) : 0;
const fmt = n => n>=1e9 ? (n/1e9).toFixed(2)+' GB'
              : n>=1e6 ? (n/1e6).toFixed(1)+' MB'
              : n>=1e3 ? (n/1e3).toFixed(1)+' kB' : n+' B';
const age = s => { const d=(Date.now()-new Date(s))/1000;
  return d<90 ? Math.round(d)+' 秒前' : d<5400 ? Math.round(d/60)+' 分钟前'
       : (d/3600).toFixed(1)+' 小时前'; };
fetch('/block.json',{cache:'no-store'}).then(r=>r.json()).then(b=>{
  const mx = Math.max(...b.collections.map(c=>c.bytes), 1);
  document.getElementById('sub').innerHTML =
    `生成于 <span class="stale">${age(b.generated)}</span> · 索引 ${b.items_indexed} 条 · `
  + `共 ${fmt(b.total_bytes)} · 最近一轮 ${b.last_pass ? age(b.last_pass) : '—'}`;
  const rows = b.collections.map(c=>{
    const un = b.unreachable.includes(c.name);
    const span = (c.first && c.last)
      ? `${c.first.slice(5,16).replace('T',' ')} → ${c.last.slice(5,16).replace('T',' ')}`
      : '—';
    const cls = un ? 'absent' : (c.items===0 ? 'warnrow' : '');
    return `<tr class="${cls}">
      <td>${c.name}${un?' ✕':''}</td>
      <td class="n">${c.items||''}</td>
      <td><span class="bar" style="width:${pct(c.bytes,mx)}px"></span></td>
      <td class="n">${c.bytes?fmt(c.bytes):''}</td>
      <td>${span}</td>
      <td style="color:var(--dim)">${Object.entries(c.assets).slice(0,5)
          .map(([k,v])=>k+(v>1?'×'+v:'')).join(' ')}</td></tr>`;}).join('');
  document.getElementById('body').innerHTML =
    `<table><tr><th>collection</th><th class="n">条目</th><th></th>
      <th class="n">占用</th><th>窗口</th><th>资产</th></tr>${rows}</table>`;
  if (b.unreachable.length)
    document.getElementById('body').insertAdjacentHTML('beforeend',
      `<div class="note absent">上游声明但取不到：${b.unreachable.join(', ')}</div>`);
}).catch(e=>{ document.getElementById('sub').textContent = '读取失败: '+e; });
</script>
</html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
