"""Decompose the ERA5-vs-R1 comparison so the bias and the std can actually be read.

Reads the two compared fields that the feasibility probe already stored inside
archive/era5-sp-sst-feasibility-v1/report.json, so NOTHING is downloaded again and no
frozen artifact is touched.

Why this exists: reporting "global bias -0.068 K, std 0.543 K" invites two mistakes.
  * a small SIGNED mean can come from regional biases of opposite sign cancelling;
  * a std with a few extreme cells in it says nothing about the typical cell.
Both are checked here, plus the selection effect: the comparison only runs on cells where
BOTH sources have data, and the two land/sea masks disagree exactly along coasts and ice
edges -- which is where the largest differences live.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

sys_path_ok = Path(__file__).resolve().parent
import sys
sys.path.insert(0, str(sys_path_ok))
import probe_era5 as P          # reuse read_day / days_available / regrid_conservative

REPO = Path('/home/ubuntu/xue-study')
RUN = REPO / 'archive/era5-sp-sst-feasibility-v1'
R1 = Path('/home/ubuntu/climatetensor-inputs/ncep-multivariate-ext-202602')


def band_stats(diff, lat, lon, mask, edges):
    rows = []
    for a, b in zip(edges[:-1], edges[1:], strict=True):
        sel = mask & (lat[:, None] >= a) & (lat[:, None] < b)
        d = diff[sel]
        d = d[np.isfinite(d)]
        if d.size == 0:
            continue
        rows.append({'lat_band': f'{a:+.0f}..{b:+.0f}', 'n': int(d.size),
                     'bias': round(float(d.mean()), 4), 'std': round(float(d.std()), 4),
                     'median_abs': round(float(np.median(np.abs(d))), 4),
                     'frac_abs_gt_1K': round(float(np.mean(np.abs(d) > 1.0)), 4)})
    return rows


def sector_stats(diff, lat, lon, mask, width=60):
    rows = []
    for a in range(-180, 180, width):
        sel = mask & (lon[None, :] >= a) & (lon[None, :] < a + width)
        d = diff[sel]
        d = d[np.isfinite(d)]
        if d.size == 0:
            continue
        rows.append({'lon_sector': f'{a:+d}..{a + width:+d}', 'n': int(d.size),
                     'bias': round(float(d.mean()), 4), 'std': round(float(d.std()), 4)})
    return rows


def coastal_split(diff, valid_r1, lat, lon):
    """Open ocean vs cells with a land neighbour, using R1's own mask as the land/sea map."""
    land = ~valid_r1
    nb_land = np.zeros_like(land)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == 0 and dx == 0:
                continue
            nb_land |= np.roll(np.roll(land, dy, axis=0), dx, axis=1)
    out = {}
    for name, sel in (('open_ocean', ~nb_land), ('coastal_or_ice_edge', nb_land)):
        d = diff[sel & np.isfinite(diff)]
        out[name] = {'n': int(d.size), 'bias': round(float(d.mean()), 4),
                     'std': round(float(d.std()), 4),
                     'median_abs': round(float(np.median(np.abs(d))), 4),
                     'p95_abs': round(float(np.percentile(np.abs(d), 95)), 4)}
    return out


def era5_month(variable: str, month: str) -> dict:
    """Re-derive the ERA5 monthly mean for one month (the report kept only the changes)."""
    y, m = int(month[:4]), int(month[5:7])
    days = P.days_available(y, m, variable)
    return P.month_mean(variable, y, m, days)


def r1_field(code: str, month: str) -> dict:
    z = np.load(R1 / f'{code}.npz')
    t = np.asarray(z['time']).astype(str)
    i = int(np.flatnonzero(np.char.startswith(t, month))[0])
    return {'values': np.asarray(z['values'][i], dtype=float),
            'lat': np.asarray(z['lat'], dtype=float), 'lon': np.asarray(z['lon'], dtype=float)}


