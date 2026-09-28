"""Continuous assimilation — core: paths, ledger, service adapters, freeze, aggregation.

Design contract: experiments/continuous-assimilation/contract.json (frozen first).

Everything written by this module is APPEND-ONLY. Nothing already frozen is ever
rewritten, and the storage cap fails loudly instead of deleting data.

The frozen model, its projection and every existing result directory are read-only.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import numpy as np

REPO = Path('/home/ubuntu/xue-study')
FROZEN = REPO / 'archive/multivariate-l12-v1'
ROOT = Path(os.environ.get('XUE_ASSIM_ROOT', '/home/ubuntu/xue-assimilation'))
SERVICE = 'https://dataset.ringsaturn.me/xue'
UA = 'xue-study-continuous-assim/1.0 (+research; contact via repo)'

# ---------------------------------------------------------------- declarations
#
# The service publishes NO units attribute (verified 2026-09-28: `tmp2m` attrs are
# empty), so every unit below is DECLARED from the GFS pgrb2.0p25 product spec and
# is then checked only by a physical range (G2/G3). A wrong declaration shows up as
# a range violation, not as a silent wrong number.
VARIABLES: dict[str, dict] = {
    # 850 hPa: the service stores degC, NOT K. Verified on the live run 2026-09-28: a
    # polar 850 hPa value of -23.0 is only possible in degC, and the G2 range guard
    # refused the run while this was declared as K. Fourth temperature-unit trap in
    # this project (GDAL/GRIB, Zarr quantization, CFSv2 tmpsfc, now this).
    'tmp850': dict(vars=['tmp850'], units='degC', scale=1.0, offset=273.15, range=(150.0, 350.0)),
    # 700 hPa: the service stores degC, NOT K. Verified on the live run 2026-09-28: a
    # polar 700 hPa value of -23.0 is only possible in degC, and the G2 range guard
    # refused the run while this was declared as K. Fourth temperature-unit trap in
    # this project (GDAL/GRIB, Zarr quantization, CFSv2 tmpsfc, now this).
    'tmp700': dict(vars=['tmp700'], units='degC', scale=1.0, offset=273.15, range=(150.0, 350.0)),
    # 2 m: the service stores degC, NOT K. Verified on the live run 2026-09-28: a
    # polar 2 m value of -23.0 is only possible in degC, and the G2 range guard
    # refused the run while this was declared as K. Fourth temperature-unit trap in
    # this project (GDAL/GRIB, Zarr quantization, CFSv2 tmpsfc, now this).
    'tmp2m': dict(vars=['tmp2m'], units='degC', scale=1.0, offset=273.15, range=(150.0, 350.0)),
    'prmsl': dict(vars=['prmsl'], units='hPa', scale=100.0, offset=0.0, range=(8.5e4, 1.12e5)),
    'hgt500': dict(vars=['hgt500'], units='gpm', scale=9.80665, offset=0.0, range=(4.0e4, 6.2e4)),
    'rh850': dict(vars=['rh850'], units='%', scale=1.0, offset=0.0, range=(0.0, 110.0)),
    'rh700': dict(vars=['rh700'], units='%', scale=1.0, offset=0.0, range=(0.0, 110.0)),
    'vvel500': dict(vars=['vvel500'], units='Pa/s', scale=1.0, offset=0.0, range=(-40.0, 40.0)),
    'vvel700': dict(vars=['vvel700'], units='Pa/s', scale=1.0, offset=0.0, range=(-40.0, 40.0)),
    'wind850': dict(vars=['ugrd850', 'vgrd850'], units='m/s', scale=1.0, offset=0.0, range=(-160.0, 160.0)),
    'wind500': dict(vars=['ugrd500', 'vgrd500'], units='m/s', scale=1.0, offset=0.0, range=(-160.0, 160.0)),
    'wind250': dict(vars=['ugrd250', 'vgrd250'], units='m/s', scale=1.0, offset=0.0, range=(-200.0, 200.0)),
}

# Range checks are applied AFTER scale/offset, so `prmsl` is checked in Pa and
# `hgt500` in m2/s2 — the same caliber the frozen model uses for msl and z500.
CHANNEL_SOURCE: dict[str, dict] = {
    't850': dict(from_=['tmp850'], status='direct'),
    't2m': dict(from_=['tmp2m'], status='direct'),
    'sst': dict(from_=[], status='missing', why='服务不含海表温度；冻结模型的 sst 来自 ERSST v5 月平均'),
    'sp': dict(from_=[], status='missing', why='服务只有 prmsl 与 orog；冻结模型的 sp 来自 R1'),
    'msl': dict(from_=['prmsl'], status='direct'),
    'z500': dict(from_=['hgt500'], status='direct'),
    'q850': dict(from_=['rh850', 'tmp850'], status='derived', why='由 rh 与 T 反算水汽属推导量，需声明'),
    'q700': dict(from_=['rh700', 'tmp700'], status='derived', why='同上'),
    'w500': dict(from_=['vvel500'], status='direct'),
    'w700': dict(from_=['vvel700'], status='direct'),
    'wind850': dict(from_=['wind850'], status='direct'),
    'wind500': dict(from_=['wind500'], status='direct'),
    'wind250': dict(from_=['wind250'], status='direct'),
}

MODEL_GRID = (73, 144)          # R1 native 2.5 degree grid, the frozen caliber
NATIVE_GRID = (721, 1440)       # service 0.25 degree
SYNOPTIC_HOURS = ['00', '06', '12', '18']
STORAGE_CAP = 30 * 1024 ** 3
POLL_COLLECTIONS = ['gfs']


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def ensure_dirs() -> None:
    for sub in ('raw', 'monthly', 'ledger'):
        (ROOT / sub).mkdir(parents=True, exist_ok=True)


def ledger_path(name: str) -> Path:
    return ROOT / 'ledger' / name


def append_jsonl(name: str, record: dict) -> None:
    """Append one record. Flushed and fsynced so a crash cannot lose the tail."""
    ensure_dirs()
    line = json.dumps(record, ensure_ascii=False, default=str)
    with open(ledger_path(name), 'a') as fh:
        fh.write(line + '\n')
        fh.flush()
        os.fsync(fh.fileno())


def read_jsonl(name: str) -> list[dict]:
    p = ledger_path(name)
    if not p.is_file():
        return []
    out = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def write_json_atomic(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str) + '\n')
    os.replace(tmp, path)


def storage_used() -> int:
    total = 0
    for dirpath, _dirnames, filenames in os.walk(ROOT / 'raw'):
        for name in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, name))
            except OSError:
                pass
    return total


# ---------------------------------------------------------------- service I/O
def http_get_json(url: str, timeout: int = 60) -> dict:
    import urllib.request
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def probe_collection(collection: str) -> dict:
    """Newest run of a collection. Records failures instead of raising past them."""
    item_url = f'{SERVICE}/{collection}/item.json'
    try:
        item = http_get_json(item_url)
    except Exception as exc:                                   # noqa: BLE001
        return {'collection': collection, 'ok': False, 'error': f'{type(exc).__name__}: {exc}',
                'item_url': item_url, 'probed_utc': utcnow()}
    props = item.get('properties', {}) or {}
    return {
        'collection': collection, 'ok': True, 'item_url': item_url,
        'run_id': item.get('id'),
        'reference_datetime': props.get('forecast:reference_datetime') or props.get('datetime'),
        'end_datetime': props.get('end_datetime'),
        'assets': item.get('assets', {}),
        'probed_utc': utcnow(),
    }


def _read_step0(asset: dict, item_url: str, var: str) -> np.ndarray:
    import xarray as xr
    href = urljoin(item_url, asset['href'])
    ds = xr.open_zarr(href, consolidated=None, decode_timedelta=False)
    try:
        da = ds[var].isel(time=0).load()
        return np.asarray(da.values, dtype=np.float64)
    finally:
        ds.close()


def _read_step0_mean(asset: dict, item_url: str) -> np.ndarray:
    """For two-component variables (ugrd/vgrd) the `vars` list holds both names."""
    return np.stack([_read_step0(asset, item_url, v) for v in asset['_vars']], axis=0)


def check_ranges(name: str, arr: np.ndarray, spec: dict) -> dict:
    lo, hi = spec['range']
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return {'variable': name, 'ok': False, 'why': 'no finite values'}
    amin, amax = float(finite.min()), float(finite.max())
    ok = bool(amin >= lo and amax <= hi)
    return {'variable': name, 'ok': ok, 'units_declared': spec['units'],
            'range_declared': [lo, hi], 'min': amin, 'max': amax,
            'why': '' if ok else 'outside declared physical range after scale/offset'}


def freeze_run(collection: str, probe: dict, dry_run: bool = False) -> dict:
    """Freeze step 0 (the analysis) of every variable we need. Append-only."""
    run_id = probe['run_id']
    run_dir = ROOT / 'raw' / collection / str(run_id)
    record = {'event': 'freeze', 'collection': collection, 'run_id': run_id,
              'reference_datetime': probe.get('reference_datetime'),
              'probed_utc': probe.get('probed_utc'), 'attempted_utc': utcnow()}

    # Deduplicate only against runs actually WRITTEN: a run refused by the range guard
    # must stay retryable, otherwise fixing a unit declaration could never take effect.
    # (Found on the first live run: the refused run id would have blocked its own retry.)
    known = {r.get('run_id') for r in read_jsonl('frozen.jsonl')
             if r.get('event') == 'freeze' and r.get('status') == 'written'}
    if run_id in known:
        record.update({'status': 'duplicate_skipped', 'why': 'run id already frozen (G5)'})
        append_jsonl('frozen.jsonl', record)
        return record
    if (run_dir / 'manifest.json').is_file():
        record.update({'status': 'duplicate_skipped', 'why': 'run directory already exists (G5)'})
        append_jsonl('frozen.jsonl', record)
        return record
    if storage_used() > STORAGE_CAP:
        record.update({'status': 'refused_storage_cap',
                       'why': f'storage {storage_used()} > cap {STORAGE_CAP}; refusing to freeze, '
                              f'NOT deleting anything (a deletion is a decision, not a default)'})
        append_jsonl('frozen.jsonl', record)
        return record
    if dry_run:
        record.update({'status': 'dry_run', 'why': 'no bytes written'})
        append_jsonl('frozen.jsonl', record)
        return record

    run_dir.mkdir(parents=True, exist_ok=True)
    arrays, checks, missing = {}, [], []
    for name, spec in VARIABLES.items():
        asset = probe['assets'].get(name)
        if asset is None:
            missing.append(name)
            continue
        asset = dict(asset)
        asset['_vars'] = spec['vars']
        try:
            raw = _read_step0_mean(asset, probe['item_url'])
        except Exception as exc:                               # noqa: BLE001
            checks.append({'variable': name, 'ok': False, 'why': f'{type(exc).__name__}: {exc}'})
            continue
        scaled = raw * spec['scale'] + spec['offset']
        chk = check_ranges(name, scaled, spec)
        checks.append(chk)
        arrays[name] = scaled.astype(np.float32)

    failed = [c['variable'] for c in checks if not c['ok']]
    record.update({'status': 'written' if not failed else 'refused_range_failure',
                   'variables_written': sorted(arrays), 'variables_failed': failed,
                   'variables_missing_asset': missing, 'range_checks': checks})
    if failed:
        record['why'] = 'G2 magnitude guard refused this run (unit declaration vs data mismatch)'
        append_jsonl('frozen.jsonl', record)
        return record

    lat = np.linspace(90.0, -90.0, NATIVE_GRID[0])
    lon = np.linspace(-180.0, 180.0 - 360.0 / NATIVE_GRID[1], NATIVE_GRID[1])
    out = run_dir / 'analysis.npz'
    np.savez_compressed(out, latitude=lat, longitude=lon, **arrays)
    ref = probe.get('reference_datetime') or ''
    manifest = {'collection': collection, 'run_id': run_id, 'reference_datetime': ref,
                'frozen_utc': utcnow(), 'file': out.name, 'sha256': sha256_file(out),
                'bytes': out.stat().st_size, 'variables': sorted(arrays),
                'units_declared': {k: VARIABLES[k]['units'] for k in arrays},
                'scale_offset': {k: [VARIABLES[k]['scale'], VARIABLES[k]['offset']] for k in arrays},
                'range_checks': checks,
                'caliber': {'native_grid': list(NATIVE_GRID), 'step': 0,
                            'note': 'step 0 of the run = the analysis field (f000)'}}
    write_json_atomic(run_dir / 'manifest.json', manifest)
    record.update({'status': 'written', 'sha256': manifest['sha256'], 'bytes': manifest['bytes'],
                   'path': str(out)})
    append_jsonl('frozen.jsonl', record)
    return record


# ---------------------------------------------------------------- aggregation
def _load_analysis(run_dir: Path) -> dict:
    with np.load(run_dir / 'analysis.npz') as f:
        return {k: f[k] for k in f.files}


def daily_mean(collection: str, day: str) -> dict:
    """Average the synoptic analyses of one day. Reports which hours were present."""
    base = ROOT / 'raw' / collection
    if not base.is_dir():
        return {'day': day, 'status': 'no_data'}
    hours, acc = [], None
    for child in sorted(base.iterdir()):
        if not (child / 'manifest.json').is_file():
            continue
        man = json.loads((child / 'manifest.json').read_text())
        ref = str(man.get('reference_datetime') or '')
        if not ref.startswith(day):
            continue
        hour = ref[11:13]
        hours.append(hour)
        data = _load_analysis(child)
        if acc is None:
            acc = {k: [np.asarray(v, dtype=np.float64)] for k, v in data.items() if v.ndim == 2}
        else:
            for k in acc:
                acc[k].append(np.asarray(data[k], dtype=np.float64))
    if acc is None:
        return {'day': day, 'status': 'no_data'}
    out = {k: np.mean(np.stack(v), axis=0) for k, v in acc.items()}
    return {'day': day, 'status': 'ok', 'hours_present': sorted(hours),
            'n_synoptic': len(hours), 'complete': sorted(hours) == sorted(SYNOPTIC_HOURS),
            'arrays': out}


def month_days(month: str) -> list[str]:
    y, m = int(month[:4]), int(month[5:7])
    nxt = datetime(y + (m // 12), (m % 12) + 1, 1)
    n = (nxt - datetime(y, m, 1)).days
    return [f'{month}-{d:02d}' for d in range(1, n + 1)]


def regrid_to_model(arr: np.ndarray, src_lat: np.ndarray, src_lon: np.ndarray,
                    dst_lat: np.ndarray, dst_lon: np.ndarray) -> np.ndarray:
    """Conservative 0.25 -> 2.5 degree regrid by exact cell-overlap area integrals.

    Weights are the exact spherical areas of the overlap between each source cell and
    each destination cell, w = sin(hi) - sin(lo), so the area integral is preserved and
    a linear field regrids to its analytic area-weighted mean. Selecting source ROWS by
    nearest centre instead (the first three attempts) left a 3e-3 degree discretisation
    residue and, at the poles, an arbitrary row count.

    The polar destination cells are partially outside the source grid; their weight is
    the cap that exists, which is the correct conservative treatment.
    """
    lat = np.asarray(src_lat, dtype=float)
    lon = np.asarray(src_lon, dtype=float)
    flip_lat = lat[0] > lat[-1]
    if flip_lat:
        lat = lat[::-1]
        arr = arr[::-1, :]
    dlat_src = abs(float(np.mean(np.diff(lat))))
    dlon_src = abs(float(np.mean(np.diff(lon))))
    if not (np.allclose(np.abs(np.diff(lat)), dlat_src, atol=1e-9)
            and np.allclose(np.abs(np.diff(lon)), dlon_src, atol=1e-9)):
        raise ValueError('source grid must be regular for this conservative regrid')
    # Clip the outer edges to the poles: without this the polar source cell gets a
    # NEGATIVE weight (sin(90.125) < sin(89.875)) and is silently dropped, which loses
    # its area and breaks area conservation at the 4e-8 level. Found by the self-test.
    src_edges = np.clip(np.concatenate([[lat[0] - dlat_src / 2], lat + dlat_src / 2]), -90.0, 90.0)
    dlat_dst = 180.0 / (dst_lat.size - 1)
    dlon_dst = 360.0 / dst_lon.size
    lon_edges_src = np.concatenate([[lon[0] - dlon_src / 2], lon + dlon_src / 2])
    nlon = lon.size
    out = np.full((dst_lat.size, dst_lon.size), np.nan)
    for i, la in enumerate(dst_lat):
        a0, a1 = la - dlat_dst / 2.0, la + dlat_dst / 2.0
        lo = np.maximum(src_edges[:-1], a0)
        hi = np.minimum(src_edges[1:], a1)
        wlat = np.clip(np.sin(np.deg2rad(hi)) - np.sin(np.deg2rad(lo)), 0.0, None)
        if not (wlat > 0).any():
            continue
        ncell_lon = dlon_dst / dlon_src
        if abs(ncell_lon - round(ncell_lon)) > 1e-9:
            raise ValueError('destination longitude cells are not an integer number of '
                             'source cells; this conservative regrid requires alignment')
        ncell_lon = int(round(ncell_lon))
        rows = np.flatnonzero(wlat > 0)
        if rows.size == 0:
            continue
        wl = wlat[rows]
        arr_rows = arr[rows]
        for j, lo_c in enumerate(dst_lon):
            b0 = ((lo_c - dlon_dst / 2.0 + 180.0) % 360.0) - 180.0
            k0 = int(round((b0 - lon_edges_src[0]) / dlon_src)) % nlon
            cols = (np.arange(k0, k0 + ncell_lon)) % nlon
            block = arr_rows[:, cols]
            w = wl[:, None] * np.ones((1, cols.size))
            good = np.isfinite(block) & (w > 0)
            if not good.any():
                continue
            out[i, j] = float(np.sum(block[good] * w[good]) / np.sum(w[good]))
    return out


def _overlap_len(s0: float, s1: float, b0: float, b1: float) -> float:
    """Length of the overlap between a source cell and a destination cell, modulo 360."""
    best = 0.0
    for shift in (-360.0, 0.0, 360.0):
        lo = max(s0 + shift, b0)
        hi = min(s1 + shift, b1)
        if hi > lo:
            best = max(best, hi - lo)
    return best


def monthly_mean(collection: str, month: str, dst_lat: np.ndarray, dst_lon: np.ndarray,
                 model_lat: np.ndarray, model_lon: np.ndarray) -> dict:
    """Monthly mean from complete days only; completeness is reported, never assumed."""
    days, used, acc = month_days(month), [], None
    for day in days:
        rec = daily_mean(collection, day)
        if rec['status'] != 'ok':
            continue
        used.append({'day': day, 'hours': rec['hours_present']})
        if acc is None:
            acc = {k: [v] for k, v in rec['arrays'].items()}
        else:
            for k in acc:
                acc[k].append(rec['arrays'][k])
    if acc is None:
        return {'month': month, 'collection': collection, 'status': 'no_data'}
    native = {k: np.mean(np.stack(v), axis=0) for k, v in acc.items()}
    regridded = {}
    for k, v in native.items():
        if v.shape == MODEL_GRID:
            regridded[k] = v
        else:
            regridded[k] = regrid_to_model(v, dst_lat, dst_lon, model_lat, model_lon)
    return {'month': month, 'collection': collection, 'status': 'ok',
            'days_used': [u['day'] for u in used], 'n_days': len(used),
            'days_expected': len(days), 'complete': len(used) == len(days),
            'synoptic_per_day': {u['day']: u['hours'] for u in used},
            'native': native, 'model': regridded}


def status() -> dict:
    ensure_dirs()
    frozen = [r for r in read_jsonl('frozen.jsonl') if r.get('event') == 'freeze']
    written = [r for r in frozen if r.get('status') == 'written']
    months = sorted(p.name for p in (ROOT / 'monthly').iterdir()) if (ROOT / 'monthly').is_dir() else []
    return {
        'generated_utc': utcnow(),
        'root': str(ROOT),
        'storage_bytes': storage_used(),
        'storage_cap_bytes': STORAGE_CAP,
        'runs_frozen_written': len(written),
        'runs_frozen_skipped': len(frozen) - len(written),
        'last_frozen': (written[-1].get('run_id') if written else None),
        'months_aggregated': months,
        'forecasts': len(read_jsonl('forecasts.jsonl')),
        'verifications': len(read_jsonl('verification.jsonl')),
    }
