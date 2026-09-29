"""读冻结的 report.json，重算三件被「检查式 bug」影响的事——**不改 report.json**。

本脚本存在的原因（跑完才发现，如实登记）：
  ① `run_caliber.py` 的 G3 闸门把单位换算写反了：E1 的残差是**原始单位**的加权 SSE，
     本件的残差是**归一单位**（除以本通道训练期标准差）。正确关系是
     `E1_raw ≈ mine × sigma²`，而闸门写成了 `want = E1_raw × sigma²` 去比 mine
     ⇒ 78/78 全部「不一致」。数字其实一致（t850 d=4：0.0452352 × 117.6 = 5.3196 = E1 的
     5.3192337），错的是检查式。本脚本按正确方向重算。
  ② 预测 P1 的检查式拿元组比整数（`argmin_rung == 16`，而它是 `[16, 0]`）⇒ 必定判「假」。
     本脚本按同一批读数重算，并把脚本原判与重算判并列写出。
  ③ C-4 的读数表需要逐条摊开看（哪些不变、哪些是退化读数、哪些不完整），
     单看计数不足以判断判据成立与否。

写 summary.json（拒绝覆盖）。
"""
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ROUND = REPO / 'archive/caliber-invariance-v1'
E1_REPORT = REPO / 'archive/vocabulary-accounting-e1-v1/report.json'
GRID = ['A-native', 'B-2p5', 'C-5', 'D-10']
D_LADDER = [4, 6, 8, 10, 12, 16]
THETA = [0, 5, 10, 20, 50, 100, 200]


def judge_curve(curve):
    """与 run_caliber.judge 同一判定：全局 argmin 是否落在阶梯内部。"""
    vals = [v for _, v in curve]
    if not vals:
        return {'argmin_rung': None, 'interior': None, 'endpoint_optimum': None}
    idx = min(range(len(vals)), key=lambda i: vals[i])
    return {'argmin_rung': list(curve[idx][0]), 'argmin_index': idx,
            'interior': bool(0 < idx < len(vals) - 1),
            'endpoint_optimum': bool(idx in (0, len(vals) - 1)),
            'value_at_argmin': float(vals[idx]),
            'margin_to_best_endpoint': float(min(vals[0], vals[-1]) - vals[idx])}


