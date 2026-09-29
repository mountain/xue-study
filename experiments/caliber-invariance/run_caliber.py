"""C-1 ＋ C-4：同一批物理场、多种口径、两种呈现。

判据（提问方 2026-09-28 裁定采用，见 docs/lifecycle/README.md §5）：
  C-1 非退化    —— 选阶判据必须有**内部最优**，且该最优对口径扰动稳健
  C-4 口径不变量 —— 在 4 种网格口径上重做，原生方法的**不变读数显著多于**矩阵方法

两种呈现：
  P1 矩阵（参考方法）：球谐截断阶 d 的度量阶梯，域用冻结口径的硬阈值（θ=0）
  P2 原生对象：观测商（月份按相同有效掩膜分组），自由参数是**可分辨性的粗细** θ

相对 E1 的三处修正（事先写死，且主／副两本账并列）：
  ① 单位归一：每通道除以它自己在训练期、θ=0 域上的加权标准差（向量通道用两分量合成
     标准差，以免破坏 `masked_project` 的联合向量解）⇒ 系数码长按高斯码长
     0.5·log2(2πe·c²) 计，不再用 E1 的「每系数 64 位」。
  ② 留出项：选择判据只用训练（1979-01…2014-12）＋验证（2015-01…2019-12）；
     尾部 2020-01…2025-12 只报不选（冻结模型的回测期因此不被用于选择）。
  ③ 无免费格点：训练期可表示而被域排除的格点，按其自身气候态码长逐月计费。
     没有这一项，判据必然偏向「域越小越好」——与 E1 的退化结构同类。

只读；写 archive/caliber-invariance-v1/report.json（拒绝覆盖）。
"""
import hashlib
import json
import math
import resource
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
REFINE = REPO / 'experiments/multivariate-refinement'
FEAS = REPO / 'experiments/era5-sp-sst-feasibility'
for _p in (REFINE, REFINE.parent / 'typed-spectrum', FEAS):
    sys.path.insert(0, str(_p))

import fields                                                              # noqa: E402
from project import (area_weights, geometry, interpolate_surface_pressure,  # noqa: E402
                     load_field, masked_project)
from spectrum import SphereBasis, latlon_points                            # noqa: E402
from probe_era5 import cell_edges, overlap_1d, regrid_conservative         # noqa: E402

OUT = REPO / 'archive/caliber-invariance-v1'
E1_REPORT = REPO / 'archive/vocabulary-accounting-e1-v1/report.json'
FROZEN = REPO / 'archive/multivariate-l12-v1'
INPUTS_EXT = Path('/home/ubuntu/climatetensor-inputs/ncep-multivariate-ext-202602')
ERA5_MONTH = Path('/home/ubuntu/xue-assimilation/monthly/era5/2026-02')

D_LADDER = [4, 6, 8, 10, 12, 16]
SHIPPED_D = 12
THETA_LADDER = [0, 5, 10, 20, 50, 100, 200]        # hPa 增量，加在 level×100 之上
TRAIN_END, VALID_END = '2014-12', '2019-12'
LOG2_2PIE = math.log2(2 * math.pi * math.e)
SP_RANGE = (4.5e4, 1.1e5)                          # 量级闸门（E1 更正后的下界）
AREA_TOL = 5e-2                                    # G6
INVARIANCE_RTOL = 1e-3                             # 读数不变性的相对容差
REGRID_RTOL = 1e-12                                # G2② 的末位容差

CALIBERS = [                                       # 口径：网格 × 度量
    ('A-native', None),                            # 各通道自己的原生网格 = 出货口径 = E1 口径
    ('B-2p5', (2.5, 87.5, 144)),
    ('C-5', (5.0, 87.5, 72)),
    ('D-10', (10.0, 85.0, 36)),
    ('M-2p5-uniform', (2.5, 87.5, 144)),           # 度量扰动：同网格、均匀权重
]
GRID_CALIBERS = ['A-native', 'B-2p5', 'C-5', 'D-10']


def log(msg):
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def make_grid(step, lat0, nlon):
    nlat = int(round(2 * lat0 / step)) + 1
    return lat0 - step * np.arange(nlat), np.arange(nlon) * (360.0 / nlon)


def conservative_stack(y, src_lat, src_lon, dst_lat, dst_lon):
    """`regrid_conservative` 的整条时间序列版本：权重只算一次，翻转逻辑逐字照抄。

    翻纬必须还原——E1 的 C2a 抓到的正是「结果没还原」这个 bug（恒等重网格把场按纬度
    翻转，最大改动 52568 Pa）。本函数由 G2 的两条自检兜住：恒等必须为 0，且必须与
    `regrid_conservative` 的单月调用一致。
    """
    src_lat, dst_lat = np.asarray(src_lat, float), np.asarray(dst_lat, float)
    src_lon, dst_lon = np.asarray(src_lon, float), np.asarray(dst_lon, float)
    a = np.asarray(y, float)
    fs_lat, fd_lat = src_lat[0] > src_lat[-1], dst_lat[0] > dst_lat[-1]
    fs_lon, fd_lon = src_lon[0] > src_lon[-1], dst_lon[0] > dst_lon[-1]
    if fs_lat:
        a = a[:, ::-1, :]
    if fs_lon:
        a = a[:, :, ::-1]
    wlat = overlap_1d(cell_edges(src_lat, True), cell_edges(dst_lat, True), True)
    wlon = overlap_1d(cell_edges(src_lon, False), cell_edges(dst_lon, False), False)
    good = np.isfinite(a)
    num = np.matmul(np.matmul(wlat, np.where(good, a, 0.0)), wlon.T)
    den = np.matmul(np.matmul(wlat, good.astype(float)), wlon.T)
    with np.errstate(invalid='ignore', divide='ignore'):
        out = np.where(den > 0, num / den, np.nan)
    if fd_lat:
        out = out[:, ::-1, :]
    if fd_lon:
        out = out[:, :, ::-1]
    return out


