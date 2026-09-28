"""E1 — observation-quotient and residual accounting over the spectral vocabulary.

Framework (adva `0036`): a feature is a FINITE VOCABULARY ON AN OBSERVATIONAL
QUOTIENT; one circuit raises birthday / covering layer / construction depth /
EXACT RESIDUAL; the learner must deliver "quotient + descended dynamics +
holonomy + accountable residual". This round measures, for each truncation
degree d (the frame = the observer resolution Q):

  * vocabulary size  p(d)              (scalar (d+1)^2 ; vector 2(d+1)^2)
  * observation quotient  N_Q          (distinct validity-mask groups, from masked_project)
  * bit cost          L_coeff = p * 64 bits
  * residual          L_resid = sum_t (n_obs_t/2) * log2(2*pi*e*sigma_t^2)   [two-part MDL code]
  * total             L(d) = L_coeff + L_resid
  * null control      d = -1 : no coefficients at all (climatology / "represent nothing")

Verdict asked for: does the degree we actually ship (12) sit at the minimum of
L(d), and does the pair (bit cost, residual) behave monotonically in d as the
framework's refinement law requires?

Reads only. Writes one JSON. Refuses to overwrite.
"""
import json
import math
import resource
import time
from pathlib import Path

import numpy as np

REFINE = Path('/home/ubuntu/xue-study/experiments/multivariate-refinement')
import sys
sys.path.insert(0, str(REFINE))
sys.path.insert(0, str(REFINE.parent / 'typed-spectrum'))

import fields
import project
from project import geometry, interpolate_surface_pressure, masked_project, load_field

OUT = Path('/home/ubuntu/xue-study/archive/vocabulary-accounting-e1-v1')
LADDER = [4, 6, 8, 10, 12, 16]
BITS_PER_COEFF = 64.0          # float64 coefficients, uncoded
LOG2_2PIE = math.log2(2 * math.pi * math.e)


def code_length_from_residual(residual, n_obs):
    """Two-part MDL: Gaussian code length of the residual, in bits, summed over months."""
    total = 0.0
    for sse, n in zip(residual, n_obs):
        if n <= 0:
            continue
        sigma2 = float(sse) / float(n)
        if sigma2 <= 0:
            continue
        total += 0.5 * float(n) * (LOG2_2PIE + math.log2(sigma2))
    return total


