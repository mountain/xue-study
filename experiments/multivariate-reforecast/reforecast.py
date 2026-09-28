"""Reforecast from a NEW initial month with the FROZEN model (no retraining, no overwrite).

Round: xue.derived.reforecast-winter-2026-27-from-latest-month (round 1).
Initial month: 2026-02 (latest month available in the R1-based inputs).
Targets: 2026-03 .. 2026-08 (leads 1..6 of the frozen direct map).

Order of operations is fixed before running:
  1 refuse to overwrite an existing result directory
  2 hash the frozen artifacts
  3 REPLAY the frozen forecast from the frozen initial state; require atol 1e-12
     (this proves the model was loaded correctly BEFORE any new number is believed)
  4 project the two new months (2026-01, 2026-02) with the frozen observation domains
  5 apply the frozen vectors/maps to the new initial state
  6 write grids, regional readouts, hashes, report
"""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

REFINE = Path('/home/ubuntu/xue-study/experiments/multivariate-refinement')
sys.path.insert(0, str(REFINE))
sys.path.insert(0, str(REFINE.parent / 'typed-spectrum'))

import fields
import project
import model as M
from train import forecast_grids
from project import load_field, geometry, interpolate_surface_pressure, masked_project, area_weights

FROZEN = Path('/home/ubuntu/xue-study/archive/multivariate-l12-v1')
EXT_INPUTS = Path('/home/ubuntu/climatetensor-inputs/ncep-multivariate-ext-202602')
OUT = Path('/home/ubuntu/xue-study/archive/multivariate-reforecast-202602-v1')
INIT_MONTH = '2026-02'
TARGET_MONTHS = ['2026-03', '2026-04', '2026-05', '2026-06', '2026-07', '2026-08']
FROZEN_FILES = ['model.npz', 'projection-L12.npz', 'forecast.npz', 'report.json']
PLATEAU = dict(lat=(28., 36.), lon=(80., 100.))
REGIONS = {'east_asia': (25., 40., 130., 170.),
           'north_america': (32.5, 47.5, 280., 310.),
           'middle_east': (20., 35., 35., 65.)}


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def block_indices(lat, lon, box):
    la0, la1, lo0, lo1 = box
    lonx = np.where(np.asarray(lon) < lo0, np.asarray(lon) + 360., np.asarray(lon))
    return (np.where((lat >= la0) & (lat <= la1))[0],
            np.where((lonx >= lo0) & (lonx <= lo1))[0])


def box_mean(field, w2, ilat, ilon):
    sel = field[np.ix_(ilat, ilon)]
    ww = w2[np.ix_(ilat, ilon)]
    return float(np.nansum(sel * ww) / np.nansum(np.isfinite(sel) * ww))