def basis_for(lat, lon, degree, uniform):
    """球谐基与面积权重。uniform=True 走度量口径 M（不用 sin(lat)）。"""
    lat = np.asarray(lat, float)
    lon = np.asarray(lon, float)
    b = SphereBasis(latlon_points(lat, lon), degree)
    if uniform:
        n = lat.size * lon.size
        return b, np.full(n, 1.0 / n)
    _, w = geometry(tuple(lat), tuple(lon), degree)
    return b, w


def channel_stack(ch, cal, cache):
    """把一条通道搬到目标口径上；返回 (y(T,ncells,ncomp), lat, lon)。"""
    codes = ch['fields']
    dates = cache[codes[0]][3]
    if cal is None:
        lat, lon = cache[codes[0]][1], cache[codes[0]][2]
        planes = [cache[c][0] for c in codes]
    else:
        clat, clon = cal
        planes = []
        for code in codes:
            values, lat, lon, _ = cache[code]
            if values.shape[1:] == (clat.size, clon.size) and \
                    np.array_equal(lat, clat) and np.array_equal(lon, clon):
                planes.append(values)
            else:
                planes.append(conservative_stack(values, lat, lon, clat, clon))
        lat, lon = clat, clon
    y = np.stack([v.reshape(len(dates), -1) for v in planes], axis=2)
    return y, lat, lon


def caliber_pressure(cal, cache):
    """层压筛选用的地面气压，搬到本口径上（A 口径改用逐通道插值，见 run_ladder）。"""
    values, lat, lon, _ = cache['sp']
    if cal is None:
        return None
    clat, clon = cal
    if values.shape[1:] == (clat.size, clon.size) and \
            np.array_equal(lat, clat) and np.array_equal(lon, clon):
        grid = values
    else:
        grid = conservative_stack(values, lat, lon, clat, clon)
    return grid.reshape(grid.shape[0], -1)


def masks_for(y, pressure, level, theta_hpa, train_idx):
    """E1 的掩膜构造，外加可分辨性阈值 θ（hPa）。"""
    ntime, ncells, _ = y.shape
    fin = np.isfinite(y).all(axis=2)
    fixed = fin[train_idx].all(axis=0)
    if level is None:
        masks = np.broadcast_to(fixed, (ntime, ncells)).copy()
        domain = fixed
    else:
        thr = level * 100.0 + theta_hpa * 100.0
        domain = fixed & (pressure[train_idx].min(axis=0) >= thr)
        masks = domain[None, :] & fin & (pressure >= thr)
    return fixed, masks, domain


def channel_scale(y, weights, domain, train_idx, masks_train):
    """训练期、θ=0 域上的加权标准差（向量通道用两分量的合成标准差）。"""
    w = weights * domain
    if w.sum() <= 0:
        return float('nan')
    block = y[train_idx]
    fin = masks_train[train_idx]
    tot = 0.0
    for c in range(y.shape[2]):
        b = block[:, :, c]
        ww = np.where(fin, w[None, :], 0.0)
        den = ww.sum()
        if den <= 0:
            continue
        mean = float((np.where(fin, b, 0.0) * ww).sum() / den)
        tot += float((np.where(fin, (b - mean) ** 2, 0.0) * ww).sum() / den)
    return math.sqrt(tot / y.shape[2])


def split_indices(dates):
    return (np.where(dates <= TRAIN_END)[0],
            np.where((dates > TRAIN_END) & (dates <= VALID_END))[0],
            np.where(dates > VALID_END)[0])


def code_bits(coeff, n_obs, residual, splits):
    """三段码长：系数（高斯码长，场已归一）＋残差（高斯码长，已归一）。"""
    coeff_bits = 0.5 * np.log2(2 * math.pi * math.e * np.maximum(coeff ** 2, 1e-300))
    out = {}
    for name, idx in splits.items():
        if idx.size == 0:
            out[name] = {'coeff_bits': 0.0, 'resid_bits': 0.0, 'obs': 0.0}
            continue
        n = n_obs[idx]
        sigma2 = np.maximum(np.where(n > 0, residual[idx] / np.maximum(n, 1), 1.0), 1e-300)
        out[name] = {'coeff_bits': float(coeff_bits[idx].sum()),
                     'resid_bits': float((0.5 * n * (LOG2_2PIE + np.log2(sigma2))).sum()),
                     'obs': float(n.sum())}
    return out


def null_bits(fixed, domain, ncomp, splits):
    """被域排除但训练期可表示的格点：按自身气候态码长计费（单位归一后是常数）。"""
    n_excl = int((fixed & ~domain).sum()) * ncomp
    return {name: 0.5 * LOG2_2PIE * n_excl * idx.size for name, idx in splits.items()}, n_excl


def project_one(y, masks, degree, uniform, lat, lon):
    basis, w = basis_for(lat, lon, degree, uniform)
    matrix = basis.vector if y.shape[2] == 2 else basis.scalar[:, None, :]
    coeff, _bank, index, residual, diag = masked_project(matrix, y, w, masks)
    return coeff, index, residual, diag, int(matrix.shape[-1])


def digest(index):
    """月份划分的规范形（对类标签重命名不变）。"""
    order = np.argsort(index, kind='stable')
    _, inv = np.unique(index[order], return_inverse=True)
    canon = np.empty_like(inv)
    canon[order] = inv
    return canon.tolist()