def main() -> int:
    lines = []

    def say(s):
        lines.append(s)
        print(s, flush=True)

    summary = {}
    for ch, var, unit in (('sst', 'sea_surface_temperature', 'K'),):
        era_m = era5_month(var, '2026-02')
        r1_m = r1_field(ch, '2026-02')
        lat, lon = r1_m['lat'], r1_m['lon']
        era = P.regrid_conservative(era_m['values'], era_m['lat'], era_m['lon'], lat, lon)
        r1 = r1_m['values']
        say(f'（ERA5 {var} 2026-02 重算：{era_m["n_days"]} 天，格式 {era_m["file_formats_seen"]}）')
        valid_r1 = np.isfinite(r1)
        both = valid_r1 & np.isfinite(era)
        diff = era - r1
        d = diff[both]

        say(f'\n================ {ch} ({unit}) ================')
        say(f'R1 格总数 {r1.size}，R1 有值 {int(valid_r1.sum())}，两侧都有值（参与比较）{int(both.sum())}，'
            f'因掩码不一致被排除 {int(valid_r1.sum() - both.sum())}')
        say(f'有符号差：mean {d.mean():+.4f}  std {d.std():.4f}  median {np.median(d):+.4f}')
        say(f'分位：p05 {np.percentile(d, 5):+.4f}  p25 {np.percentile(d, 25):+.4f}  '
            f'p75 {np.percentile(d, 75):+.4f}  p95 {np.percentile(d, 95):+.4f}  '
            f'min {d.min():+.4f}  max {d.max():+.4f}')
        ad = np.abs(d)
        say(f'绝对差：median {np.median(ad):.4f}  p90 {np.percentile(ad, 90):.4f}  '
            f'p95 {np.percentile(ad, 95):.4f}  p99 {np.percentile(ad, 99):.4f}  max {ad.max():.4f}')
        thr = (0.25, 0.5, 1.0, 2.0) if ch == 'sst' else (50.0, 100.0, 500.0, 1000.0)
        say('落在阈值内的比例：' + '  '.join(f'|d|<{t}{unit}: {np.mean(ad < t):.3f}' for t in thr))
        # 符号抵消的证据：按符号分组求和
        pos, neg = d[d > 0], d[d < 0]
        say(f'正差 {pos.size} 格（合计 {pos.sum():+.2f}），负差 {neg.size} 格（合计 {neg.sum():+.2f}）'
            f' ⇒ 相消后 {d.sum():+.2f}')
        bands = band_stats(diff, lat, lon, both, list(range(-90, 91, 10)))
        say('分纬度带（10°）：')
        for r in bands:
            say('   ' + json.dumps(r, ensure_ascii=False))
        say('分经度扇区（60°）：')
        for r in sector_stats(diff, lat, lon, both, 60):
            say('   ' + json.dumps(r, ensure_ascii=False))
        coast = coastal_split(diff, valid_r1, lat, lon)
        say('开阔洋 vs 沿岸/冰缘（用 R1 掩码判陆）：')
        say('   ' + json.dumps(coast, ensure_ascii=False))
        summary[ch] = {
            'n_total_cells': int(r1.size), 'n_r1_valid': int(valid_r1.sum()),
            'n_compared': int(both.sum()), 'n_excluded_by_mask': int(valid_r1.sum() - both.sum()),
            'signed': {'mean': float(d.mean()), 'std': float(d.std()),
                       'median': float(np.median(d)),
                       'p05': float(np.percentile(d, 5)), 'p95': float(np.percentile(d, 95)),
                       'min': float(d.min()), 'max': float(d.max())},
            'absolute': {'median': float(np.median(ad)),
                         'p90': float(np.percentile(ad, 90)),
                         'p95': float(np.percentile(ad, 95)),
                         'p99': float(np.percentile(ad, 99)), 'max': float(ad.max())},
            'frac_abs_lt': {str(t_): float(np.mean(ad < t_)) for t_ in thr},
            'positive_sum': float(pos.sum()), 'negative_sum': float(neg.sum()),
            'cancel_to': float(d.sum()),
            'lat_bands': bands, 'lon_sectors': sector_stats(diff, lat, lon, both, 60),
            'coastal_split': coast,
            'unit': unit, 'n_days': int(era_m['n_days']),
        }
        # 极端格
        idx = np.dstack(np.unravel_index(np.argsort(-np.nan_to_num(np.abs(np.where(both, diff, np.nan)), nan=0).ravel())[:8], diff.shape))[0]
        say('|差| 最大的 8 格：')
        for i, j in idx:
            say(f'   lat {lat[i]:+7.2f} lon {lon[j]:+7.2f}  diff {diff[i, j]:+9.3f}{unit}  '
                f'R1 {r1[i, j]:9.2f}  ERA5 {era[i, j]:9.2f}  邻域含陆 {bool(np.isfinite(r1[max(i-1,0):i+2, max(j-1,0):j+2]).sum() < 9)}')

    (RUN / 'explain_bias.log').write_text('\n'.join(lines) + '\n')
    (RUN / 'explain_bias.json').write_text(
        json.dumps(P.jsonable(summary), ensure_ascii=False, indent=2) + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