def main():
    out_path = ROUND / 'summary.json'
    if out_path.exists():
        raise FileExistsError(out_path)
    d = json.loads((ROUND / 'report.json').read_text())
    rows = d['rows']
    e1 = json.loads(E1_REPORT.read_text())
    ref = {(r['degree'], r['channel']): r for r in e1['per_channel']}

    # ---- ① G3 重算：E1_raw 对 mine × sigma²
    g3 = {'checked': 0, 'mismatch': [], 'max_relative_difference': 0.0,
          'max_relative_where': None, 'masks_all_identical': True}
    for r in rows:
        if r['caliber'] != 'A-native' or r['ladder'] != 'P1' or r['theta_hpa'] != 0:
            continue
        a = ref.get((r['degree'], r['channel']))
        if a is None:
            continue
        g3['checked'] += 1
        mine_raw = r['residual_mean'] * r['sigma'] ** 2
        want = a['residual_mean']
        rel = abs(mine_raw - want) / max(abs(want), 1e-300)
        if rel > g3['max_relative_difference']:
            g3['max_relative_difference'] = rel
            g3['max_relative_where'] = [r['degree'], r['channel'], want, mine_raw]
        if rel > 1e-6:
            g3['mismatch'].append([r['degree'], r['channel'], want, mine_raw, rel])
        same_masks = (a['observation_quotient_groups'] == r['n_distinct_domains']
                      and abs(a['min_area_fraction'] - r['min_area_fraction']) <= 1e-12
                      and abs(a['max_gram_condition'] - r['max_gram_condition'])
                      <= 1e-9 * a['max_gram_condition'])
        if not same_masks:
            g3['masks_all_identical'] = False
    g3['holds_recomputed'] = bool(not g3['mismatch'] and g3['checked'] == 78
                                  and g3['masks_all_identical'])
    g3['tolerance_relative'] = 1e-6
    g3['original_gate_verdict'] = d['gates']['G3']

    # ---- ② 预测重算
    def p2judge(cal):
        return d['judge_detail'][cal]['P2']

    def p2njudge(cal):
        return d['judge_detail'][cal]['P2_without_null']

    argmin_d = {c: d['judge_detail'][c]['P1']['argmin_rung'] for c in GRID}
    argmin_t = {c: p2judge(c)['argmin_rung'] for c in GRID}
    interior_t = {c: p2judge(c)['interior'] for c in GRID}
    argmin_t_none = {c: p2njudge(c)['argmin_rung'] for c in GRID}
    nq_a = d['object_readings']['A-native']['nq_at_d12']
    nq_b = d['object_readings']['B-2p5']['nq_at_d12']
    on_2p5 = [k for k in nq_a if k not in ('sp', 't2m', 'sst')]
    cross = d['cross_source_2026_02']['by_caliber']
    worst_flip = max(v['flip_fraction'] for e in cross.values() for v in e['levels'].values())
    preds = [
        ('P1', all(not d['judge_detail'][c]['P1']['interior'] for c in GRID)
         and all(argmin_d[c] == [D_LADDER[-1], 0] for c in GRID),
         '矩阵阶梯：四口径都无内部最优且 argmin 落在 d=16 端点'),
        ('P2', sum(1 for c in GRID if interior_t[c]) >= 3,
         '原生 θ 阶梯：≥3 个口径有内部最优'),
        ('P3', len({tuple(argmin_t[c]) for c in GRID}) > 1, 'θ* 的位置随口径变'),
        ('P4', all(argmin_t_none[c][1] == THETA[-1] for c in GRID),
         '副账（不含被排除格点计费）应单调偏向小域 ⇒ argmin 落在 θ=200'),
        ('P5', any(f.get('caliber') == 'D-10' for f in d['failures']), '最粗口径有失败记录'),
        ('P6', worst_flip < 0.02, '§D 的筛选翻转比例 < 2%'),
        ('P7', all(nq_a[k] == nq_b[k] for k in on_2p5)
         and any(nq_a[k] != nq_b[k] for k in ('sp', 't2m', 'sst')),
         'A 与 B 的 2.5° 通道 N_Q 相同、T62/ERSST 通道不同'),
    ]
    recorded = {i['id']: i['hit'] for i in d['predictions']['items']}
    predictions = [{'id': i, 'hit_recomputed': bool(v), 'hit_as_recorded': recorded.get(i),
                    'note': n} for i, v, n in preds]
    predictions_fixed = sum(1 for p in predictions if p['hit_recomputed'])

    # ---- ③ C-4 逐条摊开（**并修正退化标记**：run_caliber.py 里把 [16,0] 与 16 相比，
    #      端点最优因此漏标；那正是 P1 检查式同型的 bug）
    c4 = d['C4']
    table = {}
    for grp in ('object', 'matrix', 'native'):
        table[grp] = {}
        for nm, v in c4[grp].items():
            vals = v['values']
            first = list(vals.values())[0]
            deg_corrected = v.get('degenerate', False)
            if isinstance(first, list) and len(first) == 2:        # 档位 [rung, theta]
                deg_corrected = all(list(vals[c])[0] in (D_LADDER[-1], D_LADDER[0])
                                    for c in GRID) if nm.startswith('argmin_degree') else \
                    all(list(vals[c])[1] in (THETA[0], THETA[-1]) for c in GRID)
            if isinstance(first, dict):
                diff_keys = sorted({k for c in GRID for k in vals[c]
                                    if vals[c][k] != vals[GRID[0]][k]})
                show = {'differing_channels': diff_keys} if diff_keys else {'identical': True}
            elif isinstance(first, list):
                show = {'curves': {c: vals[c] for c in GRID}}
            else:
                show = {'values': vals}
            table[grp][nm] = {'invariant': v['invariant'], 'kind': v['kind'],
                              'degenerate_recorded': v.get('degenerate', False),
                              'degenerate_corrected': bool(deg_corrected),
                              'incomplete': v.get('incomplete', False), **show}
    counts = c4['counts']
    counts_corrected = {}
    for grp in ('object', 'matrix', 'native'):
        items = table[grp]
        counts_corrected[grp] = {
            'readings': len(items),
            'invariant_total': sum(1 for v in items.values() if v['invariant']),
            'degenerate_recorded': sum(1 for v in items.values() if v['degenerate_recorded']),
            'degenerate_corrected': sum(1 for v in items.values() if v['degenerate_corrected']),
            'invariant_non_degenerate_corrected':
                sum(1 for v in items.values()
                    if v['invariant'] and not v['degenerate_corrected'])}
    nat = counts_corrected['native']['invariant_non_degenerate_corrected']
    mat = counts_corrected['matrix']['invariant_non_degenerate_corrected']
    verdict_corrected = {'rule': '原生非退化不变数 ≥ 矩阵非退化不变数 ＋ 1',
                         'native_non_degenerate_invariant': nat,
                         'matrix_non_degenerate_invariant': mat,
                         'holds': bool(nat >= mat + 1)}
    def vals_of(grp, nm):
        e = table[grp][nm]
        return e.get('values') or e.get('curves')

    decision = {
        'matrix_decision_reading': {'name': 'argmin_degree',
                                    'values': vals_of('matrix', 'argmin_degree'),
                                    'invariant': table['matrix']['argmin_degree']['invariant'],
                                    'degenerate': True,
                                    'note': '四口径都取端点 d=16 ⇒ 不变，但没有判别力'},
        'native_decision_reading': {'name': 'argmin_theta',
                                    'values': vals_of('native', 'argmin_theta'),
                                    'invariant': table['native']['argmin_theta']['invariant'],
                                    'degenerate': False,
                                    'note': 'θ* 随口径移动 ⇒ 有判别力，但对口径不稳'},
        'reading': ('在**决策读数**上：矩阵方法不变但退化（永远取端点），原生方法有判别力但不稳'
                    '（0/0/10/50）。⇒ C-4 在本轮数据上判的不是「谁更强」，而是'
                    '「谁更不需要做选择」。'),
    }

    # ---- ④ 精化单调性为什么是 false：把残差与系数两条分账分开看
    refine = {}
    for cal in d['per_caliber']:
        cs = d['per_caliber'][cal]['curve_scope']['P1_channels']
        resid, coeff = [], []
        for deg in D_LADDER:
            rr = [r for r in rows if r['caliber'] == cal and r['ladder'] == 'P1'
                  and r['degree'] == deg and r['theta_hpa'] == 0 and r['channel'] in cs]
            resid.append(sum(r['bits']['train']['resid_bits'] + r['bits']['valid']['resid_bits']
                             for r in rr))
            coeff.append(sum(r['bits']['train']['coeff_bits'] + r['bits']['valid']['coeff_bits']
                             for r in rr))
        refine[cal] = {
            'resid_bits_sel': [round(v, 1) for v in resid],
            'coeff_bits_sel': [round(v, 1) for v in coeff],
            'resid_strictly_decreasing': bool(all(b < a for a, b in zip(resid, resid[1:]))),
            'coeff_strictly_increasing': bool(all(b > a for a, b in zip(coeff, coeff[1:]))),
            'channels': len(cs)}

    # ---- ⑥ 四种账目下的同一批阶梯（C-1 的判定是否随「账怎么记」而变）
    #   账A（本轮主账）＝ 每月系数高斯码长 ＋ 归一残差 ＋ 无免费格点 ＋ 域描述位
    #   账B（副账）    ＝ 同 A，但不含「被排除格点的气候态计费」
    #   账C（E1 结构、单位归一）＝ 共享词汇表 p×64（只付一次）＋ 归一残差 ＋ 无免费格点
    #   账D（全账）    ＝ 共享词汇表 ＋ 每月系数高斯码长 ＋ 归一残差 ＋ 无免费格点
    # 契约只写死「改掉 E1 的每系数 64 位」这一处；C／D 是跑完后补的两本对照账——
    # 「共享词汇表要不要再计一次」是一个**未声明的自由选择**，必须让它可见。
    accounts = {}
    for cal in d['per_caliber']:
        chans_of = {'P1': d['per_caliber'][cal]['curve_scope']['P1_channels'],
                    'P2': d['per_caliber'][cal]['curve_scope']['P2_channels']}
        curves = {k: [] for k in ('A', 'B', 'C', 'D')}
        p1_rungs, p2_rungs = [], []
        for ladder, rungs in (('P1', [(deg, 0) for deg in D_LADDER]),
                              ('P2', [(12, t) for t in THETA])):
            chans = chans_of[ladder]      # P1 与 P2 的共同通道集不同（θ=200 掉 3 条）
            for rung in rungs:
                rr = [r for r in rows if r['caliber'] == cal and r['ladder'] == ladder
                      and r['degree'] == rung[0] and r['theta_hpa'] == rung[1]
                      and r['channel'] in chans]
                if len(rr) != len(chans):
                    continue
                coeff = sum(r['bits']['train']['coeff_bits'] + r['bits']['valid']['coeff_bits']
                            for r in rr)
                resid = sum(r['bits']['train']['resid_bits'] + r['bits']['valid']['resid_bits']
                            for r in rr)
                null = sum(r['null_bits']['train'] + r['null_bits']['valid'] for r in rr)
                dom = sum(r['domain_bits'] for r in rr)
                shared = sum(r['coefficients'] for r in rr) * 64.0
                vals = {'A': coeff + resid + null + dom,
                        'B': coeff + resid + dom,
                        'C': shared + resid + null + dom,
                        'D': shared + coeff + resid + null + dom}
                for k, v in vals.items():
                    curves[k].append((rung, v))
                (p1_rungs if ladder == 'P1' else p2_rungs).append(rung)
        entry = {}
        for k in ('A', 'B', 'C', 'D'):
            cut = len(p1_rungs)
            entry[k] = {'P1': judge_curve(curves[k][:cut]),
                        'P2': judge_curve(curves[k][cut:]),
                        'P1_curve': [[r0, round(v, 1)] for r0, v in curves[k][:cut]],
                        'P2_curve': [[r0, round(v, 1)] for r0, v in curves[k][cut:]]}
        entry['coefficients_total_by_degree'] = {
            str(deg): sum(r['coefficients'] for r in rows
                          if r['caliber'] == cal and r['ladder'] == 'P1' and r['degree'] == deg
                          and r['theta_hpa'] == 0
                          and r['channel'] in chans_of['P1'])
            for deg in D_LADDER}
        accounts[cal] = entry

    # ---- ⑤ θ 曲线的局部极小（全局 argmin 在端点时，局部极小仍值得知道）
    local_min = {}
    for cal in d['per_caliber']:
        cur = [v for _, v in d['judge_detail'][cal]['P2']['curve']]
        rungs = [r for r, _ in d['judge_detail'][cal]['P2']['curve']]
        idx = [i for i in range(1, len(cur) - 1)
               if cur[i] < cur[i - 1] and cur[i] < cur[i + 1]]
        local_min[cal] = {'global_argmin_theta': rungs[int(min(range(len(cur)),
                                                              key=lambda i: cur[i]))][1],
                          'local_min_theta': [rungs[i][1] for i in idx]}

    summary = {
        'version': 'caliber-invariance-v1',
        'wall_seconds': d['wall_seconds'], 'peak_rss_mb': d['peak_rss_mb'],
        'failures_total': len(d['failures']),
        'failure_kinds': sorted({(f.get('caliber'), f.get('channel'), f.get('theta_hpa'),
                                  f.get('error')) for f in d['failures']}),
        'channel_coverage': d['channel_coverage'],
        'global_channels': d['global_channels'],
        'G3_recomputed': g3,
        'predictions_recomputed': predictions,
        'predictions_hit_recomputed': predictions_fixed,
        'predictions_hit_as_recorded': sum(1 for v in recorded.values() if v),
        'C4_table': table, 'C4_counts_as_recorded': counts,
        'C4_counts_corrected': counts_corrected,
        'C4_verdict_as_recorded': c4['C4_verdict'],
        'C4_verdict_corrected': verdict_corrected,
        'C4_decision_readings': decision,
        'refine_monotonicity_detail': refine,
        'theta_local_minima': local_min,
        'accounts': accounts,
        'C1': d['C1'],
        'curves': {c: {k: [[rr, round(vv, 1)] for rr, vv in d['judge_detail'][c][k]['curve']]
                       for k in ('P1', 'P2', 'P1_without_null', 'P2_without_null')}
                   for c in d['judge_detail']},
        'nq_theta_curve': {c: d['per_caliber'][c]['native']['nq_theta_curve'] for c in GRID},
        'cross_source': {c: {'grid': e['grid'],
                             'flips': {L: e['levels'][L]['flips'] for L in e['levels']},
                             'flip_fraction_max': max(v['flip_fraction']
                                                      for v in e['levels'].values()),
                             'sst_mean_diff_K': e['sst']['mean_diff_K'],
                             'sst_median_abs_diff_K': e['sst']['median_abs_diff_K']}
                         for c, e in cross.items()},
        'cross_source_units': d['cross_source_2026_02']['units'],
        'gate_verdicts_as_recorded': {k: v['holds'] for k, v in d['gates'].items()},
    }
    out_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=False) + '\n')
    print(json.dumps({'G3_recomputed_holds': g3['holds_recomputed'],
                      'G3_max_relative': g3['max_relative_difference'],
                      'G3_mismatch_count': len(g3['mismatch']),
                      'masks_all_identical': g3['masks_all_identical'],
                      'predictions_hit_recomputed': predictions_fixed,
                      'predictions_hit_as_recorded': summary['predictions_hit_as_recorded'],
                      'C4_verdict_corrected': verdict_corrected,
                      'counts_as_recorded': counts,
                      'counts_corrected': counts_corrected}, ensure_ascii=False, indent=1))
    print('决策读数：', json.dumps(decision, ensure_ascii=False))
    print('精化单调性：', json.dumps(refine, ensure_ascii=False))
    print('θ 局部极小：', json.dumps(local_min, ensure_ascii=False))
    print('=== 四种账目下的 argmin（P1 阶 / P2 θ）===')
    for cal, e in accounts.items():
        row = {k: (e[k]['P1']['argmin_rung'], e[k]['P1']['interior'],
                   e[k]['P2']['argmin_rung'], e[k]['P2']['interior']) for k in ('A', 'B', 'C', 'D')}
        print(' ', cal, json.dumps(row, ensure_ascii=False))
    print(f'写出 {out_path}')


if __name__ == '__main__':
    main()