def main():
    if (OUT / 'report.json').exists():
        raise FileExistsError(f'completed run already exists: {OUT}')
    OUT.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    channels = fields.CHANNELS
    rows = []
    failures = []

    for degree in LADDER:
        for ch in channels:
            name = ch['name']
            t0 = time.perf_counter()
            values, lat, lon, dates = load_field(ch['fields'][0])
            stack = [values.reshape(len(dates), -1)]
            for code in ch['fields'][1:]:
                v, la, lo, dt = load_field(code)
                if not (np.array_equal(lat, la) and np.array_equal(lon, lo) and np.array_equal(dates, dt)):
                    raise ValueError(f'{name}/{code}: misaligned channel')
                stack.append(v.reshape(len(dates), -1))
            y = np.stack(stack, axis=2)                     # (months, points, components)
            ncomp = y.shape[2]
            training = dates < '2015-01'
            fixed = np.isfinite(y[training]).all(axis=(0, 2))
            masks = np.broadcast_to(fixed, (len(dates), len(fixed))).copy()
            if ch['level'] is not None:
                pressure = interpolate_surface_pressure(lat, lon)
                fixed = fixed & (pressure[training].min(axis=0) >= ch['level'] * 100)
                masks = masks & fixed[None, :] & (pressure >= ch['level'] * 100)
            if name.startswith('q'):
                y = np.log(np.maximum(y, 1e-7))
            basis, weights = geometry(tuple(lat), tuple(lon), degree)
            matrix = basis.vector if ncomp == 2 else basis.scalar[:, None, :]
            p = matrix.shape[-1]
            try:
                coeff, bank, index, residual, diag = masked_project(matrix, y, weights, masks)
            except Exception as exc:                        # record, never silently skip
                failures.append({'degree': degree, 'channel': name, 'error': f'{type(exc).__name__}: {exc}'})
                print(json.dumps({'failed': name, 'degree': degree, 'why': str(exc)[:80]}), flush=True)
                continue
            n_obs = masks.sum(axis=1) * ncomp
            l_resid = code_length_from_residual(residual, n_obs)
            l_coeff = p * BITS_PER_COEFF
            # null control: no coefficients at all -> residual about the masked mean
            resid_null = []
            for t in range(len(dates)):
                m = masks[t]
                if m.sum() == 0:
                    resid_null.append(0.0)
                    continue
                block = y[t][m]
                w = np.repeat(weights[m] / weights[m].sum(), ncomp)
                mean = np.sum(block.reshape(-1) * w)
                resid_null.append(float(np.sum((block.reshape(-1) - mean) ** 2 * w)))
            l_null = code_length_from_residual(np.array(resid_null), n_obs)
            rows.append({
                'degree': degree, 'channel': name, 'coefficients': int(p),
                'components': int(ncomp), 'months': int(len(dates)),
                'observation_quotient_groups': int(diag['distinct_domains']),
                'max_gram_condition': float(diag['max_gram_condition']),
                'min_area_fraction': float(diag['min_area_fraction']),
                'residual_mean': float(np.mean(residual)),
                'L_coeff_bits': l_coeff, 'L_resid_bits': l_resid,
                'L_total_bits': l_coeff + l_resid, 'L_null_bits': l_null,
                'seconds': round(time.perf_counter() - t0, 2)})
            print(json.dumps({'channel': name, 'degree': degree, 'p': int(p),
                              'L_coeff': round(l_coeff), 'L_resid': round(l_resid),
                              'null': round(l_null), 'secs': round(time.perf_counter() - t0, 1)}), flush=True)

    # ---- per-degree aggregate over channels
    ladder_summary = []
    for degree in LADDER:
        sub = [r for r in rows if r['degree'] == degree]
        if not sub:
            continue
        ladder_summary.append({
            'degree': degree,
            'coefficients_total': int(sum(r['coefficients'] for r in sub)),
            'L_coeff_total_bits': sum(r['L_coeff_bits'] for r in sub),
            'L_resid_total_bits': sum(r['L_resid_bits'] for r in sub),
            'L_total_bits': sum(r['L_total_bits'] for r in sub),
            'null_total_bits': sum(r['L_null_bits'] for r in sub),
            'channels': len(sub)})
    best = min(ladder_summary, key=lambda r: r['L_total_bits']) if ladder_summary else None
    shipped = next((r for r in ladder_summary if r['degree'] == fields.DEGREE), None)
    report = {
        'question_id': 'xue.derived.vocabulary-accounting-e1',
        'version': 'vocabulary-accounting-e1-v1',
        'framework': 'adva 0036 §1.5/§1.6/§1.12/§2.12 — finite vocabulary on an observational quotient;'
                     ' two-part MDL with an accountable residual; null = represent nothing',
        'ladder_degrees': LADDER,
        'bits_per_coefficient': BITS_PER_COEFF,
        'shipped_degree': int(fields.DEGREE),
        'argmin_degree': best['degree'] if best else None,
        'shipped_is_argmin': bool(best and best['degree'] == fields.DEGREE),
        'ladder_summary': ladder_summary,
        'per_channel': rows,
        'failures': failures,
        'wall_seconds': round(time.perf_counter() - started, 1),
        'peak_rss_mb': round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1),
    }
    (OUT / 'report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + '\n')
    print(json.dumps({'argmin_degree': report['argmin_degree'],
                      'shipped': report['shipped_degree'],
                      'shipped_is_argmin': report['shipped_is_argmin'],
                      'wall_s': report['wall_seconds'],
                      'ladder': [{k: (round(v) if isinstance(v, float) else v)
                                  for k, v in r.items() if k in ('degree', 'coefficients_total',
                                                                 'L_coeff_total_bits', 'L_resid_total_bits',
                                                                 'L_total_bits', 'null_total_bits')}
                                 for r in ladder_summary]}, ensure_ascii=False, indent=1), flush=True)


if __name__ == '__main__':
    main()
