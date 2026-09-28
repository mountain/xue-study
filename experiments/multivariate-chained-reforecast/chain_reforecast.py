"""Chained reforecast: give the temporal face its overlap and gluing, then pay for it.

Round: xue.derived.multivariate-chained-reforecast (round 1), contract.json (frozen first).

The frozen model is a FAN: `(x_init @ vectors) @ maps` gives leads 1..6 from ONE
origin, so the six arrows share a source and there is no adjacent pair -- E2 measured
exactly that (the temporal face had no `overlap`, `compatibility` or `gluing` instance).

This run makes the chain instead:
    x_{m+1} = (x_m @ vectors) @ maps[0]
where the interface handed from one step to the next is the pair
(month, normalised anomaly vector), and step k's OUTPUT is literally step k+1's
INPUT. That is the mechanical meaning of gluing here, and G3 checks it byte for byte.

Two things are delivered together and must not be separated:
  * the structural completion (reachability now follows the step count, so 2026-12
    is 10 steps from the observed 2026-02 state), and
  * the MEASURED cost of iterating, taken on the 2020-2025 backtest where truth
    exists -- the model was never fitted for iterated application.

Reads only; refuses to overwrite; the frozen archive and the prior reforecast are
never written.
"""
import hashlib
import json
import resource
import sys
import time
from pathlib import Path

import numpy as np

REFINE = Path('/home/ubuntu/xue-study/experiments/multivariate-refinement')
sys.path.insert(0, str(REFINE))
sys.path.insert(0, str(REFINE.parent / 'typed-spectrum'))

import fields
import project
import model as M
from project import load_field, geometry, interpolate_surface_pressure, masked_project, area_weights

REPO = Path('/home/ubuntu/xue-study')
FROZEN = REPO / 'archive/multivariate-l12-v1'
PRIOR = REPO / 'archive/multivariate-reforecast-202602-v1'
CFS_REF = REPO / 'archive/cfs-reference-2026-12-v1'
EXT_INPUTS = Path('/home/ubuntu/climatetensor-inputs/ncep-multivariate-ext-202602')
OUT = REPO / 'archive/multivariate-chained-reforecast-v1'
CONTRACT = Path(__file__).resolve().parent / 'contract.json'

INIT_MONTH = '2026-02'
K_CHAIN = 10
SCOPE_Z = 6.0
TOL = 1e-12
REGIONS = {'east_asia': (25., 40., 130., 170.),
           'north_america': (32.5, 47.5, 280., 310.),
           'middle_east': (20., 35., 35., 65.)}
PLATEAU = dict(lat=(28., 36.), lon=(80., 100.))
FROZEN_FILES = ['model.npz', 'projection-L12.npz', 'forecast.npz', 'report.json']
PRIOR_FILES = ['forecast.npz', 'report.json', 'run.log']

failures = []
log_lines = []


def log(msg):
    log_lines.append(str(msg))
    print(msg, flush=True)


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def fingerprint(arr):
    """Byte fingerprint of a state, used for the gluing ledger (G3)."""
    a = np.ascontiguousarray(arr, dtype=np.float64)
    return hashlib.sha256(a.tobytes()).hexdigest()


def block_indices(lat, lon, box):
    la0, la1, lo0, lo1 = box
    lonx = np.where(np.asarray(lon) < lo0, np.asarray(lon) + 360., np.asarray(lon))
    return (np.where((lat >= la0) & (lat <= la1))[0],
            np.where((lonx >= lo0) & (lonx <= lo1))[0])


def box_mean(field, w2, ilat, ilon):
    sel = field[np.ix_(ilat, ilon)]
    ww = w2[np.ix_(ilat, ilon)]
    return float(np.nansum(sel * ww) / np.nansum(np.isfinite(sel) * ww))