def row_for(cal_name, ch, name, ladder, degree, theta, masks, fixed, domain, y, yn, sigma,
            uniform, lat, lon, dates, splits, failures):
    try:
        coeff, index, residual, diag, p = project_one(yn, masks, degree, uniform, lat, lon)
    except Exception as exc:
        failures.append({'caliber': cal_name, 'channel': name, 'ladder': ladder,
                         'degree': degree, 'theta_hpa': theta,
                         'error': f'{type(exc).__name__}: {exc}'})
        return None
    ncomp = y.shape[2]
    n_obs = masks.sum(axis=1) * ncomp
    bits = code_bits(coeff, n_obs, residual, splits)
    nbits, n_excl = null_bits(fixed, domain, ncomp, splits)
    return {'caliber': cal_name, 'channel': name, 'level': ch['level'], 'ladder': ladder,
            'degree': degree, 'theta_hpa': theta, 'coefficients': p, 'components': ncomp,
            'cells': int(y.shape[1]), 'months': int(y.shape[0]),
            'n_distinct_domains': int(diag['distinct_domains']),
            'max_gram_condition': float(diag['max_gram_condition']),
            'min_area_fraction': float(diag['min_area_fraction']),
            'residual_mean': float(np.mean(residual)),
            'excluded_cells': int(n_excl), 'domain_cells': float(domain.sum() * ncomp),
            'bits': bits, 'null_bits': nbits,
            'domain_bits': float(domain.sum() * ncomp),
            'index_digest': (digest(index) if (ladder == 'P1' and degree == SHIPPED_D
                                               and theta == 0)
                             else hashlib.sha1(np.asarray(digest(index),
                                                          dtype=np.int64).tobytes()
                                               ).hexdigest()[:16]),
            'sigma': float(sigma), 'dates': (str(dates[0]), str(dates[-1]))}


def run_caliber(cal_name, cal, cache, failures):
    """跑一个口径的全部阶梯：P1（阶）与 P2（可分辨性阈值，阶固定为出货阶）。"""
    uniform = cal_name.endswith('uniform')
    press = None if cal is None else caliber_pressure(cal, cache)
    rows = []
    for ch in fields.CHANNELS:
        name = ch['name']
        y, lat, lon = channel_stack(ch, cal, cache)
        dates = cache[ch['fields'][0]][3]
        splits = split_indices(dates)
        train = splits[0]
        if name.startswith('q'):
            y = np.log(np.maximum(y, 1e-7))
        if ch['level'] is None:
            pressure = None
        elif cal is None:
            pressure = interpolate_surface_pressure(lat, lon)     # E1 的路径
        else:
            pressure = press
        fixed0, masks0, domain0 = masks_for(y, pressure, ch['level'], 0, train)
        sigma = channel_scale(y, area_weights(lat, lon), domain0, train, masks0)
        if not np.isfinite(sigma) or sigma <= 0:
            failures.append({'caliber': cal_name, 'channel': name, 'error': 'degenerate scale'})
            continue
        yn = y / sigma
        shipped = None
        for degree in D_LADDER:
            rec = row_for(cal_name, ch, name, 'P1', degree, 0, masks0, fixed0, domain0,
                          y, yn, sigma, uniform, lat, lon, dates, splits, failures)
            if rec is None:
                continue
            rows.append(rec)
            if degree == SHIPPED_D:
                shipped = rec
        if shipped is None:
            continue
        for theta in THETA_LADDER:
            if theta == 0 or ch['level'] is None:
                # θ=0 就是 P1 的出货阶那一行；非层压通道的掩膜与 θ 无关（N4 的构造性事实）
                rows.append({**shipped, 'ladder': 'P2', 'theta_hpa': theta})
                continue
            _f, masks_t, domain_t = masks_for(y, pressure, ch['level'], theta, train)
            rec = row_for(cal_name, ch, name, 'P2', SHIPPED_D, theta, masks_t, fixed0, domain_t,
                          y, yn, sigma, uniform, lat, lon, dates, splits, failures)
            if rec is not None:
                rows.append(rec)
    return rows


def aggregate(rows, splits):
    """按档汇总：主账 L_null（含被排除格点计费）与副账 L_none。"""
    out = {}
    for r in rows:
        key = (r['caliber'], r['ladder'], r['degree'], r['theta_hpa'])
        acc = out.setdefault(key, {'L_null': {}, 'L_none': {}, 'coeff_bits': {},
                                   'resid_bits': {}, 'null_bits': {}, 'channels': 0,
                                   'n_distinct_domains': 0, 'excluded_cells': 0,
                                   'domain_cells': 0.0})
        acc['channels'] += 1
        acc['n_distinct_domains'] += r['n_distinct_domains']
        acc['excluded_cells'] += r['excluded_cells']
        acc['domain_cells'] += r['domain_cells']
        for split in splits:
            cb = r['bits'][split]['coeff_bits']
            rb = r['bits'][split]['resid_bits']
            nb = r['null_bits'][split]
            acc['L_none'][split] = acc['L_none'].get(split, 0.0) + cb + rb + r['domain_bits']
            acc['L_null'][split] = acc['L_null'].get(split, 0.0) + cb + rb + nb + r['domain_bits']
            acc['coeff_bits'][split] = acc['coeff_bits'].get(split, 0.0) + cb
            acc['resid_bits'][split] = acc['resid_bits'].get(split, 0.0) + rb
            acc['null_bits'][split] = acc['null_bits'].get(split, 0.0) + nb
    for acc in out.values():
        for ledger in ('L_null', 'L_none'):
            acc[ledger]['sel'] = acc[ledger]['train'] + acc[ledger]['valid']
            acc[ledger]['all'] = acc[ledger]['sel'] + acc[ledger]['tail']
    return out


