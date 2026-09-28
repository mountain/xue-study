"""Extend the projection-ready channel inputs to 2026-01/2026-02, with a zero-tolerance backfill test.

Recipe is taken verbatim from the existing provenance log
(~/climatetensor-inputs/ncep-multivariate/fetch.log): url -> local NetCDF,
source variable, unit conversion (scale, offset), pressure level.
Before accepting any extension we RE-DERIVE 2025-12 from the raw NetCDF and
require bitwise float32 equality with the stored npz month.

Nothing is overwritten: the extended inputs go to a new directory.
"""
import json
import sys
from pathlib import Path

import numpy as np
import xarray as xr

SRC = Path('/home/ubuntu/climatetensor-inputs/ncep-multivariate')
DST = Path('/home/ubuntu/climatetensor-inputs/ncep-multivariate-ext-202602')
NEW_MONTHS = ('2026-01', '2026-02')
BACKFILL_MONTH = '2025-12'


def local_nc(url: str) -> Path:
    tail = url.split('/Datasets/', 1)[1]
    return SRC / tail.replace('/', '__')


def take(ds, source_key, level, months):
    """Return (months_present, values[time,lat,lon]) in native grid order."""
    var = ds[source_key]
    if level is not None:
        var = var.sel(level=float(level))
    times = np.asarray(ds['time'].values).astype('datetime64[M]')
    want = np.array([np.datetime64(m, 'M') for m in months])
    pos = np.searchsorted(times, want)
    for m, p in zip(months, pos):
        if p >= len(times) or times[p] != np.datetime64(m, 'M'):
            raise ValueError(f'{source_key}: month {m} absent from source')
    return np.asarray(var.values)[pos]


def main():
    DST.mkdir(parents=True, exist_ok=True)
    records = [json.loads(line) for line in (SRC / 'fetch.log').read_text().splitlines() if line.strip()]
    out_records = []
    for rec in records:
        code = rec['code']
        scale = float(rec['conversion']['scale'])
        offset = float(rec['conversion']['offset'])
        level = rec['level_hpa']
        key = rec['source_key']
        nc = local_nc(rec['url'])

        with np.load(SRC / f'{code}.npz') as old:
            values, lat, lon, time = old['values'], old['lat'], old['lon'], old['time']
        months = np.asarray(time).astype('datetime64[M]')
        if str(months[-1])[:7] != BACKFILL_MONTH:
            raise ValueError(f'{code}: expected stored series to end at {BACKFILL_MONTH}, got {months[-1]}')

        with xr.open_dataset(nc) as ds:
            # backfill first: re-derive the last stored month from the raw file
            raw = take(ds, key, level, (BACKFILL_MONTH,))          # (1, lat, lon)
            derived = (raw[0].astype('float64') * scale + offset).astype('float32')   # (lat, lon)
            stored = values[-1]
            if derived.shape != stored.shape:
                raise SystemExit(f'{code}: backfill shape {derived.shape} != stored {stored.shape}')
            # NaN-aware: a NaN payload is a legitimate stored value at some grid cells,
            # and np.array_equal() returns False whenever any NaN is present.
            nan_mismatch = int(np.count_nonzero(np.isnan(derived) != np.isnan(stored)))
            finite = ~np.isnan(derived)
            exact = bool(nan_mismatch == 0 and np.array_equal(derived[finite], stored[finite]))
            maxdiff = float(np.max(np.abs(derived[finite].astype('float64') - stored[finite].astype('float64')))) \
                if finite.any() else 0.0
            print(json.dumps({'code': code, 'backfill_exact': exact, 'backfill_max_abs_diff': maxdiff,
                              'nan_mismatch': nan_mismatch,
                              'nan_cells': int(np.count_nonzero(~finite))},
                             ensure_ascii=False), flush=True)
            if not exact:
                raise SystemExit(f'BACKFILL FAILED for {code}: extension not accepted')

            raw_new = take(ds, key, level, NEW_MONTHS)
            new_values = (raw_new.astype('float64') * scale + offset).astype('float32')

        if new_values.shape[1:] != values.shape[1:]:
            raise ValueError(f'{code}: grid mismatch {new_values.shape} vs {values.shape}')
        out_values = np.concatenate([values, new_values], axis=0)
        stored_time = np.asarray(time)                     # stored layout is an array of 'YYYY-MM' strings
        out_time = np.concatenate([stored_time, np.array(NEW_MONTHS, dtype=stored_time.dtype)])

        np.savez_compressed(DST / f'{code}.npz', values=out_values, lat=lat, lon=lon, time=out_time)
        out_records.append({**rec, 'months': [str(months[0])[:7], NEW_MONTHS[-1]],
                            'shape': list(out_values.shape),
                            'extension_backfill_exact': True,
                            'extended_utc': np.datetime64('now', 's').astype(str)})
        meta = json.loads((SRC / f'{code}.json').read_text()) if (SRC / f'{code}.json').exists() else {}
        (DST / f'{code}.json').write_text(json.dumps({**meta, 'extended_months': list(NEW_MONTHS),
                                                      'backfill_exact': True}, ensure_ascii=False, indent=1))

    (DST / 'fetch-extended.log').write_text(
        '\n'.join(json.dumps(r, ensure_ascii=False) for r in out_records) + '\n')
    print(json.dumps({'extended_codes': len(out_records), 'dest': str(DST)}, ensure_ascii=False))


if __name__ == '__main__':
    sys.exit(main())