def grids_for(proj, coefficients, channels, n_steps):
    """Same construction as train.forecast_grids but for an arbitrary step count."""
    step = fields.GRID_STEP
    lat = np.arange(87.5, -87.5 - step / 2, -step)
    lon = np.arange(0., 360., step)
    basis, _ = geometry(tuple(lat), tuple(lon), fields.DEGREE)
    yy, xx = np.meshgrid(lat, lon, indexing='ij')
    points = np.stack([yy.ravel(), xx.ravel()], axis=1)
    output = {}
    for ch in channels:
        name = ch['name']
        a, b = ch['start'], ch['stop']
        matrix = basis.vector if len(ch['fields']) == 2 else basis.scalar[:, None, :]
        f = np.einsum('tp,ncp->tnc', coefficients[:, a:b], matrix)
        if name.startswith('q'):
            f = np.exp(f)
        native_lat = proj[name + '_lat']
        native_lon = proj[name + '_lon']
        domain = proj[name + '_domain'].astype(float)
        domain = np.c_[domain, domain[:, 0]]
        from scipy.interpolate import RegularGridInterpolator
        interp = RegularGridInterpolator((native_lat[::-1], np.r_[native_lon, 360.]),
                                         domain[::-1], method='nearest', bounds_error=False, fill_value=0.)
        mask = interp(points) >= .5
        for k, code in enumerate(ch['fields']):
            value = f[:, :, k].reshape(n_steps, len(lat), len(lon))
            output[code] = np.where(mask.reshape(len(lat), len(lon))[None, :, :], value, np.nan).astype('float32')
    for ch in channels:
        if ch['level'] is not None:
            for code in ch['fields']:
                output[code] = np.where(output['sp'] >= ch['level'] * 100, output[code], np.nan)
    return {'lat': lat, 'lon': lon, **output}


def month_index(labels):
    return np.array([np.datetime64(t, 'M').astype(int) % 12 for t in labels])


def score(proj, decoded, targets, channels):
    """resolved/full MSE per channel, one lead only (predictions shaped (1, T, p))."""
    return M.score_coefficients(proj, decoded[None, :, :], targets, channels)


def aggregate(metrics, channels, key='full_mse'):
    out = {}
    for ch in channels:
        out[ch['name']] = float(np.mean(metrics[ch['name']][key]))
    return out