def curve_for(agg, caliber, ladder, ledger='L_null'):
    rungs = sorted({(k[2], k[3]) for k in agg if k[0] == caliber and k[1] == ladder})
    return [(r, agg[(caliber, ladder, r[0], r[1])][ledger]['sel']) for r in rungs]


def judge(curve):
    vals = np.array([v for _, v in curve])
    idx = int(np.argmin(vals))
    margin = float(min(vals[0], vals[-1]) - vals[idx])
    gap = float(max(vals.max() - vals.min(), 1e-300))
    return {'argmin_rung': curve[idx][0], 'argmin_index': idx,
            'interior': bool(0 < idx < len(vals) - 1),
            'margin_bits': margin, 'margin_fraction_of_range': margin / gap,
            'endpoint_optimum': bool(idx in (0, len(vals) - 1)),
            'monotone_decreasing': bool(np.all(np.diff(vals) < 0)),
            'monotone_increasing': bool(np.all(np.diff(vals) > 0)),
            'value_at_argmin': float(vals[idx]), 'curve': [[r[0], r[1]] for r in curve]}


def readings(agg, caliber):
    """一个口径上的读数：对象共有组、矩阵专属组、原生专属组。"""
    j = {'P1': judge(curve_for(agg, caliber, 'P1')),
         'P2': judge(curve_for(agg, caliber, 'P2')),
         'P1_without_null': judge(curve_for(agg, caliber, 'P1', 'L_none')),
         'P2_without_null': judge(curve_for(agg, caliber, 'P2', 'L_none'))}
    d12 = {r['channel']: r for r in agg['_rows']
           if r['caliber'] == caliber and r['ladder'] == 'P1'
           and r['degree'] == SHIPPED_D and r['theta_hpa'] == 0}
    resid_curve = [agg.get((caliber, 'P1', d, 0), {}).get('resid_bits', {}).get('sel', np.nan)
                   for d in D_LADDER]
    coeff_curve = [agg.get((caliber, 'P1', d, 0), {}).get('coeff_bits', {}).get('sel', np.nan)
                   for d in D_LADDER]
    l12 = agg.get((caliber, 'P1', SHIPPED_D, 0), {}).get('L_null', {}).get('sel', float('nan'))
    return {
        'object': {
            'nq_at_d12': {k: v['n_distinct_domains'] for k, v in d12.items()},
            'area_fraction_at_d12': {k: v['min_area_fraction'] for k, v in d12.items()},
            'gram_condition_at_d12': {k: v['max_gram_condition'] for k, v in d12.items()},
            'month_partition_at_d12': {k: v['index_digest'] for k, v in d12.items()},
        },
        'matrix': {
            'argmin_degree': j['P1']['argmin_rung'], 'interior': j['P1']['interior'],
            'endpoint_optimum': j['P1']['endpoint_optimum'],
            'monotone_decreasing': j['P1']['monotone_decreasing'],
            'L_sel_at_d12': l12,
            'refine_monotone': bool(np.all(np.diff(resid_curve) < 0)
                                    and np.all(np.diff(coeff_curve) > 0)),
            'argmin_degree_without_null': j['P1_without_null']['argmin_rung'],
        },
        'native': {
            'argmin_theta': j['P2']['argmin_rung'], 'interior': j['P2']['interior'],
            'endpoint_optimum': j['P2']['endpoint_optimum'],
            'theta_curve_direction': ('decreasing' if j['P2']['monotone_decreasing'] else
                                      'increasing' if j['P2']['monotone_increasing'] else 'mixed'),
            'nq_theta_curve': [agg.get((caliber, 'P2', SHIPPED_D, t), {})
                               .get('n_distinct_domains', -1) for t in THETA_LADDER],
            'L_sel_at_theta0': l12,
            'argmin_theta_without_null': j['P2_without_null']['argmin_rung'],
            'interior_without_null': j['P2_without_null']['interior'],
        },
        'judge': j,
    }


def invariant(values, kind):
    if kind == 'exact':
        first = values[0]
        return all(v == first for v in values[1:])
    first = float(values[0])
    return all(abs(float(v) - first) <= INVARIANCE_RTOL * max(abs(first), 1e-300)
               for v in values[1:])


MATRIX_READINGS = [('argmin_degree', 'exact'), ('interior', 'exact'),
                   ('monotone_decreasing', 'exact'), ('endpoint_optimum', 'exact'),
                   ('L_sel_at_d12', 'float'), ('refine_monotone', 'exact'),
                   ('argmin_degree_without_null', 'exact')]
NATIVE_READINGS = [('argmin_theta', 'exact'), ('interior', 'exact'),
                   ('endpoint_optimum', 'exact'), ('theta_curve_direction', 'exact'),
                   ('nq_theta_curve', 'exact'), ('L_sel_at_theta0', 'float'),
                   ('argmin_theta_without_null', 'exact'), ('interior_without_null', 'exact')]
OBJECT_READINGS = ['nq_at_d12', 'area_fraction_at_d12', 'gram_condition_at_d12',
                   'month_partition_at_d12']


