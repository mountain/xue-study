"""Continuous assimilation — one entry point for the timer, and for the operator.

    python orchestrate.py cycle            # what the timer runs: probe, freeze, aggregate,
                                           # analyse, forecast, verify, status
    python orchestrate.py probe            # what is live right now?
    python orchestrate.py freeze           # probe + freeze the newest analysis
    python orchestrate.py aggregate --month 2026-10
    python orchestrate.py analyze  --month 2026-10
    python orchestrate.py verify
    python orchestrate.py status
    python orchestrate.py selftest         # offline checks + frozen-report reproduction

Exit codes: 0 = cycle completed (whatever it found), 1 = tool failure (a gate or a
control broke), 2 = a loud operational stop (storage cap). "No new data" is NOT a
failure: it is the normal state and it is recorded.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np                                          # noqa: E402
import cas                                                  # noqa: E402
import casmodel                                             # noqa: E402

FAILURES: list[str] = []


def step(label: str, payload: dict) -> None:
    print(f'--- {label} ---', flush=True)
    print(json.dumps(payload, ensure_ascii=False, default=str)[:2000], flush=True)


def do_probe(collections: list[str]) -> list[dict]:
    out = []
    for c in collections:
        p = cas.probe_collection(c)
        if p.get('ok'):
            known = {r.get('run_id') for r in cas.read_jsonl('frozen.jsonl')
                     if r.get('status') == 'written'}
            p['already_frozen'] = p['run_id'] in known
            p.pop('assets', None)
        step(f'probe {c}', {k: v for k, v in p.items() if k != 'assets'})
        out.append(p)
    return out


def do_freeze(probes: list[dict], dry_run: bool) -> list[dict]:
    out = []
    for p in probes:
        if not p.get('ok'):
            cas.append_jsonl('frozen.jsonl', {'event': 'freeze', 'collection': p.get('collection'),
                                              'status': 'probe_failed', 'why': p.get('error'),
                                              'attempted_utc': cas.utcnow()})
            continue
        if p.get('already_frozen'):
            rec = {'collection': p['collection'], 'status': 'already_frozen', 'run_id': p['run_id']}
            step(f"freeze {p['collection']}", rec)      # a timer log must not go silent
            out.append(rec)
            continue
        full = cas.probe_collection(p['collection'])          # need the assets again
        rec = cas.freeze_run(p['collection'], full, dry_run=dry_run)
        step(f"freeze {p['collection']}", {k: rec.get(k) for k in
                                           ('run_id', 'status', 'bytes', 'variables_failed',
                                            'variables_missing_asset', 'why')})
        out.append(rec)
    return out


def do_aggregate(months: list[str] | None) -> list[dict]:
    if months:
        months = list(months)
    else:
        found = set()
        for run_dir in sorted((cas.ROOT / 'raw').glob('*/*')):
            if (run_dir / 'manifest.json').is_file():
                man = json.loads((run_dir / 'manifest.json').read_text())
                ref = str(man.get('reference_datetime') or '')
                if len(ref) >= 7:
                    found.add(ref[:7])
        months = sorted(found)
    lat = np.linspace(90, -90, 73)
    lon = np.linspace(0, 360 - 360 / 144, 144)
    out = []
    for month in months:
        rec = cas.monthly_mean('gfs', month, np.linspace(90, -90, cas.NATIVE_GRID[0]),
                               np.linspace(-180, 180 - 360 / cas.NATIVE_GRID[1], cas.NATIVE_GRID[1]),
                               lat, lon)
        if rec['status'] != 'ok':
            step(f'aggregate {month}', {'status': rec['status']})
            out.append(rec)
            continue
        day_dir = cas.ROOT / 'monthly' / month
        day_dir.mkdir(parents=True, exist_ok=True)
        out_path = day_dir / 'model25.npz'
        if out_path.is_file():
            step(f'aggregate {month}', {'status': 'already_present', 'path': str(out_path)})
            out.append({'month': month, 'status': 'already_present'})
            continue
        np.savez_compressed(out_path, latitude=lat, longitude=lon, **rec['model'])
        man = {'month': month, 'collection': rec['collection'], 'n_days': rec['n_days'],
               'days_expected': rec['days_expected'], 'complete': rec['complete'],
               'days_used': rec['days_used'], 'synoptic_per_day': rec['synoptic_per_day'],
               'file': out_path.name, 'sha256': cas.sha256_file(out_path),
               'variables': sorted(rec['model']),
               'caliber_changes': ['0.25 -> 2.5 deg box average (cosine weighted)',
                                   'synoptic analyses -> daily mean -> monthly mean']}
        cas.write_json_atomic(day_dir / 'manifest.json', man)
        step(f'aggregate {month}', {k: man[k] for k in ('n_days', 'days_expected', 'complete',
                                                        'sha256')})
        out.append(man)
    return out


def do_cycle(dry_run: bool) -> int:
    started = time.perf_counter()
    record = {'event': 'cycle', 'started_utc': cas.utcnow(), 'dry_run': dry_run,
              'steps': {}}
    # G1: read-only artifacts must be unchanged
    ro_before = _readonly_hashes()
    try:
        probes = do_probe(cas.POLL_COLLECTIONS)
        record['steps']['probe'] = [{'collection': p.get('collection'), 'ok': p.get('ok'),
                                     'run_id': p.get('run_id'),
                                     'already_frozen': p.get('already_frozen')} for p in probes]
        frozen = do_freeze(probes, dry_run)
        record['steps']['freeze'] = [{'collection': f.get('collection'), 'status': f.get('status'),
                                      'run_id': f.get('run_id')} for f in frozen]
        agg = do_aggregate(None)
        record['steps']['aggregate'] = [{'month': a.get('month'), 'status': a.get('status', 'ok'),
                                         'complete': a.get('complete')} for a in agg]
        analysed = []
        for a in agg:
            if a.get('month'):
                if True:
                    res = casmodel.build_analysis('gfs', a['month'])
                    step(f"analyze {a['month']}", {k: res.get(k) for k in
                                                   ('status', 'coefficients_built',
                                                    'coefficients_expected', 'why_blocked')})
                    if res.get('status') == 'ok':
                        issued = casmodel.issue_forecast(res)
                        step('forecast', {k: issued.get(k) for k in
                                          ('event', 'initial_month', 'target_months', 'status', 'why')})
                    analysed.append({'month': a['month'], 'status': res.get('status'),
                                     'why_blocked': res.get('why_blocked')})
        record['steps']['analysis'] = analysed
        ver = casmodel.verify_due()
        record['steps']['verify'] = {'scored': len(ver['scored']), 'pending': len(ver['pending']),
                                     'pending_example': (ver['pending'][0] if ver['pending'] else None)}
        step('verify', record['steps']['verify'])
    except Exception as exc:                                   # noqa: BLE001
        FAILURES.append(f'{type(exc).__name__}: {exc}')
        record['traceback'] = traceback.format_exc()
    finally:
        ro_after = _readonly_hashes()
        if ro_before != ro_after:
            FAILURES.append('G1 failed: a read-only artifact changed during the cycle')
        record['gates'] = {'G1_read_only_unchanged': ro_before == ro_after}
        record['storage_bytes'] = cas.storage_used()
        record['storage_cap_bytes'] = cas.STORAGE_CAP
        record['failures'] = list(FAILURES)
        record['wall_seconds'] = round(time.perf_counter() - started, 1)
        record['finished_utc'] = cas.utcnow()
        cas.append_jsonl('runs.jsonl', record)
        cas.write_json_atomic(cas.ledger_path('status.json'), cas.status())
        step('cycle summary', {k: record[k] for k in ('gates', 'failures', 'wall_seconds',
                                                      'storage_bytes')})
    if any('storage' in f for f in FAILURES):
        return 2
    return 1 if FAILURES else 0


def _readonly_hashes() -> dict:
    out = {}
    for name in ('model.npz', 'projection-L12.npz', 'forecast.npz', 'report.json'):
        p = cas.FROZEN / name
        if p.is_file():
            out[name] = cas.sha256_file(p)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('command', choices=['cycle', 'probe', 'freeze', 'aggregate', 'analyze',
                                        'verify', 'status', 'selftest'])
    ap.add_argument('--month', action='append', help='month YYYY-MM (aggregate/analyze)')
    ap.add_argument('--dry-run', action='store_true', help='record the intent, write no data')
    args = ap.parse_args(argv)
    cas.ensure_dirs()

    if args.command == 'selftest':
        import selftest
        return selftest.main()
    if args.command == 'status':
        step('status', cas.status())
        return 0
    if args.command == 'probe':
        do_probe(cas.POLL_COLLECTIONS)
        return 0
    if args.command == 'freeze':
        do_freeze(do_probe(cas.POLL_COLLECTIONS), args.dry_run)
        return 0
    if args.command == 'aggregate':
        do_aggregate(args.month)
        return 0
    if args.command == 'analyze':
        if not args.month:
            print('analyze needs --month YYYY-MM', file=sys.stderr)
            return 1
        for m in args.month:
            res = casmodel.build_analysis('gfs', m)
            step(f'analyze {m}', {k: res.get(k) for k in ('status', 'coefficients_built',
                                                          'coefficients_expected', 'why_blocked',
                                                          'caliber_changes')})
            if res.get('status') == 'ok':
                step('forecast', casmodel.issue_forecast(res))
        return 0
    if args.command == 'verify':
        step('verify', casmodel.verify_due())
        return 0
    return do_cycle(args.dry_run)


if __name__ == '__main__':
    sys.exit(main())
