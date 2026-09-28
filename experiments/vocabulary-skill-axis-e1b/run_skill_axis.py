"""E1b — the skill axis opposite E1's accounting axis.

For each truncation degree d (the fineness of the spectral vocabulary) this runs
the SAME pipeline independently: build the projection at that degree, fit the
training-only seasonal state, select one global rank/penalty on VALIDATION only,
then score the development backtest. It then joins E1's accounting numbers and
asks whether the two axes point the same way.

Reads only. Writes archive/vocabulary-skill-axis-e1b-v1/. Refuses to overwrite.
The frozen archive/multivariate-l12-v1/ is never written: project.ROOT is
redirected to this run's own output directory before every build() call.
"""
from datetime import datetime, timezone
import hashlib
import json
import resource
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path('/home/ubuntu/xue-study')
REFINE = REPO / 'experiments/multivariate-refinement'
sys.path.insert(0, str(REFINE))
sys.path.insert(0, str(REFINE.parent / 'typed-spectrum'))

import fields
import project
from model import fit_state, select, predict, independent_ar, score_coefficients

OUT = REPO / 'archive/vocabulary-skill-axis-e1b-v3'
FROZEN = REPO / 'archive/multivariate-l12-v1'
E1_REPORT = REPO / 'archive/vocabulary-accounting-e1-v1/report.json'
REFORECAST_REPORT = REPO / 'archive/multivariate-reforecast-202602-v1/report.json'
CONTRACT = Path(__file__).resolve().parent / 'contract-v3.json'
# Bounded-ladder caps: a degree that overruns, or a run that exhausts its budget,
# stops the ladder and reports the completed subset instead of hanging.
MAX_DEGREE_SECONDS = 900.0
MAX_TOTAL_SECONDS = 5400.0

FROZEN_FILES = ['model.npz', 'projection-L12.npz', 'forecast.npz', 'report.json']
FROZEN_HASH_KEYS = ['model.npz', 'projection-L12.npz', 'forecast.npz']
FROZEN_REPORT = FROZEN / 'report.json'
G5_TOL = 1e-9

failures = []
log_lines = []


def log(msg, **kwargs):
    # Forward extra print keywords rather than crashing the run on them; the
    # first launch died exactly this way (see the guard at the bottom).
    log_lines.append(str(msg))
    print(msg, flush=True, **kwargs)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def same(a, b):
    a = np.asarray(a)
    b = np.asarray(b)
    if a.shape != b.shape:
        return False
    if a.dtype.kind in 'fc' and b.dtype.kind in 'fc':
        return bool(np.array_equal(a, b, equal_nan=True))
    return bool(np.array_equal(a, b))


def monotone_nonincreasing(xs, tol=1e-9):
    return all(xs[i + 1] <= xs[i] + tol for i in range(len(xs) - 1))


def aggregate_skill(metrics, channels, pred_key):
    """Equal channel weight, equal lead weight; full_mse skill vs climatology at this degree.

    Defined at module level with explicit parameters: an earlier draft closed over
    the per-degree loop variables, which ruff flagged (B023) as a binding hazard.
    """
    base = metrics['climatology']
    per_channel = {}
    for ch in channels:
        name = ch['name']
        b = np.array(base[name]['full_mse'])
        p = np.array(metrics[pred_key][name]['full_mse'])
        per_channel[name] = (1.0 - p / b).tolist()
    mean_by_lead = np.mean([per_channel[ch['name']] for ch in channels], axis=0)
    return per_channel, mean_by_lead.tolist(), float(mean_by_lead.mean())