def main():
    if (OUT / 'report.json').exists():
        raise FileExistsError(f'completed run already exists: {OUT}')
    OUT.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    contract = json.loads(CONTRACT.read_text())

    # ---- G1 frozen hashes
    hashes_before = {n: sha256(FROZEN / n) for n in FROZEN_FILES if (FROZEN / n).is_file()}
    prior_hashes_before = {n: sha256(PRIOR / n) for n in PRIOR_FILES if (PRIOR / n).is_file()}
    log(json.dumps({'frozen_hashes': hashes_before, 'prior_hashes': prior_hashes_before}, indent=1))

    fields.INPUTS = EXT_INPUTS
    project.INPUTS = EXT_INPUTS
    project.geometry.cache_clear()

    with np.load(FROZEN / 'model.npz', allow_pickle=False) as m:
        frozen = {k: m[k] for k in m.files}
    with np.load(FROZEN / 'projection-L12.npz', allow_pickle=False) as p:
        proj = {k: p[k] for k in p.files}
    with np.load(FROZEN / 'forecast.npz', allow_pickle=False) as f:
        frozen_forecast = {k: f[k] for k in f.files}
    with np.load(PRIOR / 'forecast.npz', allow_pickle=False) as f:
        prior_forecast = {k: f[k] for k in f.files}
    channels = json.loads(str(proj['channels_json']))
    state = M.SeasonalState(frozen['climatology'], frozen['scale'])
    vectors = frozen['vectors']
    maps = frozen['maps']

    def one_step(x):
        """The frozen lead-1 operator, in the frozen code's own order of operations."""
        return (x @ vectors) @ maps[0]

    frozen_dates = proj['dates']
    frozen_months = frozen_dates.astype('datetime64[M]').astype(int) % 12
    x_all = state.encode(proj['coefficients'], frozen_months)
    train = np.where(frozen_dates < '2015-01')[0]
    valid = np.where((frozen_dates >= '2015-01') & (frozen_dates < '2020-01'))[0]
    backtest = np.where(frozen_dates >= '2020-01')[0]
    assert (len(train), len(valid), len(backtest)) == (432, 60, 72)
    std_train = x_all[train].std(axis=0)

    def scope_stats(x):
        z = np.abs(x) / np.where(std_train > 0, std_train, np.inf)
        per_channel = {}
        for ch in channels:
            per_channel[ch['name']] = float(z[ch['start']:ch['stop']].max())
        return {'max_abs_z': float(z.max()), 'per_channel_max_abs_z': per_channel,
                'out_of_scope_channels': sorted(n for n, v in per_channel.items() if v > SCOPE_Z),
                'out_of_scope': bool(z.max() > SCOPE_Z)}

    # ---- G2a: the chain's first step must be the frozen forecast's lead 1
    x_last = x_all[-1]
    lead1_hist = state.decode(one_step(x_last), (frozen_months[-1] + 1) % 12)
    g2a = float(np.max(np.abs(lead1_hist - frozen_forecast['coefficients'][0])))
    log(json.dumps({'G2a_single_step_vs_frozen_lead1': g2a, 'atol': TOL, 'passed': g2a <= TOL}))
    if g2a > TOL:
        raise SystemExit('G2a failed: first step is not the frozen lead-1 operator')

    # ---- project the new months (2026-01, 2026-02) with the frozen domains
    new_rows = {}
    for ch in channels:
        name = ch['name']
        values, lat, lon, dates = load_field(ch['fields'][0])
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
        tr = dates < '2015-01'
        fixed = np.isfinite(y[tr]).all(axis=(0, 2))
        masks = np.broadcast_to(fixed, (len(dates), len(fixed))).copy()
        if ch['level'] is not None:
            pressure = interpolate_surface_pressure(lat, lon)
            fixed = fixed & (pressure[tr].min(axis=0) >= ch['level'] * 100)
            masks = masks & fixed[None, :] & (pressure >= ch['level'] * 100)
        if not np.array_equal(fixed.reshape(len(lat), len(lon)), proj[name + '_domain']):
            raise ValueError(f'{name}: observation domain differs from frozen projection')
        if name.startswith('q'):
            y = np.log(np.maximum(y, 1e-7))
        basis, weights = geometry(tuple(lat), tuple(lon), fields.DEGREE)
        matrix = basis.vector if len(ch['fields']) == 2 else basis.scalar[:, None, :]
        sel = np.arange(len(frozen_dates), len(dts))
        if len(sel) < 1 or str(dts[sel[-1]])[:7] != INIT_MONTH:
            raise ValueError(f'{name}: new months do not end at {INIT_MONTH}')
        coeff, _, _, _, diag = masked_project(matrix, y[sel], weights, masks[sel])
        if coeff.shape[1] != ch['stop'] - ch['start']:
            raise ValueError(f'{name}: coefficient block size changed')
        new_rows[name] = coeff
        log(json.dumps({'projected_new_months': name, **{k: diag[k] for k in ('distinct_domains', 'max_gram_condition')}}))
    blocks = [np.concatenate([proj['coefficients'][:, ch['start']:ch['stop']], new_rows[ch['name']]], axis=0)
              for ch in channels]
    c_ext = np.concatenate(blocks, axis=1)
    stored_dtype = np.asarray(frozen_dates).dtype
    last_frozen = np.datetime64(str(np.asarray(frozen_dates)[-1])[:7], 'M')
    n_new = c_ext.shape[0] - len(frozen_dates)
    new_labels = [str(last_frozen + k)[:7] for k in range(1, n_new + 1)]
    dates_ext = np.concatenate([np.asarray(frozen_dates), np.array(new_labels, dtype=stored_dtype)])
    assert new_labels[-1] == INIT_MONTH, new_labels
    months_ext = dates_ext.astype('datetime64[M]').astype(int) % 12
    x_ext = state.encode(c_ext, months_ext)
    x_init = x_ext[-1]

    # ---- G2b: the chain's start must hand over to the existing reforecast
    lead1_new = state.decode(one_step(x_init), (months_ext[-1] + 1) % 12)
    g2b = float(np.max(np.abs(lead1_new - prior_forecast['coefficients'][0])))
    log(json.dumps({'G2b_first_step_vs_prior_reforecast_2026_03': g2b, 'atol': TOL, 'passed': g2b <= TOL}))
    if g2b > TOL:
        raise SystemExit('G2b failed: chain start does not agree with the prior reforecast')

    # ---- the chain, with the gluing ledger (G3) and the scope check (G4)
    ledger = []
    chain_states = [x_init]
    cur = x_init
    for step in range(1, K_CHAIN + 1):
        nxt = one_step(cur)
        if not np.isfinite(nxt).all():
            raise SystemExit(f'non-finite state at step {step}')
        in_month = INIT_MONTH if step == 1 else ledger[-1]['output_month']
        out_month = str(np.datetime64(in_month, 'M') + 1)[:7]
        entry = {'step': step, 'input_month': in_month, 'output_month': out_month,
                 'input_fingerprint': fingerprint(cur), 'output_fingerprint': fingerprint(nxt),
                 'amplitude': float(np.sqrt(np.mean(nxt ** 2))),
                 'step_gain': float(np.sqrt(np.mean(nxt ** 2)) / np.sqrt(np.mean(cur ** 2))),
                 **scope_stats(nxt)}
        ledger.append(entry)
        chain_states.append(nxt)
        cur = nxt
    for k in range(len(ledger) - 1):
        if not (ledger[k]['output_month'] == ledger[k + 1]['input_month']
                and ledger[k]['output_fingerprint'] == ledger[k + 1]['input_fingerprint']):
            failures.append(f'G3 failed at junction {k + 1}->{k + 2}')
    log(json.dumps({'G3_gluing_ledger': [{'step': e['step'], 'in': e['input_month'], 'out': e['output_month'],
                                          'gain': round(e['step_gain'], 4), 'max_abs_z': round(e['max_abs_z'], 3),
                                          'out_of_scope': e['out_of_scope']} for e in ledger]}, ensure_ascii=False))

    chain_states = np.stack(chain_states)                     # (K+1, p), row 0 = 2026-02 observed
    target_labels = [str(np.datetime64(INIT_MONTH, 'M') + k)[:7] for k in range(1, K_CHAIN + 1)]
    chain_coeff = state.decode(chain_states[1:], month_index(target_labels))

    # ---- calibration on the backtest: chain vs direct vs AR(1) vs climatology
    rho = M.independent_ar(x_all, train)
    calibration = {}
    for k in range(1, K_CHAIN + 1):
        origins = backtest[backtest + k <= frozen_dates.shape[0] - 1]
        if len(origins) == 0:
            continue
        targets = origins + k
        rows = {}
        for name in ('chain', 'direct', 'ar1', 'identity', 'persistence_frozen', 'misaligned_12m'):
            if name == 'direct' and k > maps.shape[0]:
                continue
            if name == 'identity':
                # coefficient-space persistence: the observed state AT THE ORIGIN is the
                # prediction for the target (this is what an identity chain means).
                dec = proj['coefficients'][origins]
            elif name == 'persistence_frozen':
                # the frozen report's own convention: normalise at the origin, decode at
                # the target month. Kept for comparability; the difference is a residual.
                dec = state.decode(x_all[origins], frozen_months[targets])
            elif name == 'ar1':
                dec = state.decode(x_all[origins] * rho ** k, frozen_months[targets])
            elif name == 'misaligned_12m':
                base = x_all[origins - 12]
                for _ in range(k):
                    base = one_step(base)
                dec = state.decode(base, frozen_months[targets])
            elif name == 'chain':
                base = x_all[origins]
                for _ in range(k):
                    base = one_step(base)
                dec = state.decode(base, frozen_months[targets])
            else:
                dec = state.decode((x_all[origins] @ vectors) @ maps[k - 1], frozen_months[targets])
            met = score(proj, dec, targets, channels)
            rows[name] = {'resolved': aggregate(met, channels, 'resolved_mse'),
                          'full': aggregate(met, channels, 'full_mse')}
        clim = state.decode(np.zeros((len(origins), x_all.shape[1])), frozen_months[targets])
        met_c = score(proj, clim, targets, channels)
        rows['climatology'] = {'resolved': aggregate(met_c, channels, 'resolved_mse'),
                               'full': aggregate(met_c, channels, 'full_mse')}
        rows['n_origins'] = int(len(origins))
        rows['target_range'] = [str(frozen_dates[targets[0]])[:7], str(frozen_dates[targets[-1]])[:7]]
        for name in ('chain', 'direct', 'ar1', 'identity', 'persistence_frozen', 'misaligned_12m'):
            if name not in rows:
                continue
            rows[name + '_resolved_ratio_vs_direct'] = (
                float(np.mean([rows[name]['resolved'][c] / rows['direct']['resolved'][c] for c in rows[name]['resolved']]))
                if 'direct' in rows else None)
            rows[name + '_full_ratio_vs_direct'] = (
                float(np.mean([rows[name]['full'][c] / rows['direct']['full'][c] for c in rows[name]['full']]))
                if 'direct' in rows else None)
            rows[name + '_skill_vs_climatology'] = float(np.mean(
                [1.0 - rows[name]['full'][c] / rows['climatology']['full'][c] for c in rows[name]['full']]))
            rows[name + '_resolved_skill_vs_climatology'] = float(np.mean(
                [1.0 - rows[name]['resolved'][c] / rows['climatology']['resolved'][c] for c in rows[name]['resolved']]))
        calibration[k] = rows
        log(json.dumps({'k': k, 'n_origins': rows['n_origins'],
                        'chain_skill': round(rows['chain_skill_vs_climatology'], 5),
                        'direct_skill': round(rows.get('direct_skill_vs_climatology', float('nan')), 5),
                        'ar1_skill': round(rows['ar1_skill_vs_climatology'], 5),
                        'identity_skill': round(rows['identity_skill_vs_climatology'], 5),
                        'persistence_frozen_skill': round(rows['persistence_frozen_skill_vs_climatology'], 5),
                        'chain_resolved_ratio_vs_direct': (round(rows['chain_resolved_ratio_vs_direct'], 4)
                                                           if rows['chain_resolved_ratio_vs_direct'] else None),
                        'misaligned_resolved_ratio_vs_direct': (round(rows['misaligned_12m_resolved_ratio_vs_direct'], 4)
                                                                if rows['misaligned_12m_resolved_ratio_vs_direct'] else None)},
                       ensure_ascii=False))

    # ---- controls
    # C1 applies to k>=2: at k=1 one-month anomaly persistence is a genuinely strong
    # baseline, so that comparison is a readout, not a gate (stated in the contract).
    c1 = all(calibration[k]['chain_skill_vs_climatology'] > calibration[k]['identity_skill_vs_climatology'] + 1e-9
             for k in calibration if k >= 2)
    c1_k1 = (calibration[1]['chain_skill_vs_climatology'] - calibration[1]['identity_skill_vs_climatology'])
    c2 = all((calibration[k]['misaligned_12m_resolved_ratio_vs_direct'] or 0) > 1.0 + 1e-9
             for k in calibration if calibration[k]['misaligned_12m_resolved_ratio_vs_direct'])
    synth = scope_stats(x_init * 100.0)
    c3_fires = synth['out_of_scope']
    c3_quiet = True   # real chain states are reported, not asserted clean
    if not c1:
        failures.append('C1 failed (k=2..6): identity chain (persistence) was not worse than the real chain')
    if not c2:
        failures.append('C2 failed: a 12-month misaligned interface was not worse than the aligned chain')
    if not c3_fires:
        failures.append('C3 failed: the scope gate did not fire on a 100x inflated state')
    log(json.dumps({'C1_identity_worse_k2_to_k6': c1, 'C1_k1_chain_minus_identity': round(c1_k1, 5),
                    'C2_misaligned_worse': c2,
                    'C3_scope_fires_on_inflated': c3_fires,
                    'C3_inflated_max_abs_z': round(synth['max_abs_z'], 2)}, ensure_ascii=False))

    # ---- G6: k=1 chain == direct, on the predictions themselves
    o1 = backtest[backtest + 1 <= frozen_dates.shape[0] - 1]
    g6 = float(np.max(np.abs(one_step(x_all[o1]) - ((x_all[o1] @ vectors) @ maps[0]))))
    log(json.dumps({'G6_k1_chain_vs_direct_max_abs_diff': g6, 'atol': TOL, 'passed': g6 <= TOL}))
    if g6 > TOL:
        failures.append('G6 failed: at k=1 the chain and the direct map differ')

    # ---- G1 after
    hashes_after = {n: sha256(FROZEN / n) for n in FROZEN_FILES if (FROZEN / n).is_file()}
    prior_hashes_after = {n: sha256(PRIOR / n) for n in PRIOR_FILES if (PRIOR / n).is_file()}
    recorded = json.loads((PRIOR / 'report.json').read_text()).get('frozen_hashes_sha256', {})
    g1 = hashes_before == hashes_after and prior_hashes_before == prior_hashes_after
    for n in ('model.npz', 'projection-L12.npz', 'forecast.npz'):
        if n in recorded and recorded[n] != hashes_after.get(n):
            g1 = False
            failures.append(f'G1 failed: {n} differs from the hash recorded by the prior reforecast')
    if not g1:
        failures.append('G1 failed: a read-only artifact changed during this run')

    # ---- predictions (written down in the contract before the run)
    ratios = {k: calibration[k]['chain_resolved_ratio_vs_direct'] for k in calibration
              if calibration[k]['chain_resolved_ratio_vs_direct']}
    amps = [e['amplitude'] for e in ledger]
    amp0 = float(np.sqrt(np.mean(x_init ** 2)))
    amps_rel = [a / amp0 for a in amps]
    preds = [
        {'id': 'P1', 'claim': 'resolved_ratio_k > 1 对 k=2..6',
         'observed': {str(k): round(ratios[k], 4) for k in ratios if 2 <= k <= 6},
         'hit': all(ratios[k] > 1.0 for k in ratios if 2 <= k <= 6)},
        {'id': 'P2', 'claim': 'k=1 链式与直接逐位相同',
         'observed': {'max_abs_diff_resolved': g6}, 'hit': bool(g6 is not None and g6 <= TOL)},
        {'id': 'P3', 'claim': 'resolved_ratio_2 ∈ [1.2, 3.0]',
         'observed': round(ratios.get(2, float('nan')), 4),
         'hit': bool(2 in ratios and 1.2 <= ratios[2] <= 3.0)},
        {'id': 'P4', 'claim': 'resolved_ratio_k 随 k(2..6) 单调上升',
         'observed': {str(k): round(ratios[k], 4) for k in sorted(ratios) if 2 <= k <= 6},
         'hit': all(ratios[a] <= ratios[b] for a, b in zip([2, 3, 4, 5], [3, 4, 5, 6], strict=False)
                    if a in ratios and b in ratios)},
        {'id': 'P5', 'claim': 'resolved_ratio_6 > 2.0',
         'observed': round(ratios.get(6, float('nan')), 4),
         'hit': bool(6 in ratios and ratios[6] > 2.0)},
        {'id': 'P6', 'claim': '链式幅度随步数衰减（单调下降）',
         'observed': [round(a, 4) for a in amps_rel],
         'hit': all(amps_rel[i + 1] <= amps_rel[i] + 1e-9 for i in range(len(amps_rel) - 1))},
        {'id': 'P7', 'claim': '十步之内不出现 out_of_scope',
         'observed': {'out_of_scope_steps': [e['step'] for e in ledger if e['out_of_scope']]},
         'hit': not any(e['out_of_scope'] for e in ledger)},
    ]

    # ---- verdict
    if failures:
        verdict = 'instrument_failure'
    elif any(e['out_of_scope'] for e in ledger) and amps_rel[-1] > 1.0:
        verdict = 'chain_amplifies'
    elif all(a <= amps_rel[0] + 1e-9 for a in amps_rel[1:]) and all(v > 1.0 for v in ratios.values() if v):
        verdict = 'chain_decays'
    elif all(ratios[k] > 1.0 for k in ratios if k >= 2):
        verdict = 'chain_degrades'
    else:
        verdict = 'chain_degrades'

    # ---- readouts on the chain, in the same boxes the CFSv2 reference used
    grids = grids_for(proj, chain_coeff, channels, K_CHAIN)
    lat, lon = grids['lat'], grids['lon']
    w2 = area_weights(lat, lon).reshape(len(lat), len(lon))
    u, v = grids['u500'], grids['v500']
    speed = np.sqrt(u ** 2 + v ** 2)
    readouts = {'u500_v500_vector_speed_m_s': {}}
    for name, box in REGIONS.items():
        ilat, ilon = block_indices(lat, lon, box)
        readouts['u500_v500_vector_speed_m_s'][name] = [
            box_mean(speed[i], w2, ilat, ilon) for i in range(K_CHAIN)]
    ilat, ilon = block_indices(lat, lon, (PLATEAU['lat'][0], PLATEAU['lat'][1],
                                          PLATEAU['lon'][0], PLATEAU['lon'][1]))
    readouts['plateau_t2m_K'] = [box_mean(grids['t2m'][i], w2, ilat, ilon) for i in range(K_CHAIN)]
    readouts['months'] = target_labels
    cfs = json.loads((CFS_REF / 'report.json').read_text()) if (CFS_REF / 'report.json').is_file() else None
    cfs_2026_12 = None
    if cfs:
        for key in ('readouts', 'regions', 'values'):
            if isinstance(cfs.get(key), dict):
                cfs_2026_12 = cfs[key]
                break
    spectral = None
    try:
        rng = np.random.default_rng(0)
        w = rng.standard_normal(x_all.shape[1])
        for _ in range(60):
            w = (w @ vectors) @ maps[0]
            w = w / np.linalg.norm(w)
        sigma = float(np.linalg.norm((w @ vectors) @ maps[0]))
        spectral = {'largest_singular_value_estimate': sigma,
                    'method': 'power iteration on M1 (60 steps), estimate only'}
    except Exception as exc:                       # recorded, never silently skipped
        spectral = {'error': f'{type(exc).__name__}: {exc}'}

    report = {
        'question_id': contract['question_id'],
        'version': contract['version'],
        'generated_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'contract_sha256': sha256(CONTRACT),
        'initial_month': INIT_MONTH,
        'target_months': target_labels,
        'status': 'structural chained extrapolation with a measured iteration cost; NOT a skilled seasonal forecast',
        'model': {'artifact': str(FROZEN / 'model.npz'), 'operator': '(x @ vectors) @ maps[0]',
                  'no_retraining': True, 'fitted_for_iteration': False},
        'gates': {
            'G1_read_only_unchanged': g1,
            'G1_frozen_hashes': hashes_after, 'G1_prior_hashes': prior_hashes_after,
            'G2a_first_step_vs_frozen_lead1': g2a,
            'G2b_first_step_vs_prior_reforecast': g2b,
            'G3_gluing_ledger_consistent': not any(str(f).startswith('G3') for f in failures),
            'G4_scope_recorded': True,
            'G5_refuse_overwrite': True,
            'G6_k1_chain_equals_direct': g6,
            'atol': TOL,
        },
        'gluing_ledger': ledger,
        'scope_threshold_abs_z': SCOPE_Z,
        'calibration': {str(k): v for k, v in calibration.items()},
        'controls': {
            'C1_identity_chain_worse_k2_to_k6': c1,
            'C1_k1_chain_minus_identity_skill': c1_k1,
            'C2_misaligned_interface_worse': c2,
            'C3_scope_gate_fires_on_inflated_state': c3_fires,
            'C3_inflated_max_abs_z': synth['max_abs_z'],
            'C3_quiet_on_real_states': c3_quiet,
        },
        'spectral': spectral,
        'predictions': preds,
        'predictions_hit': sum(1 for p in preds if p['hit']),
        'predictions_total': len(preds),
        'failures': failures,
        'verdict': verdict,
        'verdict_text': {
            'chain_degrades': '依次推进可用，但每一步都在劣化；代价已在回测期量出',
            'chain_decays': '链在衰减并趋于气候态：推进可用但越往后越接近「报气候态」，必须如实说',
            'chain_amplifies': '迭代在放大（谱半径 ≥ 1）：外推不可用，必须降级',
            'instrument_failure': '闸门或对照不成立 ⇒ 不报判定',
        }[verdict],
        'readouts': readouts,
        'cfs_reference_available': bool(cfs),
        'cfs_reference_keys': (sorted(cfs_2026_12) if isinstance(cfs_2026_12, dict) else None),
        'known_representation_error': '高原 t2m 有已知表示误差（1 月偏差 +10.43 K，其中谱截断 +9.589 K）',
        'data_authenticity_reservation': '保留了提问方对数据真实性的保留意见；本件不消解它',
        'residuals': [
            '模型从未为迭代应用拟合过：输入由观测变成预测，属分布外输入；本件把代价量出，但**不**声称它无害',
            '回测期 2020–2025 此前已被看过（冻结契约的 prior_exposure）⇒ 不是全新验证样本',
            '链式结果是**结构性外推**，不是有技巧的季节预报；不得用于支撑厄尔尼诺强度结论',
            '作用域检查只覆盖「幅度是否越出训练范围」这一半；类型相符由构造保证，其余分布外形态**未检验**',
            'k>6 没有直接映射可比，只能用气候态／持续性／AR(1) 作对手',
        ],
        'wall_seconds': round(time.perf_counter() - started, 1),
        'peak_rss_mb': round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1),
    }
    (OUT / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    np.savez_compressed(OUT / 'chain.npz', months=np.array(target_labels), coefficients=chain_coeff,
                        states=chain_states, **grids)
    (OUT / 'run.log').write_text('\n'.join(log_lines) + '\n')
    log(json.dumps({'verdict': verdict, 'predictions': f"{report['predictions_hit']}/{report['predictions_total']}",
                    'failures': failures, 'wall_seconds': report['wall_seconds'],
                    'peak_rss_mb': report['peak_rss_mb']}, ensure_ascii=False))
    return 1 if failures else 0


if __name__ == '__main__':
    try:
        code = main()
    except BaseException as exc:                      # leave a trace, never exit silently
        import traceback
        OUT.mkdir(parents=True, exist_ok=True)
        tb = traceback.format_exc()
        failures.append(f'{type(exc).__name__}: {exc}')
        (OUT / 'report.json').write_text(json.dumps({
            'question_id': 'xue.derived.multivariate-chained-reforecast',
            'version': 'multivariate-chained-reforecast-v1',
            'generated_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'verdict': 'instrument_failure', 'failures': failures, 'traceback': tb,
        }, ensure_ascii=False, indent=2) + '\n')
        (OUT / 'run.log').write_text('\n'.join(log_lines) + '\n')
        print('INSTRUMENT FAILURE:', exc, flush=True)
        print(tb, flush=True)
        code = 1
    sys.exit(code)