def compare_readings(per_caliber):
    """C-4：逐读数在 4 个网格口径上的不变性，并标出退化读数。"""
    rep = {'object': {}, 'matrix': {}, 'native': {}}
    for nm in OBJECT_READINGS:
        vals = [per_caliber[c]['object'][nm] for c in GRID_CALIBERS]
        if isinstance(vals[0], dict):
            keys = sorted(vals[0])
            same = all(all(vals[0][k] == v[k] for k in keys) for v in vals[1:])
            detail = {c: {k: vals[i][k] for k in keys} for i, c in enumerate(GRID_CALIBERS)}
        else:
            same = invariant(vals, 'exact')
            detail = dict(zip(GRID_CALIBERS, vals))
        rep['object'][nm] = {'invariant': bool(same), 'kind': 'exact', 'values': detail,
                             'note': '对象共有组：两种呈现共用同一批掩膜，不用于判别'}
    for nm, kind in MATRIX_READINGS:
        vals = [per_caliber[c]['matrix'][nm] for c in GRID_CALIBERS]
        deg = ((nm.startswith('argmin') and all(v == D_LADDER[-1] for v in vals))
               or (nm == 'monotone_decreasing' and all(v is True for v in vals))
               or (nm == 'endpoint_optimum' and all(v is True for v in vals))
               or (nm == 'interior' and all(v is False for v in vals)))
        rep['matrix'][nm] = {'invariant': bool(invariant(vals, kind)), 'kind': kind,
                             'degenerate': bool(deg),
                             'values': dict(zip(GRID_CALIBERS, vals))}
    for nm, kind in NATIVE_READINGS:
        vals = [per_caliber[c]['native'][nm] for c in GRID_CALIBERS]
        deg = ((nm.startswith('argmin_theta')
                and all(v in (THETA_LADDER[0], THETA_LADDER[-1]) for v in vals))
               or (nm in ('interior', 'interior_without_null') and all(v is False for v in vals))
               or (nm == 'endpoint_optimum' and all(v is True for v in vals)))
        rep['native'][nm] = {'invariant': bool(invariant(vals, kind)), 'kind': kind,
                             'degenerate': bool(deg),
                             'values': {c: (v if not isinstance(v, (dict, list)) else v)
                                        for c, v in zip(GRID_CALIBERS, vals)}}
    counts = {}
    for group in ('object', 'matrix', 'native'):
        items = rep[group]
        counts[group] = {
            'readings': len(items),
            'invariant_total': sum(1 for v in items.values() if v['invariant']),
            'degenerate': sum(1 for v in items.values() if v.get('degenerate', False)),
            'invariant_non_degenerate': sum(1 for v in items.values()
                                            if v['invariant'] and not v.get('degenerate', False))}
    rep['counts'] = counts
    rep['C4_verdict'] = {
        'rule': '原生非退化不变数 ≥ 矩阵非退化不变数 ＋ 1',
        'native_non_degenerate_invariant': counts['native']['invariant_non_degenerate'],
        'matrix_non_degenerate_invariant': counts['matrix']['invariant_non_degenerate'],
        'holds': bool(counts['native']['invariant_non_degenerate']
                      >= counts['matrix']['invariant_non_degenerate'] + 1)}
    return rep


def check_permuted_domain(cal_name, cal, cache, failures):
    """N1：把「月份 ↔ 掩膜」的对应随机置换（破坏可区分性），主账必须在每一档都变差。"""
    rng = np.random.default_rng(20260929)
    ch = next(c for c in fields.CHANNELS if c['name'] == 't850')
    y, lat, lon = channel_stack(ch, cal, cache)
    pressure = (interpolate_surface_pressure(lat, lon) if cal is None
                else caliber_pressure(cal, cache))
    dates = cache['t850'][3]
    splits = split_indices(dates)
    fixed0, masks0, domain0 = masks_for(y, pressure, ch['level'], 0, splits[0])
    sigma = channel_scale(y, area_weights(lat, lon), domain0, splits[0], masks0)
    yn = y / sigma
    perm = rng.permutation(len(dates))
    detail = []
    for degree in (10, SHIPPED_D):
        try:
            coeff, _, residual, _, _ = project_one(yn, masks0, degree, False, lat, lon)
            base = code_bits(coeff, masks0.sum(axis=1), residual, splits)['train']
            masks_p = masks0[perm]
            coeff_p, _, residual_p, _, _ = project_one(yn, masks_p, degree, False, lat, lon)
            permd = code_bits(coeff_p, masks_p.sum(axis=1), residual_p, splits)['train']
        except Exception as exc:
            failures.append({'caliber': cal_name, 'control': 'N1', 'error': str(exc)})
            return {'holds': None, 'reason': f'projection failed: {exc}'}
        base_total = base['coeff_bits'] + base['resid_bits']
        perm_total = permd['coeff_bits'] + permd['resid_bits']
        detail.append({'degree': degree, 'base_bits': base_total, 'permuted_bits': perm_total,
                       'worse': bool(perm_total > base_total),
                       'relative_increase': (perm_total - base_total) / abs(base_total)})
    ok = all(d['worse'] for d in detail) and len(detail) == 2
    return {'holds': bool(ok), 'detail': detail}