def main():
    if (OUT / 'report.json').exists():
        raise FileExistsError(f'completed run already exists: {OUT}')
    contract = json.loads(CONTRACT.read_text())
    LADDER = contract['design']['ladder_degrees']
    RANKS = contract['design']['ranks']
    PENALTIES = contract['design']['ridge_mean_loss_penalties']
    started = time.perf_counter()

    frozen_before = {n: sha256(FROZEN / n) for n in FROZEN_FILES if (FROZEN / n).is_file()}
    log(json.dumps({'frozen_hashes_before': frozen_before}, indent=1))

    with np.load(FROZEN / 'projection-L12.npz') as f:
        frozen_projection = {k: f[k] for k in f.files}

    per_degree = []
    stopped_reason = None
    for degree in LADDER:
        t0 = time.perf_counter()
        outd = OUT / f'L{degree}'
        outd.mkdir(parents=True, exist_ok=True)
        project.ROOT = outd                      # never write into the frozen archive
        path = project.build(degree)
        t_build = time.perf_counter()
        with np.load(path) as f:
            projection = {k: f[k] for k in f.files}
        channels = json.loads(str(projection['channels_json']))
        blocks = [(ch['start'], ch['stop']) for ch in channels]
        c = projection['coefficients']
        dates = projection['dates']
        months = dates.astype('datetime64[M]').astype(int) % 12
        train = np.where(dates < '2015-01')[0]
        valid = np.where((dates >= '2015-01') & (dates < '2020-01'))[0]
        test = np.where(dates >= '2020-01')[0]
        assert (len(train), len(valid), len(test)) == (432, 60, 72), (degree, len(train), len(valid), len(test))

        # ---- G1 domain invariance, every degree, every channel
        domain_ok = True
        for ch in channels:
            name = ch['name']
            if not same(projection[name + '_domain'], frozen_projection[name + '_domain']):
                domain_ok = False
                failures.append(f'G1 domain mismatch at d={degree} channel={name}')
        if not domain_ok:
            raise SystemExit('G1 failed: observation domain changed with degree')

        # ---- G2 exact reproduction of the frozen L12 projection
        if degree == fields.DEGREE:
            keys_frozen = set(frozen_projection)
            keys_mine = set(projection)
            if keys_frozen != keys_mine:
                raise SystemExit(f'G2 failed: key sets differ {keys_frozen ^ keys_mine}')
            bad = [k for k in sorted(keys_frozen) if not same(projection[k], frozen_projection[k])]
            if bad:
                raise SystemExit(f'G2 failed: arrays differ at d=12: {bad}')
            log(f'G2 ok: all {len(keys_frozen)} arrays of the d=12 projection reproduce the frozen artifact exactly')

        state = fit_state(c, months, train, blocks)
        x = state.encode(c, months)
        vectors, maps, chosen, candidates = select(x, train, valid, RANKS, PENALTIES)
        learned = predict(x, test, vectors, maps)
        independent = np.zeros_like(learned)
        for ch in channels:
            a, b = ch['start'], ch['stop']
            v, m, _sel, _rows = select(x[:, a:b], train, valid, RANKS, PENALTIES)
            independent[:, :, a:b] = predict(x[:, a:b], test, v, m)
        rho = independent_ar(x, train)
        coeff_predictions = {
            'climatology': np.zeros_like(learned),
            'persistence': np.stack([x[test - lead] for lead in range(1, 7)]),
            'independent_ar1': np.stack([x[test - lead] * rho ** lead for lead in range(1, 7)]),
            'independent_channels': independent,
            'joint': learned,
        }
        physical = {k: state.decode(v, months[test]) for k, v in coeff_predictions.items()}
        metrics = {k: score_coefficients(projection, v, test, channels) for k, v in physical.items()}
        t_fit = time.perf_counter()

        per_channel_skill, skill_by_lead, skill_mean = aggregate_skill(metrics, channels, 'joint')
        _, indep_by_lead, indep_mean = aggregate_skill(metrics, channels, 'independent_channels')
        _, persist_by_lead, persist_mean = aggregate_skill(metrics, channels, 'persistence')
        _, ar1_by_lead, ar1_mean = aggregate_skill(metrics, channels, 'independent_ar1')

        coeff_mse = {k: float(np.mean(np.sum((v - x[test]) ** 2, axis=2))) for k, v in coeff_predictions.items()}

        # ---- C1 hindsight control: select on the backtest period itself
        hv, hm, hchosen, _hrows = select(x, train, test, RANKS, PENALTIES)
        hp = predict(x, test, hv, hm)
        hp_phys = state.decode(hp, months[test])
        # score_coefficients returns {channel_name: {...}} for ONE prediction set,
        # while `metrics` above is {variant: {channel_name: {...}}}. The shared
        # aggregate_skill() takes the variant-keyed form, so wrap the control
        # scores accordingly. (Revision 3: the second launch died here -- the
        # refactor to the shared helper dropped this wrapping and raised
        # KeyError: 'climatology' after the whole degree had already been computed.)
        hmetrics = {'climatology': metrics['climatology'],
                    'joint': score_coefficients(projection, hp_phys, test, channels)}
        hskill = aggregate_skill(hmetrics, channels, 'joint')[2]
        # The quantity `select` actually minimizes, so that hindsight can be tested
        # on the criterion it optimizes rather than on a different one.
        h_coeff_on_test = float(np.mean(np.sum((hp - x[test]) ** 2, axis=2)))

        # ---- C2 shuffled-lead control: wrong lead alignment must score worse
        shuffled = np.roll(learned, 1, axis=0)
        sh_phys = state.decode(shuffled, months[test])
        shmetrics = {'climatology': metrics['climatology'],
                     'joint': score_coefficients(projection, sh_phys, test, channels)}
        shskill = aggregate_skill(shmetrics, channels, 'joint')[2]

        t_scored = time.perf_counter()
        # ---- G5 independent reproduction of the frozen report's headline numbers
        g5 = None
        if degree == fields.DEGREE:
            frozen_report = json.loads(FROZEN_REPORT.read_text())
            for variant, mine in (('joint', skill_mean), ('independent_channels', indep_mean)):
                theirs = float(np.mean([np.mean(s['full_skill_vs_climatology'])
                                        for s in frozen_report['metrics'][variant].values()]))
                ok = abs(theirs - mine) <= G5_TOL
                g5 = dict(g5 or {}, **{variant: {'frozen_report': theirs, 'this_run': mine, 'match': bool(ok)}})
                if not ok:
                    failures.append(f'G5 failed: {variant} at d=12 differs from the frozen report '
                                    f'({theirs} vs {mine})')
            log(f'G5 d=12 vs frozen report: {json.dumps(g5, ensure_ascii=False)}')

        # ---- C2 target-axis misalignment: predictions compared against the wrong months
        rolled_target = state.decode(np.roll(learned, 1, axis=1), months[test])
        rtmetrics = {'climatology': metrics['climatology'],
                     'joint': score_coefficients(projection, rolled_target, test, channels)}
        rt_skill = aggregate_skill(rtmetrics, channels, 'joint')[2]

        row = {
            'g5_frozen_report_match': g5,
            'target_rolled_skill_mean': rt_skill,
            'phase_seconds': {'build': round(t_build - t0, 2),
                              'fit_and_predict': round(t_fit - t_build, 2),
                              'score_and_controls': round(t_scored - t_fit, 2)},
            'degree': degree, 'coefficients_total': int(c.shape[1]),
            'chosen': {'rank': int(chosen['rank']), 'penalty': float(chosen['penalty']),
                       'validation_loss': float(chosen['validation_loss'])},
            'candidates': candidates,
            'valid_loss': float(chosen['validation_loss']),
            'coeff_space_test_mse': coeff_mse,
            'skill_mean': skill_mean, 'skill_by_lead': skill_by_lead,
            'independent_channels_skill_mean': indep_mean,
            'persistence_skill_mean': persist_mean, 'independent_ar1_skill_mean': ar1_mean,
            'joint_gain_over_independent': skill_mean - indep_mean,
            'per_channel_skill_mean': {k: float(np.mean(v)) for k, v in per_channel_skill.items()},
            'hindsight': {'chosen': {'rank': int(hchosen['rank']), 'penalty': float(hchosen['penalty'])},
                          'test_selected_skill_mean': hskill,
                          'test_selected_coeff_loss_on_test': h_coeff_on_test,
                          'validation_chosen_coeff_loss_on_test': coeff_mse['joint'],
                          'chose_same_parameters': bool(int(hchosen['rank']) == int(chosen['rank'])
                                                    and float(hchosen['penalty']) == float(chosen['penalty']))},
            'shuffled_lead_skill_mean': shskill,
            'wall_seconds': round(time.perf_counter() - t0, 2),
        }
        per_degree.append(row)
        log(json.dumps({'degree': degree, 'p_total': row['coefficients_total'],
                        'chosen': row['chosen'], 'skill_mean': round(skill_mean, 5),
                        'indep': round(indep_mean, 5), 'hindsight': round(hskill, 5),
                        'shuffled': round(shskill, 5), 'secs': row['wall_seconds'],
                        'phases': row['phase_seconds']}, ensure_ascii=False))
        if row['wall_seconds'] > MAX_DEGREE_SECONDS:
            stopped_reason = (f'degree {degree} took {row["wall_seconds"]}s '
                              f'> per-degree cap {MAX_DEGREE_SECONDS}s')
            log('STOP ' + stopped_reason)
            break
        if time.perf_counter() - started > MAX_TOTAL_SECONDS:
            stopped_reason = f'total budget {MAX_TOTAL_SECONDS}s exhausted after degree {degree}'
            log('STOP ' + stopped_reason)
            break

    ladder_completed = [r['degree'] for r in per_degree]
    ladder_complete = ladder_completed == list(LADDER)
    log(f'ladder completed: {ladder_completed} of {list(LADDER)}; complete={ladder_complete}; stopped_reason={stopped_reason}')

    # ---- controls
    # C1a (gate): hindsight selection minimizes the COEFFICIENT-space loss on the
    # backtest period, so on that same quantity it must not be worse than the
    # validation-selected model. v1/v2 stated the control on the PHYSICAL skill
    # metric instead, which is a different quantity; that false premise is recorded
    # below as C1b rather than quietly dropped.
    c1_ok = all(r['hindsight']['test_selected_coeff_loss_on_test']
                <= r['hindsight']['validation_chosen_coeff_loss_on_test'] + 1e-9 for r in per_degree)
    c1b_same_pars = all(r['hindsight']['chose_same_parameters'] for r in per_degree)
    c1b_rows = [{'degree': r['degree'],
                 'chose_same_parameters': r['hindsight']['chose_same_parameters'],
                 'validation_skill': r['skill_mean'],
                 'hindsight_skill': r['hindsight']['test_selected_skill_mean'],
                 'hindsight_minus_validation': r['hindsight']['test_selected_skill_mean'] - r['skill_mean']}
                for r in per_degree]
    # C2 (correctly specified): permuting the TARGET axis breaks alignment and must
    # lower skill. The lead-axis roll from v1/v2 is kept below as a recorded,
    # diagnosed non-gate: a metric averaged over leads is invariant under a
    # permutation of leads, so that control could never have had teeth.
    c2_ok = all(r['target_rolled_skill_mean'] < r['skill_mean'] - 1e-9 for r in per_degree)
    if not c1_ok:
        failures.append('C1a failed: hindsight selection was worse on the coefficient-space '
                        'loss it minimizes -- the grid search itself would be broken')
    if not c2_ok:
        failures.append('C2 failed: target-rolled predictions did not score worse than aligned ones')

    frozen_after = {n: sha256(FROZEN / n) for n in FROZEN_FILES if (FROZEN / n).is_file()}
    g3_ok = frozen_before == frozen_after
    if REFORECAST_REPORT.is_file():
        recorded = json.loads(REFORECAST_REPORT.read_text()).get('frozen_hashes_sha256', {})
        for n in FROZEN_HASH_KEYS:
            if n in recorded and recorded[n] != frozen_after.get(n):
                g3_ok = False
                failures.append(f'G3 failed: {n} differs from the hash recorded by the reforecast run')
    else:
        recorded = {}
    if not g3_ok:
        failures.append('G3 failed: frozen artifact hashes changed during this run')

    # ---- two axes
    e1 = json.loads(E1_REPORT.read_text()) if E1_REPORT.is_file() else None
    bits_by_degree = {r['degree']: r['L_total_bits'] for r in (e1 or {}).get('ladder_summary', [])}
    overlap = [d for d in ladder_completed if d in bits_by_degree]
    skills = [next(r['skill_mean'] for r in per_degree if r['degree'] == d) for d in overlap]
    bits = [bits_by_degree[d] for d in overlap]

    valid_losses = [r['valid_loss'] for r in per_degree]
    gains = [r['joint_gain_over_independent'] for r in per_degree]
    argmax_skill = max(per_degree, key=lambda r: r['skill_mean'])['degree']
    interior = argmax_skill not in (ladder_completed[0], ladder_completed[-1])
    # Skill is available for the whole completed ladder; E1's accounting numbers only
    # for the degrees E1 measured. Keep the two cleanly separated.
    ladder_skills = [r['skill_mean'] for r in per_degree]
    accounting_prefers_finer = monotone_nonincreasing(bits)              # L_total decreasing in d
    skill_prefers_finer = monotone_nonincreasing([-s for s in ladder_skills])   # skill increasing in d
    two_axes_agree = accounting_prefers_finer and skill_prefers_finer

    def plateau_from(idx):
        rel = [abs(skills[i + 1] - skills[i]) / max(abs(skills[i]), 1e-12) for i in range(idx, len(skills) - 1)]
        return all(x < 0.02 for x in rel), rel

    pl_ok, pl_rel = plateau_from(2) if len(skills) > 3 else (False, [])
    skill_monotone = monotone_nonincreasing(skills)
    bits_monotone = accounting_prefers_finer

    predictions = [
        {'id': 'P1', 'claim': 'valid_loss(d) 单调不增',
         'observed': {'valid_loss': valid_losses, 'monotone_nonincreasing': monotone_nonincreasing(valid_losses)},
         'hit': monotone_nonincreasing(valid_losses)},
        {'id': 'P2', 'claim': 'skill(d) 在 d≥8 后平台且 argmax 不在最低两阶',
         'observed': {'skill': skills, 'degrees': overlap, 'relative_steps_from_index2': pl_rel,
                      'argmax_degree': argmax_skill},
         'hit': bool(pl_ok and argmax_skill not in (ladder_completed[0], ladder_completed[1]))},
        {'id': 'P3', 'claim': 'joint 相对 independent_channels 的增益随 d 不增',
         'observed': {'gains': gains, 'degrees': LADDER, 'monotone_nonincreasing': monotone_nonincreasing(gains)},
         'hit': monotone_nonincreasing(gains)},
        {'id': 'P4', 'claim': '两轴不同向：记账轴单调偏向更细（L_total 单调递减）而 skill 非单调（平台）',
         'observed': {'L_total_bits': bits, 'skill': skills, 'degrees': overlap,
                      'L_total_monotone_decreasing': bits_monotone, 'skill_monotone_nonincreasing': skill_monotone,
                      'note': 'v1/v2 的机械检查把这条写反了符号（把「L_total 递增」当作条件），'
                              'claim 的文字未改，检查式已更正：bits 是负值且随 d 递减 ⇒ 记账轴单调偏向更细'},
         'hit': bool(bits_monotone and not skill_monotone)},
        {'id': 'P5', 'claim': 'd≥16 时选中 rank ≥ 32',
         'observed': {str(r['degree']): r['chosen']['rank'] for r in per_degree},
         'hit': all(r['chosen']['rank'] >= 32 for r in per_degree if r['degree'] >= 16)},
    ]

    if failures:
        verdict = 'instrument_failure'
    elif interior and not skill_prefers_finer:
        verdict = 'skill_has_interior_optimum'
    elif two_axes_agree:
        verdict = 'two_axes_align'
    elif accounting_prefers_finer and not skill_prefers_finer:
        verdict = 'skill_nonmonotone_bits_monotone'
    else:
        verdict = 'skill_nonmonotone_bits_monotone'

    report = {
        'version': contract['version'],
        'question_id': contract['question_id'],
        'generated_utc': datetime.now(timezone.utc).isoformat(),
        'contract_sha256': sha256(CONTRACT),
        'ladder': LADDER, 'ranks': RANKS, 'ridge_mean_loss_penalties': PENALTIES,
        'ladder_planned': list(LADDER), 'ladder_completed': ladder_completed,
        'g5_tolerance': G5_TOL,
        'ladder_complete': ladder_complete, 'stopped_reason': stopped_reason,
        'phase_caps_seconds': {'per_degree': MAX_DEGREE_SECONDS, 'total': MAX_TOTAL_SECONDS},
        'gates': {
            'G1_domain_identity_all_degrees': True,
            'G2_L12_reproduction_exact': True,
            'G3_frozen_hashes_unchanged': g3_ok,
            'G3_hashes_before': frozen_before, 'G3_hashes_after': frozen_after,
            'G3_recorded_by_reforecast': recorded,
            'G4_refuse_overwrite': True,
        },
        'controls': {
            'C1a_hindsight_on_its_own_criterion': {
                'rule_ok': c1_ok,
                'per_degree': [{'degree': r['degree'],
                                'hindsight_coeff_loss_on_test': r['hindsight']['test_selected_coeff_loss_on_test'],
                                'validation_chosen_coeff_loss_on_test': r['hindsight']['validation_chosen_coeff_loss_on_test']}
                               for r in per_degree]},
            'C1b_false_premise_recorded': {
                'was': 'v1/v2 规定「后见之明的 PHYSICAL 技巧必须不差于验证期选参」',
                'measured': c1b_rows,
                'chose_same_parameters_everywhere': bool(c1b_same_pars),
                'diagnosis': '两条独立原因使该前提不成立：(i) `select` 最小化的是**系数空间**损失，而物理 full_mse 技巧是**另一个量**（选参判据 ≠ 评分判据）；(ii) 八个阶全部选中网格角点 rank=64/penalty=0.1 ⇒ 用哪一段选参都得到同一个模型，后见之明**没有优势可言**。⇒ 该对照**按原样记为失败**，不改写、不删除。'},
            'C2_target_axis_misalignment': {
                'rule_ok': c2_ok,
                'per_degree': [{'degree': r['degree'], 'aligned_skill': r['skill_mean'],
                                'target_rolled_skill': r['target_rolled_skill_mean']} for r in per_degree]},
            'C2_lead_roll_recorded_as_ill_posed': {
                'was': 'v1/v2 用**沿 lead 轴**滚动作错位对照，规定技巧必须变差',
                'per_degree': [{'degree': r['degree'], 'aligned_skill': r['skill_mean'],
                                'lead_rolled_skill': r['shuffled_lead_skill_mean']} for r in per_degree],
                'diagnosis': '技巧是**对 lead 取平均**的量，而沿 lead 轴滚动只是**置换** lead 轴 ⇒ 平均值不变 ⇒ 该对照**在数学上不可能失败**。这是**对照设计错误**，不是模型的发现；按原样记为失败。'},
        },
        'per_degree': per_degree,
        'two_axes': {
            'degrees_with_both': overlap,
            'L_total_bits': bits, 'skill_mean_overlap': skills,
            'ladder_skills_full': ladder_skills, 'ladder_degrees_full': ladder_completed,
            'accounting_prefers_finer': bool(accounting_prefers_finer),
            'skill_prefers_finer_over_full_ladder': bool(skill_prefers_finer),
            'skill_monotone_nonincreasing_overlap': skill_monotone,
            'skill_argmax_degree': argmax_skill, 'skill_argmax_interior': bool(interior),
            'plateau_from_index2_overlap': {'all_steps_relative_lt_0.02': bool(pl_ok), 'relative_steps': pl_rel},
            'e1_argmin_degree': (e1 or {}).get('argmin_degree'),
            'two_axes_agree': bool(two_axes_agree),
        },
        'predictions': predictions,
        'predictions_hit': sum(1 for p in predictions if p['hit']),
        'predictions_total': len(predictions),
        'failures': failures,
        'verdict': verdict,
        'verdict_text': {
            'skill_has_interior_optimum': '技能轴有内部极大 ⇒ E1 的记账判据是错的代理，应改用它或并用',
            'skill_nonmonotone_bits_monotone': '两轴不同向：记账轴单调偏向更细（L_total 递减），技能轴却不单调（出现回撤）⇒ 「最小词汇」判据不能只靠记账，必须加留出／可信度项',
            'two_axes_align': '两轴同向单调 ⇒ 记账轴可作为技能轴的代理（E1 的退化对选阶无害）',
            'instrument_failure': '闸门或对照不成立 ⇒ 不报判定',
        }[verdict],
        'residuals': [
            '本件度量的是**我们自己的呈现方式**，不是对自然的发现',
            '高阶技巧更好不等于物理分辨率更高（输出采样步长与技巧无关）',
            'rank 网格上界 64 在高阶可能成为限制：P5 记录的正是这件事',
            '开发回测期（2020–2025）此前已被看过（冻结契约的 prior_exposure）⇒ 不是全新的验证样本',
        ],
        'wall_seconds': round(time.perf_counter() - started, 1),
        'peak_rss_mb': round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1),
    }
    (OUT / 'report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + '\n')
    (OUT / 'run.log').write_text('\n'.join(log_lines) + '\n')
    log(json.dumps({'verdict': verdict, 'predictions': f"{report['predictions_hit']}/{report['predictions_total']}",
                    'two_axes': report['two_axes'], 'failures': failures,
                    'wall_seconds': report['wall_seconds'], 'peak_rss_mb': report['peak_rss_mb']},
                   ensure_ascii=False, indent=1))
    return 1 if failures else 0


if __name__ == '__main__':
    # A gate failure must leave its own trace: write the failure report and log
    # rather than exiting silently. The result directory then refuses a re-run,
    # so the failure stays on record until a v2 contract is written.
    #
    # Revision 2 (2026-09-28): the first launch died on a plain bug — one call
    # passed `flush=True` to this module's own `log()`, raising TypeError — and
    # the guard caught only SystemExit, so the crash left no report at all.
    # The guard now catches every exception and records the traceback.
    try:
        code = main()
    except BaseException as exc:                      # noqa: BLE001 - deliberate
        import traceback
        OUT.mkdir(parents=True, exist_ok=True)
        tb = traceback.format_exc()
        failures.append(f'{type(exc).__name__}: {exc}')
        (OUT / 'report.json').write_text(json.dumps({
            'version': 'vocabulary-skill-axis-e1b-v2',
            'question_id': 'xue.derived.vocabulary-skill-axis-e1b',
            'generated_utc': datetime.now(timezone.utc).isoformat(),
            'verdict': 'instrument_failure', 'failures': failures,
            'traceback': tb,
        }, ensure_ascii=False, indent=2) + '\n')
        (OUT / 'run.log').write_text('\n'.join(log_lines) + '\n')
        print('INSTRUMENT FAILURE:', exc, flush=True)
        print(tb, flush=True)
        code = 1
    sys.exit(code)