def main():
    if (OUT / 'report.json').exists():
        raise FileExistsError(f'completed reforecast already exists: {OUT}')
    OUT.mkdir(parents=True, exist_ok=True)
    log = []

    hashes = {name: sha256(FROZEN / name) for name in FROZEN_FILES}
    log.append({'step': 'frozen_hashes', **hashes})

    fields.INPUTS = EXT_INPUTS
    project.INPUTS = EXT_INPUTS
    project.geometry.cache_clear()   # only geometry() is lru_cached in project.py

    with np.load(FROZEN / 'model.npz', allow_pickle=False) as m:
        frozen = {k: m[k] for k in m.files}
    with np.load(FROZEN / 'projection-L12.npz', allow_pickle=False) as p:
        proj = {k: p[k] for k in p.files}
    with np.load(FROZEN / 'forecast.npz', allow_pickle=False) as f:
        frozen_forecast = {k: f[k] for k in f.files}
    channels = json.loads(str(proj['channels_json']))
    state = M.SeasonalState(frozen['climatology'], frozen['scale'])

    # ---- 3. frozen replay: frozen initial state -> frozen forecast, atol 1e-12
    frozen_dates = proj['dates']
    frozen_months = frozen_dates.astype('datetime64[M]').astype(int) % 12
    frozen_init = state.encode(proj['coefficients'][-1], frozen_months[-1])
    replay = state.decode((frozen_init @ frozen['vectors']) @ frozen['maps'],
                          frozen_forecast['months'].astype('datetime64[M]').astype(int) % 12)
    replay_max = float(np.max(np.abs(replay - frozen_forecast['coefficients'])))
    log.append({'step': 'frozen_replay', 'initial_month': str(frozen_dates[-1])[:7],
                'max_abs_diff_vs_frozen_forecast': replay_max, 'atol': 1e-12,
                'passed': replay_max <= 1e-12})
    if replay_max > 1e-12:
        raise SystemExit('frozen replay failed: model not loaded as frozen')

    # ---- 4. project the new months with the frozen domains
    new_rows, channel_report = {}, []
    for ch in channels:
        name = ch['name']
        values, lat, lon, dates = load_field(ch['fields'][0])   # channel names are not file codes
        dts = np.asarray(dates).astype('datetime64[M]')
        if not np.array_equal(dts[:len(frozen_dates)], np.asarray(frozen_dates).astype('datetime64[M]')):
            raise ValueError(f'{name}: stored history does not match frozen dates')
        if not (np.array_equal(proj[name + '_lat'], lat) and np.array_equal(proj[name + '_lon'], lon)):
            raise ValueError(f'{name}: grid differs from frozen projection')
        stack = [values.reshape(len(dates), -1)]
        for code in ch['fields'][1:]:
            v, la, lo, dt = load_field(code)
            if not (np.array_equal(lat, la) and np.array_equal(lon, lo)
                    and np.array_equal(np.asarray(dates), np.asarray(dt))):
                raise ValueError(f'{name}/{code}: misaligned channel')
            stack.append(v.reshape(len(dates), -1))
        y = np.stack(stack, axis=2)
        training = dates < '2015-01'
        fixed = np.isfinite(y[training]).all(axis=(0, 2))
        masks = np.broadcast_to(fixed, (len(dates), len(fixed))).copy()
        if ch['level'] is not None:
            pressure = interpolate_surface_pressure(lat, lon)
            fixed = fixed & (pressure[training].min(axis=0) >= ch['level'] * 100)
            masks = masks & fixed[None, :] & (pressure >= ch['level'] * 100)
        if not np.array_equal(fixed.reshape(len(lat), len(lon)), proj[name + '_domain']):
            raise ValueError(f'{name}: observation domain differs from frozen projection')
        if name.startswith('q'):
            y = np.log(np.maximum(y, 1e-7))
        basis, weights = geometry(tuple(lat), tuple(lon), fields.DEGREE)
        matrix = basis.vector if len(ch['fields']) == 2 else basis.scalar[:, None, :]
        # new months = exactly those beyond the frozen history (2026-01, 2026-02)
        sel = np.arange(len(frozen_dates), len(dts))
        if len(sel) < 1 or str(dts[sel[-1]])[:7] != INIT_MONTH:
            raise ValueError(f'{name}: new months {[str(dts[i])[:7] for i in sel]} do not end at {INIT_MONTH}')
        coeff, _, _, _, diag = masked_project(matrix, y[sel], weights, masks[sel])
        if coeff.shape[1] != ch['stop'] - ch['start']:
            raise ValueError(f'{name}: coefficient block size changed')
        new_rows[name] = coeff
        channel_report.append({'channel': name, 'new_months': [str(dates[i])[:7] for i in sel],
                               'block_size': int(coeff.shape[1]), **diag})
        log.append({'step': 'project_new_months', 'channel': name, **diag})

    # ---- 5. compose and apply the frozen direct map
    # concatenate along TIME inside each channel block, then across blocks
    blocks = [np.concatenate([proj['coefficients'][:, ch['start']:ch['stop']], new_rows[ch['name']]], axis=0)
              for ch in channels]
    c_ext = np.concatenate(blocks, axis=1)
    n_new = c_ext.shape[0] - len(frozen_dates)
    last_frozen = np.datetime64(str(np.asarray(frozen_dates)[-1])[:7], 'M')
    new_labels = [str(last_frozen + k)[:7] for k in range(1, n_new + 1)]
    stored_dtype = np.asarray(frozen_dates).dtype
    dates_ext = np.concatenate([np.asarray(frozen_dates), np.array(new_labels, dtype=stored_dtype)])
    assert len(dates_ext) == c_ext.shape[0], (len(dates_ext), c_ext.shape)
    assert new_labels[-1] == INIT_MONTH, new_labels
    months_ext = dates_ext.astype('datetime64[M]').astype(int) % 12
    x_ext = state.encode(c_ext, months_ext)
    x_init = x_ext[-1]
    forecast = (x_init @ frozen['vectors']) @ frozen['maps']
    target_index = np.array([np.datetime64(t, 'M').astype(int) % 12 for t in TARGET_MONTHS])
    coefficients = state.decode(forecast, target_index)

    # replay the new path itself (encode -> map -> decode must round-trip)
    again = state.decode((state.encode(c_ext[-1], months_ext[-1]) @ frozen['vectors']) @ frozen['maps'], target_index)
    self_max = float(np.max(np.abs(again - coefficients)))
    log.append({'step': 'self_replay', 'max_abs_diff': self_max, 'atol': 1e-12, 'passed': self_max <= 1e-12})

    grids = forecast_grids(proj, coefficients, channels)
    np.savez_compressed(OUT / 'forecast.npz', months=np.array(TARGET_MONTHS),
                        initial_month=np.array(INIT_MONTH), coefficients=coefficients, **grids)

    # ---- 6. regional readouts
    lat, lon = grids['lat'], grids['lon']
    w2 = area_weights(lat, lon).reshape(len(lat), len(lon))     # area_weights returns a flat vector
    t2m = grids['t2m']
    ilat, ilon = block_indices(lat, lon, (PLATEAU['lat'][0], PLATEAU['lat'][1],
                                          PLATEAU['lon'][0], PLATEAU['lon'][1]))
    wind = {}
    for key, box in REGIONS.items():
        rlat, rlon = block_indices(lat, lon, box)
        ww = w2[np.ix_(rlat, rlon)][None, :, :]
        u = grids['u500'][:, rlat][:, :, rlon]
        v = grids['v500'][:, rlat][:, :, rlon]
        ok = np.isfinite(u) & np.isfinite(v)
        den = np.nansum(ok * ww, axis=(1, 2))
        ubar = np.nansum(np.where(ok, u, 0.) * ww, axis=(1, 2)) / den
        vbar = np.nansum(np.where(ok, v, 0.) * ww, axis=(1, 2)) / den
        wind[key] = np.sqrt(ubar ** 2 + vbar ** 2).tolist()
    readouts = {'target_months': TARGET_MONTHS,
                'plateau_t2m_K': [box_mean(t2m[i], w2, ilat, ilon) for i in range(len(TARGET_MONTHS))],
                'region_500hPa_vector_mean_speed_ms': wind}

    report = {
        'question_id': 'xue.derived.reforecast-winter-2026-27-from-latest-month',
        'version': 'multivariate-reforecast-202602-v1',
        'initial_month': INIT_MONTH,
        'target_months': TARGET_MONTHS,
        'leads_months': [1, 2, 3, 4, 5, 6],
        'status': 'historical-origin experimental monthly forecast from a NEW initial month; not operational weather',
        'model': 'frozen multivariate L12 (ctmulti12); vectors/maps/climatology/scale reused unchanged; no retraining',
        'reachable_target_check': {
            'rule': 'direct map only, leads 1..6; a target month T needs an initial month M with 0 < T-M <= 6',
            'latest_available_initial_month': INIT_MONTH,
            'months_needed_for_2026_12': ['2026-06', '2026-11'],
            '2026_12_reachable': False,
            'why': 'R1-based inputs end 2026-02; 2026-12 would be lead 10 (> 6)'},
        'verification_available': False,
        'verification_note': 'no month later than 2026-02 exists in the R1 inputs, so leads 1..6 cannot be scored yet',
        'known_representation_error': 'low-order spectral truncation flattens the plateau cold background '
                                      '(audit 2026-09-24: L12 January plateau warm bias +10.43 K, spectral '
                                      'climatology truncation +9.589 K of it); plateau readouts carry this caveat',
        'data_authenticity_reservation': 'reserved by the questioner on 2026-09-24; not resolved by this round',
        'frozen_hashes_sha256': hashes,
        'channels': channel_report,
        'readouts': readouts,
        'outputs': {'forecast.npz': None},
    }
    (OUT / 'report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + '\n')
    (OUT / 'run.log').write_text('\n'.join(json.dumps(x, ensure_ascii=False, default=str) for x in log) + '\n')
    print(json.dumps({'out': str(OUT), 'frozen_replay_max_abs_diff': replay_max,
                      'self_replay_max_abs_diff': self_max,
                      'plateau_t2m_K': readouts['plateau_t2m_K'],
                      'region_speeds': {k: [round(x, 2) for x in v] for k, v in wind.items()}},
                     ensure_ascii=False, indent=1), flush=True)


if __name__ == '__main__':
    main()
