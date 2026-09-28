"""ERA5 source adapter: collect `sp` and `sst` into the append-only archive, then process.

Contract: experiments/continuous-assimilation/contract-era5-source-v1.json

WHY THIS COLLECTOR IS DIFFERENT FROM THE gfs ONE
------------------------------------------------
The gfs collector exists because that service keeps only the newest run -- not freezing
today loses today forever. ARCO-ERA5 is a permanent archive back to 1940, so **nothing is
lost by waiting**; this collector is for convenience and consistency, not rescue. That also
means a gap can be filled later, unlike a gfs gap.

WHAT IS KEPT, AND WHAT IS THROWN AWAY (a deliberate, declared choice)
--------------------------------------------------------------------
Downloaded: the raw daily files carry 24 hourly steps (33.7 MB for sp, 23.6 MB for sst per
day). The HDF5/NetCDF chunking is (12, 361, 720), so reading the four synoptic steps pulls
essentially the whole file -- about 57 MB/day of egress either way.
Stored: the **four synoptic fields (00/06/12/18Z) at native 0.25 degrees, per day**, as
float32. That is ~33 MB/day (both variables) rather than the ~1.7 GB/day of raw files, and
it keeps exactly the sampling that the R1 monthly means the model was trained on use.
Discarded: the other 20 hourly steps.

The reusable readers and the conservative regrid are IMPORTED from probe_era5 rather than
re-implemented: that module is a frozen evidence artifact, and its regrid is the one whose
identity behaviour control C2a already validated. Two divergent regrids is exactly how this
project has been bitten before.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
FEASIBILITY = HERE.parent / 'era5-sp-sst-feasibility'
for _p in (str(HERE), str(HERE.parent), str(FEASIBILITY)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import cas                       # noqa: E402  (ROOT, ledgers, sha256, atomic write)
# Deliberate cross-experiment import: probe_era5.py is the frozen feasibility artifact whose
# reader and conservative regrid are the ones validated by control C2a (identity regrid == 0)
# and which produced the numbers cited in docs/maintenance/2026-09-28-era5-sp-sst-feasibility.md.
# Copying that regrid here instead would create exactly the kind of two-divergent-copies bug
# this project keeps hitting.
import probe_era5 as P           # noqa: E402  (read_day, regrid_conservative, gates)

VARIABLES = {'sp': 'surface_pressure', 'sst': 'sea_surface_temperature'}
UNITS = {'sp': 'Pa', 'sst': 'K'}
# Daily-range declarations. Wider than the monthly ranges used by the probe, because daily
# extremes are wider; still far from what a unit mix-up would produce (hPa -> ~1000,
# degC -> -10..40), which is the only thing these gates are here to catch.
DAILY_RANGE = {'sp': (4.5e4, 1.11e5), 'sst': (264.0, 316.0)}
MIN_VALID_CELLS = {'sp': 20000, 'sst': 5000}
HOURS = P.HOURS
ERA5_ROOT = cas.ROOT / 'raw' / 'era5'
MONTH_ROOT = cas.ROOT / 'monthly' / 'era5'
STORAGE_CAP = 20 * 1024 ** 3
R1_INPUTS = Path('/home/ubuntu/climatetensor-inputs/ncep-multivariate-ext-202602')
BACKFILL_FROM = '2026-09-01'

FAILURES: list[str] = []


def log(msg) -> None:
    print(msg, flush=True)


def _manifest_day(day: str) -> Path:
    return ERA5_ROOT / day / 'manifest.json'


def frozen_days() -> set[str]:
    out = set()
    if ERA5_ROOT.is_dir():
        for child in ERA5_ROOT.iterdir():
            if (child / 'manifest.json').is_file():
                out.add(child.name)
    return out


def era5_storage() -> int:
    total = 0
    if ERA5_ROOT.is_dir():
        for path in ERA5_ROOT.rglob('*'):
            if path.is_file():
                total += path.stat().st_size
    return total


def probe() -> dict:
    """Newest day for which each variable exists, and the days still missing from the archive."""
    per_var, newest = {}, None
    for code, var in VARIABLES.items():
        d = P.days_available(2026, 9, var)
        per_var[code] = {'variable': var, 'days_in_2026_09': len(d), 'last': d[-1] if d else None}
        if d:
            cand = f'2026-09-{d[-1]}'
            newest = cand if newest is None or cand > newest else newest
    have = frozen_days()
    return {'per_variable': per_var, 'newest_day': newest, 'archive_days': sorted(have),
            'archive_n_days': len(have), 'storage_bytes': era5_storage(),
            'storage_cap_bytes': STORAGE_CAP}


def days_between(start: str, end: str) -> list[str]:
    a = np.datetime64(start)
    b = np.datetime64(end)
    return [str(a + int(k)) for k in range(int((b - a).astype(int)) + 1)]


def day_gate(code: str, arr: np.ndarray) -> dict:
    """Per-day magnitude and coverage gate for one channel.

    Factored out so the negative controls can call it directly (C1: Pa mislabelled as hPa
    must be refused; C3: an all-missing array must be refused). The gate guards UNIT
    MIX-UPS, not geophysics -- hPa would give ~1000 and degC ~-10..40, both far outside.
    """
    lo, hi = DAILY_RANGE[code]
    good = np.isfinite(arr)
    vals = arr[good]
    cells = int(good.sum())
    range_ok = bool(vals.size and vals.min() >= lo and vals.max() <= hi)
    cells_ok = cells >= MIN_VALID_CELLS[code]
    return {'channel': code, 'declared_units': UNITS[code], 'range_declared': [lo, hi],
            'min': float(vals.min()) if vals.size else None,
            'max': float(vals.max()) if vals.size else None,
            'valid_cells': cells, 'range_ok': range_ok, 'cells_ok': cells_ok,
            'ok': bool(range_ok and cells_ok)}


def selftest() -> int:
    """The three negative controls from the contract. No network, no archive writes."""
    import tempfile
    results = []

    def check(name, ok, detail=''):
        results.append((name, bool(ok), detail))
        log(('PASS  ' if ok else 'FAIL  ') + name + (f'  -- {detail}' if detail else ''))

    # Shape matters: the gate also requires a minimum number of valid cells (sp >= 20000),
    # so a tiny fixture fails for the wrong reason. (That is exactly what the first version
    # of this test did -- the gate was right, the fixture was too small.)
    real = np.full((4, 200, 200), 98000.0)
    check('C1 量级闸门接受 Pa 量级', day_gate('sp', real)['ok'])
    check('C1 量级闸门拒绝 hPa 误标', not day_gate('sp', real / 100.0)['ok'],
          f"min {float((real / 100).min())}")
    sst_c = np.full((4, 200, 200), 12.0)
    check('C1 量级闸门拒绝 degC 误标为 K', not day_gate('sst', sst_c)['ok'])
    check('C3 全缺测数组被拒', not day_gate('sst', np.full((4, 200, 200), np.nan))['ok'])
    raw_missing = np.full((4, 200, 200), 3.4028234663852886e38)
    raw_missing[raw_missing > 1e30] = np.nan          # the conversion read_day() performs
    check('C3 缺测值 3.4e38 经转换后不被当作有效值', not day_gate('sp', raw_missing)['ok'])
    # C2 去重：把 ERA5_ROOT 指到临时目录，避免碰真档案
    global ERA5_ROOT
    keep = ERA5_ROOT
    with tempfile.TemporaryDirectory() as tmp:
        ERA5_ROOT = Path(tmp) / 'era5'
        (ERA5_ROOT / '2026-09-01').mkdir(parents=True)
        (ERA5_ROOT / '2026-09-01' / 'manifest.json').write_text('{}')
        rec = freeze_day('2026-09-01', dry_run=True)
        check('C2 已冻结的日必须去重', rec['status'] == 'duplicate_skipped', rec['status'])
    ERA5_ROOT = keep
    bad = [r for r in results if not r[1]]
    log(f'{len(results) - len(bad)}/{len(results)} 项对照通过')
    return 1 if bad else 0


def freeze_day(day: str, dry_run: bool = False) -> dict:
    """Freeze one day: the four synoptic fields of both variables, native grid, append-only."""
    rec = {'event': 'era5_freeze', 'day': day, 'attempted_utc': cas.utcnow()}
    if _manifest_day(day).is_file():
        rec.update({'status': 'duplicate_skipped', 'why': 'day already frozen (G-D)'})
        cas.append_jsonl('era5_frozen.jsonl', rec)
        return rec
    if era5_storage() > STORAGE_CAP:
        rec.update({'status': 'refused_storage_cap',
                    'why': f'era5 archive {era5_storage()} > cap {STORAGE_CAP}; refusing to '
                           f'freeze, NOT deleting anything'})
        cas.append_jsonl('era5_frozen.jsonl', rec)
        return rec
    if dry_run:
        rec.update({'status': 'dry_run'})
        cas.append_jsonl('era5_frozen.jsonl', rec)
        return rec

    y, m, d = day.split('-')
    arrays, meta, checks, formats = {}, {}, [], set()
    for code, var in VARIABLES.items():
        try:
            arr, lat, lon, units, name, engine = P.read_day(var, int(y), int(m), d)
        except Exception as exc:                                   # noqa: BLE001
            rec.update({'status': 'refused_read_error', 'variable': code,
                        'why': f'{type(exc).__name__}: {exc}'})
            cas.append_jsonl('era5_frozen.jsonl', rec)
            return rec
        formats.add(engine)
        gate = day_gate(code, arr)
        gate['era5_variable'] = var
        gate['observed_units_attr'] = units
        checks.append(gate)
        if not gate['ok']:
            rec.update({'status': 'refused_gate', 'checks': checks,
                        'why': f"{code}: range_ok={gate['range_ok']}, "
                               f"valid_cells={gate['valid_cells']}"})
            cas.append_jsonl('era5_frozen.jsonl', rec)
            return rec
        arrays[code] = arr.astype(np.float32)
        meta[code] = (lat, lon)

    outdir = ERA5_ROOT / day
    outdir.mkdir(parents=True, exist_ok=True)
    files = {}
    for code, arr in arrays.items():
        lat, lon = meta[code]
        p = outdir / f'{code}.npz'
        np.savez_compressed(p, values=arr, hours=np.array(HOURS),
                            latitude=np.asarray(lat, dtype=np.float32),
                            longitude=np.asarray(lon, dtype=np.float32),
                            units=np.array(UNITS[code]))
        files[code] = {'file': p.name, 'sha256': cas.sha256_file(p), 'bytes': p.stat().st_size}
    man = {'day': day, 'frozen_utc': cas.utcnow(), 'source': 'ARCO-ERA5 (public GCS bucket)',
           'files': files, 'checks': checks, 'file_formats_seen': sorted(formats),
           'hours_kept': list(HOURS), 'discarded': 'the other 20 hourly steps',
           'native_grid': {c: [int(v[0].size), int(v[1].size)] for c, v in meta.items()},
           'note': 'four synoptic fields per day; daily mean is formed at aggregation time'}
    cas.write_json_atomic(outdir / 'manifest.json', man)
    rec.update({'status': 'written', 'files': {k: v['bytes'] for k, v in files.items()},
                'checks': checks, 'total_bytes': sum(v['bytes'] for v in files.values())})
    cas.append_jsonl('era5_frozen.jsonl', rec)
    return rec


def collect(from_day: str, newest: str, dry_run: bool = False, max_days: int = 40) -> dict:
    have = frozen_days()
    todo = [d for d in days_between(from_day, newest) if d not in have][:max_days]
    log(f'ERA5 采集：{from_day} .. {newest}，缺 {len(todo)} 天 → {todo[:3]}{"..." if len(todo) > 3 else ""}')
    done, skipped, refused = [], 0, []
    for day in todo:
        rec = freeze_day(day, dry_run=dry_run)
        if rec['status'] == 'written':
            done.append(day)
            log(f'  冻结 {day}  {rec["total_bytes"] / 1e6:.1f} MB')
        elif rec['status'] == 'duplicate_skipped':
            skipped += 1
        else:
            refused.append({'day': day, 'status': rec['status'], 'why': rec.get('why')})
            log(f'  ** 拒绝 {day}: {rec["status"]} {rec.get("why")}')
            FAILURES.append(f'{day}: {rec["status"]}: {rec.get("why")}')
    return {'from': from_day, 'to': newest, 'frozen': done, 'skipped': skipped,
            'refused': refused, 'storage_bytes': era5_storage()}


def month_days_uniform(month: str) -> list[str]:
    return cas.month_days(month)


def aggregate_month(month: str, dry_run: bool = False) -> dict:
    """Monthly mean of daily means at native 0.25 deg, with a completeness report."""
    outdir = MONTH_ROOT / month
    rec = {'event': 'era5_month', 'month': month, 'attempted_utc': cas.utcnow()}
    if (outdir / 'manifest.json').is_file():
        rec.update({'status': 'already_present'})
        cas.append_jsonl('era5_months.jsonl', rec)
        return rec
    days = [d for d in month_days_uniform(month) if _manifest_day(d).is_file()]
    if not days:
        rec.update({'status': 'no_days'})
        cas.append_jsonl('era5_months.jsonl', rec)
        return rec
    acc, seen, lat, lon = {}, {}, None, None
    for day in days:
        with np.load(ERA5_ROOT / day / 'sp.npz') as z:
            lat, lon = np.asarray(z['latitude'], dtype=float), np.asarray(z['longitude'], dtype=float)
        for code in VARIABLES:
            with np.load(ERA5_ROOT / day / f'{code}.npz') as z:
                arr = np.asarray(z['values'], dtype=np.float64)
            good_h = np.isfinite(arr)
            with np.errstate(invalid='ignore', divide='ignore'):
                day_mean = np.where(good_h.any(axis=0),
                                    np.nansum(arr, axis=0) / np.maximum(good_h.sum(axis=0), 1),
                                    np.nan)
            acc[code] = acc.get(code, np.zeros_like(day_mean)) + np.nan_to_num(day_mean, nan=0.0)
            seen[code] = seen.get(code, np.zeros_like(day_mean)) + np.isfinite(day_mean)
    with np.errstate(invalid='ignore', divide='ignore'):
        fields = {c: np.where(seen[c] > 0, acc[c] / np.maximum(seen[c], 1), np.nan) for c in acc}
    if dry_run:
        rec.update({'status': 'dry_run', 'days': days})
        cas.append_jsonl('era5_months.jsonl', rec)
        return rec
    outdir.mkdir(parents=True, exist_ok=True)
    files = {}
    for code, field in fields.items():
        p = outdir / f'{code}.npz'
        np.savez_compressed(p, values=field.astype(np.float32),
                            latitude=lat.astype(np.float32), longitude=lon.astype(np.float32),
                            units=np.array(UNITS[code]))
        files[code] = {'file': p.name, 'sha256': cas.sha256_file(p), 'bytes': p.stat().st_size,
                       'valid_cells': int(np.isfinite(field).sum())}
    expected = len(month_days_uniform(month))
    man = {'month': month, 'days_used': days, 'n_days': len(days), 'days_expected': expected,
           'complete': len(days) == expected, 'files': files, 'native_grid': [int(len(lat)), int(len(lon))],
           'caliber': 'monthly mean of daily means; daily mean = mean of the 00/06/12/18Z fields',
           'frozen_utc': cas.utcnow()}
    cas.write_json_atomic(outdir / 'manifest.json', man)
    rec.update({'status': 'written', 'n_days': len(days), 'days_expected': expected,
                'complete': man['complete'],
                'files': {k: v['bytes'] for k, v in files.items()}})
    cas.append_jsonl('era5_months.jsonl', rec)
    return rec


def process_month(month: str) -> dict:
    """Compare the ERA5 month against R1 when they overlap; never writes into the analysis."""
    man = MONTH_ROOT / month / 'manifest.json'
    if not man.is_file():
        return {'month': month, 'status': 'not_aggregated'}
    m = json.loads(man.read_text())
    out = {'month': month, 'n_days': m['n_days'], 'complete': m['complete'],
           'overlap_with_r1': None, 'channels': {}}
    for code in VARIABLES:
        with np.load(MONTH_ROOT / month / f'{code}.npz') as z:
            era = np.asarray(z['values'], dtype=float)
            elat, elon = np.asarray(z['latitude'], float), np.asarray(z['longitude'], float)
        f = R1_INPUTS / f'{code}.npz'
        if not f.is_file():
            out['channels'][code] = {'status': 'no_r1_channel_file'}
            continue
        with np.load(f) as z:
            t = np.asarray(z['time']).astype(str)
            hit = np.flatnonzero(np.char.startswith(t, month))
            if hit.size == 0:
                out['channels'][code] = {'status': 'no_overlap',
                                         'r1_last_month': str(t[-1])[:7],
                                         'why': 'R1 does not reach this month yet; nothing to compare'}
                out['overlap_with_r1'] = False
                continue
            r1 = np.asarray(z['values'][int(hit[0])], dtype=float)
            rlat, rlon = np.asarray(z['lat'], float), np.asarray(z['lon'], float)
        era_r = P.regrid_conservative(era, elat, elon, rlat, rlon)
        both = np.isfinite(r1) & np.isfinite(era_r)
        d = (era_r - r1)[both]
        ad = np.abs(d)
        out['overlap_with_r1'] = True
        out['channels'][code] = {
            'status': 'compared', 'unit': UNITS[code], 'n_compared': int(both.sum()),
            'signed_mean': float(d.mean()), 'median': float(np.median(d)),
            'std': float(d.std()), 'median_abs': float(np.median(ad)),
            'p95_abs': float(np.percentile(ad, 95)), 'max_abs': float(ad.max()),
            'frac_abs_lt_1': float(np.mean(ad < (1.0 if code == 'sst' else 100.0))),
            'r1_month_used': month}
    cas.write_json_atomic(MONTH_ROOT / month / 'comparison.json', out)
    return out


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description='ERA5 sp/sst collection and processing')
    ap.add_argument('--from', dest='start', default=BACKFILL_FROM)
    ap.add_argument('--max-days', type=int, default=40)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--no-process', action='store_true')
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args(argv)
    cas.ensure_dirs()
    if a.selftest:
        return selftest()
    p = probe()
    log('ERA5 探测: ' + json.dumps({k: v for k, v in p.items() if k != 'archive_days'},
                                  ensure_ascii=False))
    res = {'probe': {k: v for k, v in p.items() if k != 'archive_days'}, 'collect': None, 'months': []}
    if p['newest_day']:
        res['collect'] = collect(a.start, p['newest_day'], dry_run=a.dry_run, max_days=a.max_days)
    for month in sorted({d[:7] for d in frozen_days()}):
        agg = aggregate_month(month, dry_run=a.dry_run)
        log(f"月聚合 {month}: {agg['status']}"
            + (f"  {agg.get('n_days')}/{agg.get('days_expected')} 天 complete={agg.get('complete')}"
               if agg['status'] == 'written' else ''))
        if agg['status'] in ('written', 'already_present') and not a.no_process:
            pr = process_month(month)
            res['months'].append(pr)
            for code, v in pr.get('channels', {}).items():
                if v.get('status') == 'compared':
                    log(f"    {code} 与 R1 比较: 偏差 {v['signed_mean']:+.3f} 中位|差| {v['median_abs']:.3f} "
                        f"p95 {v['p95_abs']:.3f} max {v['max_abs']:.3f} {v['unit']}（n={v['n_compared']}）")
                else:
                    log(f"    {code}: {v.get('status')} {v.get('why','')}")
    cas.write_json_atomic(cas.ledger_path('era5_status.json'),
                          {'generated_utc': cas.utcnow(), **p,
                           'last_run': {'frozen': (res['collect'] or {}).get('frozen', []),
                                        'refused': (res['collect'] or {}).get('refused', []),
                                        'failures': FAILURES}})
    log(json.dumps({'failures': FAILURES, 'storage_bytes': era5_storage()}, ensure_ascii=False))
    return 1 if FAILURES else 0


if __name__ == '__main__':
    raise SystemExit(main())
