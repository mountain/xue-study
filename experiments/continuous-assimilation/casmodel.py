"""Analysis, forecast issue and forecast verification.

The analysis is what this pipeline calls assimilation, and it is exactly ONE operation:
the observed monthly mean is projected onto the FROZEN observation domains and Gram
matrices (an exact least-squares solve), giving the model's normalised state.

It is NOT variational or Kalman assimilation: there is no background-error covariance,
no increment solve, and no analysis update. An earlier version of this docstring claimed
the difference against a running background forecast "is recorded as an increment" --
that was FALSE, the code never did it. Computing an increment needs a background
forecast for the same month; it is listed as not-done below rather than described as
done.

NOT DONE (stated so the reader does not have to infer it): background forecast and
increment; a quotient derived from distinguishability (the truncation degree is still an
assumed presentation, per E1); any per-circuit lift accounting (birthday, covering
layer, construction depth, exact residual); any holonomy record.

Verification rule: a forecast is scored only against an observation from the SAME
source caliber. Cross-source comparison needs the V3 overlap gate, which needs
overlapping months; until then operational scores stay labelled `provisional`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

import cas

REFINE = cas.REPO / 'experiments/multivariate-refinement'
if str(REFINE) not in sys.path:
    sys.path.insert(0, str(REFINE))
    sys.path.insert(0, str(REFINE.parent / 'typed-spectrum'))

import fields                      # noqa: E402
import model as M                  # noqa: E402
import project                     # noqa: E402
from project import geometry, masked_project   # noqa: E402

R1_INPUTS = Path('/home/ubuntu/climatetensor-inputs/ncep-multivariate-ext-202602')
R1_INPUTS_ORIG = Path('/home/ubuntu/climatetensor-inputs/ncep-multivariate')


def load_frozen() -> dict:
    with np.load(cas.FROZEN / 'model.npz', allow_pickle=False) as m:
        model = {k: m[k] for k in m.files}
    with np.load(cas.FROZEN / 'projection-L12.npz', allow_pickle=False) as p:
        proj = {k: p[k] for k in p.files}
    return {'model': model, 'proj': proj, 'channels': json.loads(str(proj['channels_json']))}


def missing_channels(available_variables: set[str]) -> dict:
    """Which model channels can be built from the variables actually frozen."""
    missing, derived, ok = [], [], []
    for ch in fields.CHANNELS:
        name = ch['name']
        src = cas.CHANNEL_SOURCE.get(name, {})
        need = set(src.get('from_', []))
        if src.get('status') == 'missing' or not need:
            missing.append({'channel': name, 'why': src.get('why', 'no declared source')})
        elif need <= available_variables:
            (derived if src.get('status') == 'derived' else ok).append(name)
        else:
            missing.append({'channel': name, 'why': f'needs {sorted(need)} (not frozen)'})
    return {'buildable': ok, 'derived_only': derived, 'missing': missing}


def build_analysis(collection: str, month: str, allow_derived: bool = False,
                   allow_missing_proxy: bool = False) -> dict:
    """Project a monthly mean onto the frozen observation domains."""
    frozen = load_frozen()
    proj, channels = frozen['proj'], frozen['channels']
    lat, lon = np.asarray(proj[channels[0]['name'] + '_lat']), np.asarray(proj[channels[0]['name'] + '_lon'])
    monthly = cas.monthly_mean(collection, month, np.linspace(90, -90, cas.NATIVE_GRID[0]),
                               np.linspace(-180, 180 - 360 / cas.NATIVE_GRID[1], cas.NATIVE_GRID[1]),
                               lat, lon)
    if monthly['status'] != 'ok':
        return {'month': month, 'collection': collection, 'status': 'no_data'}
    avail = set(monthly['model'])
    coverage = missing_channels(avail)

    fields.INPUTS = R1_INPUTS
    project.INPUTS = R1_INPUTS
    project.geometry.cache_clear()

    per_channel, blocks, offset = [], {}, 0
    for ch in channels:
        name = ch['name']
        block = ch['stop'] - ch['start']
        src = cas.CHANNEL_SOURCE.get(name, {})
        usable = src.get('status') == 'direct' and set(src.get('from_', [])) <= avail
        if not usable:
            per_channel.append({'channel': name, 'status': 'blocked',
                                'why': src.get('why') or f'variables {src.get("from_")} not available'})
            offset += block
            continue
        vals, ncomp = _channel_values(name, monthly['model'])
        if vals is None:
            per_channel.append({'channel': name, 'status': 'blocked', 'why': 'value assembly failed'})
            offset += block
            continue
        basis, weights = geometry(tuple(lat), tuple(lon), fields.DEGREE)
        matrix = basis.vector if ncomp == 2 else basis.scalar[:, None, :]
        fixed = np.asarray(proj[name + '_domain'])
        masks = np.broadcast_to(fixed.ravel(), (1, fixed.size)).copy()
        try:
            coeff, _, _, residual, diag = masked_project(matrix, vals[None, :, :], weights, masks)
        except Exception as exc:                               # noqa: BLE001
            per_channel.append({'channel': name, 'status': 'blocked',
                                'why': f'{type(exc).__name__}: {exc}'})
            offset += block
            continue
        blocks[name] = coeff[0]
        per_channel.append({'channel': name, 'status': 'projected', 'block': block,
                            'residual': float(residual[0]),
                            'max_gram_condition': float(diag['max_gram_condition']),
                            # distinct_domains is the closest thing this pipeline has to an
                            # observation-quotient count; it is recorded, not interpreted.
                            'distinct_domains': int(diag['distinct_domains']),
                            'min_area_fraction': float(diag['min_area_fraction'])})
        offset += block

    total = sum(ch['stop'] - ch['start'] for ch in channels)
    got = sum(v.size for v in blocks.values())
    blocked = [p for p in per_channel if p['status'] == 'blocked']
    result = {
        'month': month, 'collection': collection, 'status': 'ok' if not blocked else 'blocked',
        'n_days_used': monthly['n_days'], 'complete_month': monthly['complete'],
        'coverage': coverage, 'per_channel': per_channel,
        'coefficients_expected': int(total), 'coefficients_built': int(got),
        'pressure_screening': 'training_domain_only (no monthly sp available from this source)',
        'caliber_changes': ['0.25 deg -> 2.5 deg box average (cosine weighted)',
                            'synoptic analyses -> daily mean -> monthly mean',
                            'pressure-level monthly screening omitted (no sp in source)'],
        'why_blocked': ([f'{p["channel"]}: {p["why"]}' for p in blocked] if blocked else []),
        'assimilation_kind': 'observation projection onto frozen domains; NOT variational/Kalman',
    }
    if blocked:
        result['forecast_allowed'] = False
        if allow_missing_proxy:
            result['note'] = 'proxy fill requested but NOT implemented: a proxy needs a human declaration'
        return result
    coeff = np.concatenate([blocks[ch['name']] for ch in channels])
    state = M.SeasonalState(frozen['model']['climatology'], frozen['model']['scale'])
    midx = np.datetime64(month + '-01', 'M').astype(int) % 12
    result.update({'status': 'ok', 'forecast_allowed': True,
                   'x_state_sha256': _hash_array(state.encode(coeff, midx)),
                   '_x_state': state.encode(coeff, midx), '_coefficients': coeff})
    return result


def _channel_values(name: str, monthly: dict):
    """Assemble (points, components) for one channel from the frozen monthly means."""
    src = cas.CHANNEL_SOURCE.get(name, {})
    keys = src.get('from_', [])
    if name.startswith('wind'):
        key = keys[0]
        if key not in monthly:
            return None, 2
        uv = monthly[key]                                  # (2, lat, lon)
        return np.stack([uv[0].ravel(), uv[1].ravel()], axis=1), 2
    if name in ('t850', 't2m', 'msl', 'z500', 'w500', 'w700'):
        key = keys[0]
        return (None, 1) if key not in monthly else (monthly[key].ravel()[:, None], 1)
    if name in ('q850', 'q700'):
        return None, 1                                     # derived: needs a declaration
    return None, 1


def _hash_array(arr: np.ndarray) -> str:
    import hashlib
    return hashlib.sha256(np.ascontiguousarray(arr, dtype=np.float64).tobytes()).hexdigest()


def issue_forecast(analysis: dict) -> dict:
    """Issue leads 1..6 from an analysis and append to the ledger (append-only)."""
    if analysis.get('status') != 'ok' or not analysis.get('forecast_allowed'):
        rec = {'event': 'forecast_refused', 'month': analysis.get('month'),
               'why': 'analysis blocked (G7: never fill a missing channel to make a forecast)',
               'blocked': analysis.get('why_blocked'), 'at_utc': cas.utcnow()}
        cas.append_jsonl('forecasts.jsonl', rec)
        return rec
    frozen = load_frozen()
    model = frozen['model']
    initial = analysis['month']
    existing = {r.get('initial_month') for r in cas.read_jsonl('forecasts.jsonl')
                if r.get('event') == 'forecast_issued'}
    if initial in existing:
        rec = {'event': 'forecast_refused', 'initial_month': initial,
               'why': 'a forecast for this initial month already exists (G5)', 'at_utc': cas.utcnow()}
        cas.append_jsonl('forecasts.jsonl', rec)
        return rec
    x = np.asarray(analysis['_x_state'], dtype=np.float64)
    forecasts = (x @ model['vectors']) @ model['maps']
    targets = [str(np.datetime64(initial + '-01', 'M') + k)[:7] for k in range(1, 7)]
    state = M.SeasonalState(model['climatology'], model['scale'])
    coeff = state.decode(forecasts, np.array([np.datetime64(t + '-01', 'M').astype(int) % 12 for t in targets]))
    entry = {'event': 'forecast_issued', 'initial_month': initial, 'target_months': targets,
             'collection': analysis['collection'], 'at_utc': cas.utcnow(),
             'model_sha256': cas.sha256_file(cas.FROZEN / 'model.npz'),
             'projection_sha256': cas.sha256_file(cas.FROZEN / 'projection-L12.npz'),
             'x_state_sha256': analysis['x_state_sha256'],
             'coefficients_sha256': _hash_array(coeff),
             'coefficients': np.round(coeff, 6).tolist(),
             'status': 'pending_verification',
             'caliber_changes': analysis['caliber_changes']}
    cas.append_jsonl('forecasts.jsonl', entry)
    return entry


def observation_for(month: str) -> dict:
    """Admissible observation for a target month, or a reason why there is none."""
    r1 = R1_INPUTS if R1_INPUTS.is_dir() else R1_INPUTS_ORIG
    info = {'month': month, 'r1_dir': str(r1)}
    try:
        with np.load(r1 / 'u500.npz') as f:
            dates = np.asarray(f['time'])
        last = str(dates[-1])[:7]
        info['r1_last_month'] = last
        info['r1_available'] = month <= last
    except Exception as exc:                                   # noqa: BLE001
        info['r1_available'] = False
        info['r1_error'] = f'{type(exc).__name__}: {exc}'
    if info['r1_available']:
        info.update({'status': 'verified', 'source': 'R1 monthly mean (model training caliber)'})
    else:
        info.update({'status': 'pending',
                     'source': None,
                     'why': f'target month {month} is later than the R1 inputs ({info.get("r1_last_month")}); '
                            f'no admissible observation yet'})
    return info


def verify_due() -> dict:
    """Score every issued forecast whose target month now has an admissible observation."""
    issued = [r for r in cas.read_jsonl('forecasts.jsonl') if r.get('event') == 'forecast_issued']
    done = {(r.get('initial_month'), r.get('target_month')) for r in cas.read_jsonl('verification.jsonl')}
    scored, pending = [], []
    for entry in issued:
        coeff = np.asarray(entry['coefficients'], dtype=np.float64)
        for lead, target in enumerate(entry['target_months'], start=1):
            if (entry['initial_month'], target) in done:
                continue
            obs = observation_for(target)
            if obs['status'] != 'verified':
                pending.append({'initial_month': entry['initial_month'], 'target_month': target,
                                'status': obs['status'], 'why': obs['why']})
                continue
            res = score_month(coeff[lead - 1], target, lead)
            rec = {'event': 'verified', 'initial_month': entry['initial_month'],
                   'target_month': target, 'lead': lead, 'at_utc': cas.utcnow(),
                   'observation_source': obs['source'], 'observation_month': target,
                   'forecast_source': entry.get('collection'),
                   'forecast_coefficients_sha256': entry.get('coefficients_sha256'),
                   **res}
            cas.append_jsonl('verification.jsonl', rec)
            scored.append({k: rec[k] for k in ('initial_month', 'target_month', 'lead', 'status')}
                          | {'aggregate': rec.get('aggregate')})
    _refresh_summary()
    return {'scored': scored, 'pending': pending}


def truth_for_month(target: str) -> dict:
    """Truth for one target month in the frozen model's own scoring caliber.

    Inside the frozen history the coefficients, Gram bank and residual are already
    computed, so scoring is directly comparable with the published report. Outside it
    the month is projected from the R1 inputs with the SAME procedure, and the Gram is
    taken from that projection so the comparison stays self-consistent.
    """
    frozen = load_frozen()
    proj, channels = frozen['proj'], frozen['channels']
    dates = np.asarray(proj['dates']).astype('datetime64[M]').astype(str)
    if target in set(dates.tolist()):
        idx = int(np.flatnonzero(dates == target)[0])
        out = {'kind': 'frozen_history', 'index': idx, 'per_channel': {}}
        for ch in channels:
            name = ch['name']
            bank = np.asarray(proj[name + '_gram_bank'])
            gi = int(np.asarray(proj[name + '_gram_index'])[idx])
            out['per_channel'][name] = {
                'c': np.asarray(proj[name + '_c'])[idx],
                'G': bank[gi],
                'residual': float(np.asarray(proj[name + '_residual'])[idx])}
        return out

    r1 = R1_INPUTS if R1_INPUTS.is_dir() else R1_INPUTS_ORIG
    fields.INPUTS = r1
    project.INPUTS = r1
    project.geometry.cache_clear()
    lat = lon = None
    per_channel, problems = {}, []
    for ch in channels:
        name = ch['name']
        try:
            stack, lat, lon, dts = [], None, None, None
            for code in ch['fields']:
                values, la, lo, dt = project.load_field(code)
                stack.append(values.reshape(len(dt), -1))
                if lat is None:
                    lat, lon, dts = la, lo, np.asarray(dt).astype('datetime64[M]').astype(str)
            if target not in set(dts.tolist()):
                problems.append({'channel': name, 'why': f'{target} not in R1 inputs'})
                continue
            ti = int(np.flatnonzero(dts == target)[0])
            y = np.stack(stack, axis=2)[ti:ti + 1]
            fixed = np.asarray(proj[name + '_domain'])
            masks = np.broadcast_to(fixed.ravel(), (1, fixed.size)).copy()
            if name.startswith('q'):
                y = np.log(np.maximum(y, 1e-7))
            basis, weights = geometry(tuple(lat), tuple(lon), fields.DEGREE)
            matrix = basis.vector if len(ch['fields']) == 2 else basis.scalar[:, None, :]
            coeff, bank, _idx, residual, _diag = masked_project(matrix, y, weights, masks)
            per_channel[name] = {'c': coeff[0], 'G': bank[0], 'residual': float(residual[0])}
        except Exception as exc:                               # noqa: BLE001
            problems.append({'channel': name, 'why': f'{type(exc).__name__}: {exc}'})
    return {'kind': 'projected_from_r1', 'per_channel': per_channel, 'problems': problems}


def score_month(forecast_coeff: np.ndarray, target: str, lead: int) -> dict:
    """resolved / full MSE for the forecast, climatology and persistence at one month."""
    frozen = load_frozen()
    channels, model = frozen['channels'], frozen['model']
    truth = truth_for_month(target)
    if not truth['per_channel']:
        return {'status': 'unavailable', 'why': truth.get('problems')}
    midx = int(np.datetime64(target + '-01', 'M').astype(int) % 12)
    clim = model['climatology'][midx]
    prev = truth_for_month(str(np.datetime64(target + '-01', 'M') - 1)[:7])
    per = {}
    for ch in channels:
        name = ch['name']
        if name not in truth['per_channel']:
            continue
        a, b = ch['start'], ch['stop']
        c, G = truth['per_channel'][name]['c'], truth['per_channel'][name]['G']
        res = truth['per_channel'][name]['residual']
        d_f = np.asarray(forecast_coeff[a:b]) - c
        d_c = np.asarray(clim[a:b]) - c
        row = {'resolved_forecast': float(d_f @ G @ d_f),
               'full_forecast': float(d_f @ G @ d_f) + res,
               'resolved_climatology': float(d_c @ G @ d_c),
               'full_climatology': float(d_c @ G @ d_c) + res}
        if name in prev['per_channel']:
            d_p = prev['per_channel'][name]['c'] - c
            row['resolved_persistence'] = float(d_p @ G @ d_p)
            row['full_persistence'] = float(d_p @ G @ d_p) + res
        per[name] = row
    agg = {}
    for key in ('resolved_forecast', 'full_forecast', 'resolved_climatology',
                'full_climatology', 'resolved_persistence', 'full_persistence'):
        vals = [v[key] for v in per.values() if key in v]
        if vals:
            agg[key] = float(np.mean(vals))
    if 'full_climatology' in agg and agg['full_climatology'] > 0:
        agg['skill_vs_climatology'] = float(1.0 - agg['full_forecast'] / agg['full_climatology'])
    if agg.get('full_persistence', 0) > 0:
        agg['skill_vs_persistence'] = float(1.0 - agg['full_forecast'] / agg['full_persistence'])
    return {'status': 'scored', 'truth_kind': truth['kind'], 'lead': lead,
            'target_month': target, 'per_channel': per, 'aggregate': agg}


def _refresh_summary() -> None:
    rows = cas.read_jsonl('verification.jsonl')
    summary = {'generated_utc': cas.utcnow(), 'n_records': len(rows),
               'by_status': {}, 'pending_examples': []}
    for r in rows:
        key = str(r.get('status') or r.get('event'))
        summary['by_status'][key] = summary['by_status'].get(key, 0) + 1
    scored = [r for r in rows if r.get('status') == 'scored']
    if scored:
        summary['by_lead'] = {}
        for r in scored:
            lead = str(r.get('lead'))
            agg = r.get('aggregate') or {}
            summary['by_lead'].setdefault(lead, {'n': 0, 'skill_vs_climatology': []})
            summary['by_lead'][lead]['n'] += 1
            if 'skill_vs_climatology' in agg:
                summary['by_lead'][lead]['skill_vs_climatology'].append(agg['skill_vs_climatology'])
        for _lead, d in summary['by_lead'].items():
            if d['skill_vs_climatology']:
                d['mean_skill_vs_climatology'] = float(np.mean(d['skill_vs_climatology']))
            d.pop('skill_vs_climatology', None)
    cas.write_json_atomic(cas.ledger_path('summary.json'), summary)


def verify_against_frozen() -> dict:
    """Gate: the verifier must reproduce the frozen report's published metrics.

    This is the test that makes the verification program trustworthy: it recomputes
    the development backtest from the frozen model and compares against the numbers
    already published in archive/multivariate-l12-v1/report.json.
    """
    frozen = load_frozen()
    model, proj, channels = frozen['model'], frozen['proj'], frozen['channels']
    dates = np.asarray(proj['dates'])
    months = dates.astype('datetime64[M]').astype(int) % 12
    state = M.SeasonalState(model['climatology'], model['scale'])
    x = state.encode(np.asarray(proj['coefficients'], dtype=np.float64), months)
    test = np.where(dates >= '2020-01')[0]
    learned = M.predict(x, test, model['vectors'], model['maps'])
    physical = state.decode(learned, months[test])
    metrics = M.score_coefficients(proj, physical, test, channels)
    report = json.loads((cas.FROZEN / 'report.json').read_text())
    worst, detail = 0.0, {}
    for name, scores in metrics.items():
        published = report['metrics']['joint'][name]
        agreed = float(np.max(np.abs(np.mean(scores['resolved_mse']) -
                                     np.mean(published['resolved_mse']))))
        detail[name] = agreed
        worst = max(worst, agreed)
    return {'gate': 'verifier reproduces the frozen published metrics',
            'max_abs_difference_in_mean_resolved_mse': worst, 'per_channel': detail,
            'passed': worst <= 1e-9}