def cross_source(cache):
    """§D：2026-02，ERA5 的 sp／sst 与 R1-ext 在同一口径上的筛选读数。

    **限度**：ERA5 只有 2026-02 这一个月，没有 1979–2014 的训练期最小值 ⇒ 冻结口径的
    「域」（由训练期最小值决定）**无法**用 ERA5 重算。本节只比**当月**的筛选掩膜与面积，
    不冒充域的重算，也不产出任何预报。
    """
    era = {'sp': _load_era5('sp'), 'sst': _load_era5('sst')}
    r1 = {'sp': _load_ext('sp'), 'sst': _load_ext('sst')}
    out = {'units': {'era5_sp': era['sp'][3], 'era5_sst': era['sst'][3],
                     'r1_sp': None, 'r1_sst': None},
           'sp_magnitude_ok': bool(SP_RANGE[0] <= np.nanmin(era['sp'][0]) <= SP_RANGE[1]),
           'by_caliber': {}}
    for cal_name, cal in CALIBERS:
        if cal is None:
            tlat, tlon = cache['sp'][1], cache['sp'][2]            # R1 的 sp 原生网格（E1 的比较口径）
        else:
            tlat, tlon = make_grid(*cal)
        entry = {'levels': {}}
        sp_era = regrid_conservative(era['sp'][0], era['sp'][1], era['sp'][2], tlat, tlon)
        sp_r1 = regrid_conservative(r1['sp'][0], r1['sp'][1], r1['sp'][2], tlat, tlon)
        w = area_weights(tlat, tlon)
        for level in (850, 700, 500):
            m_era, m_r1 = sp_era >= level * 100.0, sp_r1 >= level * 100.0
            flips = int((m_era != m_r1).sum())
            entry['levels'][str(level)] = {
                'cells': int(m_era.size), 'flips': flips,
                'flip_fraction': flips / float(m_era.size),
                'area_fraction_era5': float((w * m_era).sum()),
                'area_fraction_r1': float((w * m_r1).sum()),
                'near_threshold_cells_5hPa': int(((np.abs(sp_era - level * 100.0) <= 500.0)
                                                  | (np.abs(sp_r1 - level * 100.0) <= 500.0)).sum())}
        sst_era = regrid_conservative(era['sst'][0], era['sst'][1], era['sst'][2], tlat, tlon)
        sst_r1 = regrid_conservative(r1['sst'][0], r1['sst'][1], r1['sst'][2], tlat, tlon)
        both = np.isfinite(sst_era) & np.isfinite(sst_r1)
        entry['sst'] = {
            'common_ocean_cells': int(both.sum()),
            'finite_era5_only': int((np.isfinite(sst_era) & ~np.isfinite(sst_r1)).sum()),
            'finite_r1_only': int((np.isfinite(sst_r1) & ~np.isfinite(sst_era)).sum()),
            'mean_diff_K': float(np.mean(sst_era[both] - sst_r1[both])) if both.any() else None,
            'median_abs_diff_K': float(np.median(np.abs(sst_era[both] - sst_r1[both])))
            if both.any() else None}
        entry['grid'] = [int(tlat.size), int(tlon.size)]
        out['by_caliber'][cal_name] = entry
    return out


def _load_era5(var):
    with np.load(ERA5_MONTH / f'{var}.npz', allow_pickle=True) as f:
        return (f['values'].astype(float), f['latitude'].astype(float),
                f['longitude'].astype(float), float(f['units']))


def _load_ext(code):
    with np.load(INPUTS_EXT / f'{code}.npz', allow_pickle=True) as f:
        values, lat, lon, time = f['values'], f['lat'], f['lon'], f['time']
    order = np.argsort(-lat)
    order = order[abs(lat[order]) < 89.999]
    return (values[-1][order].astype(float), lat[order], lon.copy(), str(time[-1]))


def _hash_dir(path):
    out = {}
    for p in sorted(path.rglob('*')):
        if p.is_file():
            out[str(p.relative_to(path))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def _gate_regrid(cache):
    """G2：① 恒等重网格必须为 0；② 整条序列版与单月版必须一致。"""
    clat, clon = make_grid(2.5, 87.5, 144)
    values, lat, lon, _ = cache['t850']
    stacked = conservative_stack(values, lat, lon, clat, clon)
    single = np.stack([regrid_conservative(values[t], lat, lon, clat, clon)
                       for t in range(values.shape[0])])
    diff = float(np.nanmax(np.abs(stacked - single)))
    scale = float(np.nanmax(np.abs(single)))
    identity = float(np.nanmax(np.abs(stacked - values)))
    sp_lat = cache['sp'][1]
    return {'holds': bool(identity <= 0.0 and diff <= REGRID_RTOL * scale),
            'identity_max_abs_change': identity,
            'stack_vs_single_max_abs': diff, 'stack_vs_single_relative': diff / max(scale, 1e-300),
            'tolerance_relative': REGRID_RTOL,
            'sp_native_lat_is_gaussian': bool(not np.allclose(np.diff(sp_lat), np.diff(sp_lat)[0]))}


def _gate_units(cache):
    """N2：单位注入（sp 当 hPa 用）必须被量级闸门拒收。"""
    values = cache['sp'][0]
    raw_ok = bool(SP_RANGE[0] <= np.nanmin(values) and np.nanmax(values) <= SP_RANGE[1])
    injected = values * 0.01
    inj_ok = bool(SP_RANGE[0] <= np.nanmin(injected) and np.nanmax(injected) <= SP_RANGE[1])
    return {'holds': bool(raw_ok and not inj_ok), 'raw_in_range': raw_ok,
            'injected_in_range': inj_ok, 'range': list(SP_RANGE)}


def _gate_e1(rows):
    """G3：口径 A、θ=0 的掩膜类读数与残差必须与 E1 一致。"""
    if not E1_REPORT.exists():
        return {'holds': None, 'reason': 'E1 report missing'}
    e1 = json.loads(E1_REPORT.read_text())
    ref = {(r['degree'], r['channel']): r for r in e1['per_channel']}
    bad, checked = [], 0
    for r in rows:
        if r['caliber'] != 'A-native' or r['ladder'] != 'P1' or r['theta_hpa'] != 0:
            continue
        key = (r['degree'], r['channel'])
        if key not in ref:
            continue
        checked += 1
        a = ref[key]
        if a['observation_quotient_groups'] != r['n_distinct_domains']:
            bad.append([key, 'n_distinct_domains', a['observation_quotient_groups'],
                        r['n_distinct_domains']])
        if abs(a['min_area_fraction'] - r['min_area_fraction']) > 1e-12:
            bad.append([key, 'min_area_fraction', a['min_area_fraction'], r['min_area_fraction']])
        if abs(a['max_gram_condition'] - r['max_gram_condition']) > 1e-9 * a['max_gram_condition']:
            bad.append([key, 'max_gram_condition', a['max_gram_condition'],
                        r['max_gram_condition']])
        want = a['residual_mean'] * r['sigma'] ** 2
        if abs(want - r['residual_mean']) > 1e-9 * max(abs(want), 1e-300):
            bad.append([key, 'residual_mean_rescaled', want, r['residual_mean']])
    return {'holds': bool(not bad and checked > 0), 'checked': checked,
            'mismatch_count': len(bad), 'mismatches': bad[:20]}


def _gate_area(per_caliber):
    """G6：B/C/D 的域面积比与 A 的相对差 ≤ 5%（正对照：口径确实承载同一内容）。"""
    base = per_caliber['A-native']['object']['area_fraction_at_d12']
    worst = {}
    for c in GRID_CALIBERS[1:]:
        vals = per_caliber[c]['object']['area_fraction_at_d12']
        keys = sorted(set(base) & set(vals))
        worst[c] = float(max(abs(vals[k] - base[k]) / max(abs(base[k]), 1e-300) for k in keys)) \
            if keys else float('nan')
    return {'holds': bool(all(v <= AREA_TOL for v in worst.values())),
            'worst_relative': worst, 'tolerance': AREA_TOL}


def _gate_metric(per_caliber):
    """N4：度量口径 M 只应改变依赖权重的读数；掩膜类读数必须与 B 逐位相同。"""
    b = per_caliber['B-2p5']
    m = per_caliber['M-2p5-uniform']
    keys = sorted(set(b['object']['area_fraction_at_d12'])
                  & set(m['object']['area_fraction_at_d12']))
    masks_same = (b['object']['nq_at_d12'] == m['object']['nq_at_d12']
                  and b['object']['month_partition_at_d12'] == m['object']['month_partition_at_d12']
                  and all(abs(b['object']['area_fraction_at_d12'][k]
                              - m['object']['area_fraction_at_d12'][k]) <= 1e-12 for k in keys))
    differs = b['matrix']['L_sel_at_d12'] != m['matrix']['L_sel_at_d12']
    return {'holds': bool(masks_same and differs), 'masks_identical': bool(masks_same),
            'weight_dependent_reading_differs': bool(differs),
            'L_sel_B': b['matrix']['L_sel_at_d12'], 'L_sel_M': m['matrix']['L_sel_at_d12']}


def _gate_trivial():
    """N3：平凡不变的读数是不变的，但没有判别力 ⇒ C-4 只数「非退化」的不变读数。"""
    return {'holds': bool(invariant([1.0, 1.0, 1.0, 1.0], 'float')),
            'note': '常数读数被记作不变；C-4 的计数规则已把它排除（只看非退化项）'}


def _predictions(per_caliber, cross, failures):
    p1 = {c: per_caliber[c]['judge']['P1'] for c in GRID_CALIBERS}
    p2 = {c: per_caliber[c]['judge']['P2'] for c in GRID_CALIBERS}
    items = []
    items.append(('P1', bool(all(not x['interior'] for x in p1.values())
                             and all(x['argmin_rung'] == D_LADDER[-1] for x in p1.values())),
                  {'argmin_degree': {c: p1[c]['argmin_rung'] for c in GRID_CALIBERS}}))
    n_int = sum(1 for c in GRID_CALIBERS if p2[c]['interior'])
    items.append(('P2', bool(n_int >= 3),
                  {'interior_count': n_int, 'argmin_theta': {c: p2[c]['argmin_rung']
                                                             for c in GRID_CALIBERS}}))
    items.append(('P3', bool(len({p2[c]['argmin_rung'] for c in GRID_CALIBERS}) > 1),
                  {'argmin_theta': {c: p2[c]['argmin_rung'] for c in GRID_CALIBERS}}))
    items.append(('P4', bool(all(per_caliber[c]['judge']['P2_without_null']['endpoint_optimum']
                                 for c in GRID_CALIBERS)),
                  {'argmin_theta_without_null':
                   {c: per_caliber[c]['judge']['P2_without_null']['argmin_rung']
                    for c in GRID_CALIBERS}}))
    items.append(('P5', bool(any(f.get('caliber') == 'D-10' for f in failures)),
                  {'failures_D10': sum(1 for f in failures if f.get('caliber') == 'D-10'),
                   'failures_total': len(failures)}))
    worst = max(v['flip_fraction'] for e in cross['by_caliber'].values()
                for v in e['levels'].values())
    items.append(('P6', bool(worst < 0.02), {'worst_flip_fraction': worst,
                                             'threshold': 0.02}))
    nq_a = per_caliber['A-native']['object']['nq_at_d12']
    nq_b = per_caliber['B-2p5']['object']['nq_at_d12']
    on_25 = [ch['name'] for ch in fields.CHANNELS if ch['fields'][0] not in ('sp', 't2m', 'sst')]
    same_25 = all(nq_a[k] == nq_b[k] for k in on_25)
    differs = any(nq_a[k] != nq_b[k] for k in ('sp', 't2m', 'sst'))
    items.append(('P7', bool(same_25 and differs),
                  {'channels_on_2p5': len(on_25), 'same_2p5': same_25,
                   'gaussian_or_ersst_differs': differs,
                   'nq_A_minus_B': {k: nq_a[k] - nq_b[k] for k in sorted(nq_a)}}))
    return {'total': len(items), 'checked': len(items),
            'items': [{'id': i, 'hit': v, 'detail': d} for i, v, d in items]}


def main():
    if (OUT / 'report.json').exists():
        raise FileExistsError(f'completed run already exists: {OUT}')
    OUT.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    failures = []
    frozen_before = _hash_dir(FROZEN) if FROZEN.exists() else {}
    log('读 15 条通道（只读）')
    codes = sorted({c for ch in fields.CHANNELS for c in ch['fields']})
    cache = {code: load_field(code) for code in codes}
    dates = cache['sp'][3]
    splits = split_indices(dates)
    log(f'月份 {dates[0]}…{dates[-1]}（{len(dates)}）训练 {splits[0].size}／'
        f'验证 {splits[1].size}／尾部 {splits[2].size}')

    gates = {}
    gates['G2'] = _gate_regrid(cache)
    gates['N2'] = _gate_units(cache)
    log(f"G2 恒等 {gates['G2']['identity_max_abs_change']}；"
        f"序列版 vs 单月版 {gates['G2']['stack_vs_single_max_abs']}")

    per_caliber, all_rows = {}, []
    for cal_name, cal in CALIBERS:
        cal = None if cal is None else make_grid(*cal)
        log(f'口径 {cal_name}：P1 {D_LADDER} ＋ P2 θ {THETA_LADDER}')
        rows = run_caliber(cal_name, cal, cache, failures)
        agg = aggregate(rows, {'train': splits[0], 'valid': splits[1], 'tail': splits[2]})
        agg['_rows'] = rows
        per_caliber[cal_name] = readings(agg, cal_name)
        all_rows.extend(rows)
        log(f'  {len(rows)} 行；失败累计 {len(failures)}')

    gates['G3'] = _gate_e1(all_rows)
    gates['G6'] = _gate_area(per_caliber)
    cmp = compare_readings(per_caliber)
    gates['N1'] = check_permuted_domain('A-native', None, cache, failures)
    gates['N4'] = _gate_metric(per_caliber)
    gates['N3'] = _gate_trivial()
    log('§D 跨来源：2026-02 的 ERA5 vs R1-ext（只比当月筛选读数）')
    cross = cross_source(cache)
    predictions = _predictions(per_caliber, cross, failures)
    gates['G5'] = {'holds': bool(predictions['checked'] == predictions['total']),
                   'checked': predictions['checked'], 'total': predictions['total']}
    gates['G1'] = {'holds': bool((_hash_dir(FROZEN) if FROZEN.exists() else {}) == frozen_before),
                   'note': 'archive/multivariate-l12-v1/ 的 sha256 清单跑前后比对'}
    gates['G4'] = {'holds': True, 'failures_recorded': len(failures)}

    c1 = {'rule': '选阶判据必须有内部最优，且该最优对口径扰动稳健',
          'matrix': {'interior_count': sum(1 for c in GRID_CALIBERS
                                           if per_caliber[c]['judge']['P1']['interior']),
                     'argmin_per_caliber': {c: per_caliber[c]['judge']['P1']['argmin_rung']
                                            for c in GRID_CALIBERS}},
          'native': {'interior_count': sum(1 for c in GRID_CALIBERS
                                           if per_caliber[c]['judge']['P2']['interior']),
                     'argmin_per_caliber': {c: per_caliber[c]['judge']['P2']['argmin_rung']
                                            for c in GRID_CALIBERS},
                     'robust_location': len({per_caliber[c]['judge']['P2']['argmin_rung']
                                             for c in GRID_CALIBERS}) == 1},
          'native_without_null': {'interior_count':
                                  sum(1 for c in GRID_CALIBERS if per_caliber[c]['judge']
                                      ['P2_without_null']['interior']),
                                  'argmin_per_caliber':
                                  {c: per_caliber[c]['judge']['P2_without_null']['argmin_rung']
                                   for c in GRID_CALIBERS}}}
    report = {
        'question_id': 'xue.derived.caliber-invariance-c1-c4',
        'version': 'caliber-invariance-v1',
        'contract': 'experiments/caliber-invariance/contract.json',
        'calibers': [c[0] for c in CALIBERS], 'grid_calibers': GRID_CALIBERS,
        'degree_ladder': D_LADDER, 'shipped_degree': SHIPPED_D,
        'theta_ladder_hpa': THETA_LADDER,
        'splits': {'train': [str(dates[splits[0][0]]), str(dates[splits[0][-1]]),
                             int(splits[0].size)],
                   'valid': [str(dates[splits[1][0]]), str(dates[splits[1][-1]]),
                             int(splits[1].size)],
                   'tail': [str(dates[splits[2][0]]), str(dates[splits[2][-1]]),
                            int(splits[2].size)]},
        'gates': gates, 'predictions': predictions, 'failures': failures,
        'C1': c1, 'C4': cmp, 'cross_source_2026_02': cross,
        'per_caliber': {k: {kk: vv for kk, vv in v.items() if kk not in ('judge', 'object')}
                        for k, v in per_caliber.items()},
        'judge_detail': {k: v['judge'] for k, v in per_caliber.items()},
        'object_readings': {k: {kk: (vv if not isinstance(vv, dict) else
                                     {a: b for a, b in vv.items()})
                                for kk, vv in v['object'].items() if kk != 'month_partition_at_d12'}
                            for k, v in per_caliber.items()},
        'rows': all_rows,
        'wall_seconds': round(time.perf_counter() - started, 1),
        'peak_rss_mb': round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1),
    }
    (OUT / 'report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False,
                                                allow_nan=False) + '\n')
    log(f'写出 {OUT / "report.json"}；wall {report["wall_seconds"]} s；'
        f'peak {report["peak_rss_mb"]} MB')
    log(json.dumps({'C1': c1, 'C4_verdict': cmp['C4_verdict'],
                    'predictions': [{'id': i['id'], 'hit': i['hit']}
                                    for i in predictions['items']],
                    'failures': len(failures)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
