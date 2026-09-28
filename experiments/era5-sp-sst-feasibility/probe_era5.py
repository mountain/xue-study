"""Feasibility probe: can ARCO-ERA5 supply the two missing model channels (sp, sst)?

Round: xue.derived.era5-sp-sst-feasibility (contract.json, frozen first).

Reads the public ARCO-ERA5 bucket over HTTPS with fsspec + h5netcdf. No credentials are
involved and nothing under archive/ is touched. The question is factual: is the source
reachable and current, are the units and magnitudes right, and -- the part that actually
decides usability for `sp` -- does swapping it change the pressure-level screening mask?

Sampling caliber note: only the 00/06/12/18Z steps are used, because that is how the R1
monthly means the model was trained on were built. Sampling 24 hourly steps would be a
different (better) caliber and would make the comparison less like-for-like, not more.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np

REPO = Path('/home/ubuntu/xue-study')
OUT = REPO / 'archive/era5-sp-sst-feasibility-v1'
CONTRACT = Path(__file__).resolve().parent / 'contract.json'
R1 = Path('/home/ubuntu/climatetensor-inputs/ncep-multivariate-ext-202602')
BUCKET = 'https://storage.googleapis.com/gcp-public-data-arco-era5'
SINGLE = BUCKET + '/raw/date-variable-single_level'
MISSING = 3.4028234663852886e38
HOURS = (0, 6, 12, 18)
LEVELS = (850, 700, 500)
REGIONS = {'east_asia': (25., 40., 130., 170.), 'plateau': (28., 36., 80., 100.),
           'north_america': (32.5, 47.5, 280., 310.)}
sys.path.insert(0, str(REPO / 'experiments/continuous-assimilation'))
import cas  # noqa: E402  (regrid_to_model: conservative overlap-integral regrid)

def cell_edges(centres: np.ndarray, is_lat: bool) -> np.ndarray:
    """Cell edges from centres: midpoints inside, half a step outside."""
    c = np.asarray(centres, dtype=float)
    if c[0] > c[-1]:
        c = c[::-1]
    e = np.empty(c.size + 1)
    e[1:-1] = 0.5 * (c[:-1] + c[1:])
    e[0] = c[0] - 0.5 * (c[1] - c[0])
    e[-1] = c[-1] + 0.5 * (c[-1] - c[-2])
    return np.clip(e, -90.0, 90.0) if is_lat else e


def overlap_1d(src_edges, dst_edges, is_lat: bool) -> np.ndarray:
    """Exact overlap between every destination and every source cell, normalised per row.

    Latitude overlaps are measured in sin(lat) and longitude in degrees, so the outer
    product of the two is exactly the spherical area weight -- that is what makes this a
    conservative regrid. Longitude wraps, so the source is evaluated at -360/0/+360.
    """
    n_dst, n_src = dst_edges.size - 1, src_edges.size - 1
    W = np.zeros((n_dst, n_src))
    for i in range(n_dst):
        a0, a1 = dst_edges[i], dst_edges[i + 1]
        if is_lat:
            num = (np.sin(np.deg2rad(np.minimum(src_edges[1:], a1)))
                   - np.sin(np.deg2rad(np.maximum(src_edges[:-1], a0))))
            denom = np.sin(np.deg2rad(a1)) - np.sin(np.deg2rad(a0))
        else:
            num = (np.minimum(src_edges[1:], a1) - np.maximum(src_edges[:-1], a0))
            for shift in (-360.0, 360.0):
                num = np.maximum(num, np.minimum(src_edges[1:] + shift, a1)
                                 - np.maximum(src_edges[:-1] + shift, a0))
            denom = a1 - a0
        num = np.clip(num, 0.0, None)
        W[i] = num / denom if denom != 0 else 0.0
    return W


def regrid_conservative(values, src_lat, src_lon, dst_lat, dst_lon):
    """Conservative area-weighted regrid for ANY regular-or-Gaussian lat/lon pair.

    `cas.regrid_to_model` (used for the 0.25 -> 2.5 operational case) requires the
    destination longitude cells to be an integer number of source cells, which fails here:
    R1's sp sits on the T62 GAUSSIAN grid (94x192, non-uniform latitudes, 1.875 deg
    longitudes) and R1's sst on the ERSST 2 deg grid (89x180). This version carries the
    exact overlap integral in both axes, so no alignment is assumed. NaN cells (land in
    an SST field) are excluded and the weights renormalised over what remains.
    """
    src_lat = np.asarray(src_lat, dtype=float)
    dst_lat = np.asarray(dst_lat, dtype=float)
    src_lon = np.asarray(src_lon, dtype=float)
    dst_lon = np.asarray(dst_lon, dtype=float)
    # cell_edges() always works in ASCENDING order, so both axes are normalised here and
    # restored at the end. Forgetting the restore is exactly the bug C2a caught: the
    # identity regrid came back latitude-reversed (max change 52568 Pa), which silently
    # turned every downstream number into a comparison of the plateau against the
    # Southern Ocean. A control that compares a field with itself is what found it.
    flip_src_lat = src_lat[0] > src_lat[-1]
    flip_dst_lat = dst_lat[0] > dst_lat[-1]
    flip_src_lon = src_lon[0] > src_lon[-1]
    flip_dst_lon = dst_lon[0] > dst_lon[-1]
    src = np.asarray(values, dtype=float)
    if flip_src_lat:
        src = src[::-1, :]
    if flip_src_lon:
        src = src[:, ::-1]
    Wlat = overlap_1d(cell_edges(src_lat, True), cell_edges(dst_lat, True), True)
    Wlon = overlap_1d(cell_edges(src_lon, False), cell_edges(dst_lon, False), False)
    good = np.isfinite(src)
    num = Wlat @ np.where(good, src, 0.0) @ Wlon.T
    den = Wlat @ good.astype(float) @ Wlon.T
    with np.errstate(invalid='ignore', divide='ignore'):
        out = np.where(den > 0, num / den, np.nan)
    if flip_dst_lat:
        out = out[::-1, :]
    if flip_dst_lon:
        out = out[:, ::-1]
    return out


def declared_range(variable: str):
    # 修正（跑之前）：最初写 [5e4, 1.1e5] Pa，而 2026-02 的**月平均** sp 在喜马拉雅上空
    # 低到 48890.9 Pa —— 这是物理上正确的（那里地面就在 500 hPa 以上），是我的下界写错了。
    # 改为 45000 Pa。这不削弱单位检测能力：若把 Pa 误当 hPa（值 ~1000）或把 degC 误当 K
    # （值 ~-5..30），都远在界外，仍会被拒（C1 就是这条注入测试）。
    return (4.5e4, 1.1e5) if variable == 'surface_pressure' else (265.0, 320.0)


def magnitude_ok(variable: str, values: np.ndarray) -> bool:
    lo, hi = declared_range(variable)
    finite = values[np.isfinite(values)]
    return bool(finite.size and finite.min() >= lo and finite.max() <= hi)


def grid_ok(lat: np.ndarray, lon: np.ndarray) -> bool:
    return bool(lat.size == 721 and lon.size == 1440
                and abs(lat[0] - 90.0) < 1e-9 and abs(lat[-1] + 90.0) < 1e-9
                and np.allclose(np.diff(lat), -0.25, atol=1e-9)
                and abs(lon[0]) < 1e-9 and abs(lon[-1] - 359.75) < 1e-9
                and np.allclose(np.diff(lon), 0.25, atol=1e-9))


def jsonable(obj):
    """Replace non-finite floats with None: json.dumps(..., allow_nan=False) refuses NaN,
    which is how the previous run died AFTER computing every number it needed."""
    if isinstance(obj, dict):
        return {k: jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [jsonable(v) for v in obj]
    if isinstance(obj, float):
        return obj if np.isfinite(obj) else None
    if isinstance(obj, (np.floating, np.integer)):
        v = obj.item()
        return jsonable(v)
    return obj


FAILURES: list[str] = []
LOG: list[str] = []


def log(msg) -> None:
    LOG.append(str(msg))
    print(msg, flush=True)


def gcs_list(prefix: str) -> list[str]:
    url = (f'https://storage.googleapis.com/storage/v1/b/gcp-public-data-arco-era5/o'
           f'?prefix={prefix}&delimiter=/&maxResults=1000')
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r).get('prefixes', [])


def days_available(year: int, month: int, variable: str) -> list[str]:
    pre = f'raw/date-variable-single_level/{year}/{month:02d}/'
    out = []
    for p in gcs_list(pre):
        d = p.rstrip('/').split('/')[-1]
        if d.isdigit():
            sub = gcs_list(p if p.endswith('/') else p + '/')
            if any(f'{variable}/' in q for q in sub):
                out.append(d)
    return sorted(out)


def read_day(variable: str, year: int, month: int, day: str, hours=HOURS):
    """Read a box-free full field for one day, picking the engine from the file signature.

    The bucket MIXES formats: files up to early 2026 are NetCDF-3 classic (signature
    b'CDF\\x02') while recent ones are HDF5. `h5netcdf` raises
    "b'CDF\\x02...' is not the signature of a valid netCDF4 file" on the former, and
    `netCDF4` is not installed here, so the classic files go through scipy's reader.
    Both are opened on an fsspec HTTP file object, so only the needed chunks are fetched.
    """
    import fsspec
    import xarray as xr
    url = f'{SINGLE}/{year}/{month:02d}/{day}/{variable}/surface.nc'
    with fsspec.open(url, 'rb') as f:
        signature = f.read(8)
    engine = 'h5netcdf' if signature[:4] == b'\x89HDF' else 'scipy'
    with fsspec.open(url, 'rb') as f:
        with xr.open_dataset(f, engine=engine) as ds:
            name = list(ds.data_vars)[0]
            units = ds[name].attrs.get('units')
            tdim = 'valid_time' if 'valid_time' in ds.sizes else 'time'
            da = ds[name]
            nt = da.sizes[tdim]
            want = [h for h in hours if h < nt] or [0]
            arr = np.asarray(da.isel({tdim: want}).load().values, dtype=np.float64)
            lat = np.asarray(ds['latitude'].values, dtype=float)
            lon = np.asarray(ds['longitude'].values, dtype=float)
    arr[arr > 1e30] = np.nan
    return arr, lat, lon, units, name, engine


def month_mean(variable: str, year: int, month: int, days: list[str]) -> dict:
    acc, lat, lon, units, name, n, engines = None, None, None, None, None, 0, set()
    for d in days:
        arr, la, lo, u, nm, eng = read_day(variable, year, month, d)
        engines.add(eng)
        # read_day returns (hours, lat, lon): average the 00/06/12/18Z steps into a DAILY
        # mean first, then average days. Skipping this step left a phantom (4, ...) axis
        # that silently propagated through the regrid -- hence the assertion below.
        good_h = np.isfinite(arr)
        with np.errstate(invalid='ignore', divide='ignore'):
            day = np.where(good_h.any(axis=0), np.nansum(arr, axis=0) / np.maximum(good_h.sum(axis=0), 1), np.nan)
        assert day.shape == la.shape + lo.shape, (variable, d, day.shape)
        if acc is None:
            acc, lat, lon, units, name = np.zeros_like(day), la, lo, u, nm
            seen = np.zeros_like(day)
        if day.shape != acc.shape:
            raise ValueError(f'{variable} {d}: shape changed {day.shape} != {acc.shape}')
        acc += np.nan_to_num(day, nan=0.0)
        # count per cell, so a day missing in some cells does not bias the mean
        seen += np.isfinite(day)
        n += 1
    if acc is None:
        return {'status': 'no_days'}
    with np.errstate(invalid='ignore', divide='ignore'):
        mean = np.where(seen > 0, acc / np.maximum(seen, 1), np.nan)
    return {'status': 'ok', 'values': mean, 'lat': lat, 'lon': lon, 'units': units,
            'variable': name, 'n_days': n, 'days': days, 'file_formats_seen': sorted(engines),
            'cells_with_data': int((seen > 0).sum()), 'cells_total': int(seen.size)}


def r1_month(variable: str, month: str) -> dict:
    z = np.load(R1 / f'{variable}.npz')
    t = np.asarray(z['time']).astype(str)
    idx = np.flatnonzero(np.char.startswith(t, month))
    if idx.size == 0:
        return {'status': 'no_month'}
    return {'status': 'ok', 'values': np.asarray(z['values'][idx[0]], dtype=np.float64),
            'lat': np.asarray(z['lat'], dtype=float), 'lon': np.asarray(z['lon'], dtype=float),
            'index': int(idx[0])}


def box_stats(a: np.ndarray, b: np.ndarray, lat, lon, box) -> dict:
    la0, la1, lo0, lo1 = box
    lonx = np.where(lon < lo0, lon + 360.0, lon)
    il = np.flatnonzero((lat >= la0) & (lat <= la1))
    io = np.flatnonzero((lonx >= lo0) & (lonx <= lo1))
    d = (a - b)[np.ix_(il, io)]
    good = np.isfinite(d)
    return {'n': int(good.sum()), 'mean': float(np.mean(d[good])) if good.any() else None,
            'std': float(np.std(d[good])) if good.any() else None,
            'max_abs': float(np.max(np.abs(d[good]))) if good.any() else None}


def main() -> int:
    if (OUT / 'report.json').exists():
        raise FileExistsError(f'completed run already exists: {OUT}')
    OUT.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    contract = json.loads(CONTRACT.read_text())
    log(f'contract {contract["version"]}')

    # ---- A. currency
    avail = {}
    for var in ('surface_pressure', 'sea_surface_temperature'):
        for ym in ((2026, 9), (2026, 2), (2026, 1)):
            d = days_available(*ym, var)
            avail[f'{var}|{ym[0]}-{ym[1]:02d}'] = {'n_days': len(d), 'first': d[0] if d else None,
                                                   'last': d[-1] if d else None}
            log(f'  {var} {ym[0]}-{ym[1]:02d}: {len(d)} 天  {d[0] if d else "-"} .. {d[-1] if d else "-"}')
    newest_full = None
    for key, v in avail.items():
        if v['last']:
            y, m = key.split('|')[1].split('-')
            cand = f'{y}-{m}-{v["last"]}'
            if newest_full is None or cand > newest_full:
                newest_full = cand
    server_day = time.strftime('%Y-%m-%d', time.gmtime())
    lag = int((np.datetime64(server_day) - np.datetime64(newest_full)).astype(int)) if newest_full else None

    # ---- B/C. one overlap month, both variables, both sides
    comparison = {}
    for var, model_channel in (('surface_pressure', 'sp'), ('sea_surface_temperature', 'sst')):
        days = days_available(2026, 2, var)
        era = month_mean(var, 2026, 2, days)
        r1 = r1_month(model_channel, '2026-02')
        if era['status'] != 'ok' or r1['status'] != 'ok':
            FAILURES.append(f'{var}: missing side (era={era["status"]}, r1={r1["status"]})')
            continue
        units = era['units']
        lo, hi = declared_range(var)
        finite = era['values'][np.isfinite(era['values'])]
        gate_ok = magnitude_ok(var, era['values'])
        if not gate_ok:
            FAILURES.append(f'G1 failed for {var}: range [{finite.min():.1f}, {finite.max():.1f}] '
                            f'units={units} outside declared [{lo}, {hi}]')
        # G2 grid check
        grid_ok_ = grid_ok(era['lat'], era['lon'])
        if not grid_ok_:
            FAILURES.append(f'G2 failed for {var}: grid {era["lat"][:2]} {era["lon"][:2]}')
        era_25 = regrid_conservative(era['values'], era['lat'], era['lon'], r1['lat'], r1['lon'])
        # longitude convention: R1 lon is 0..357.5, ERA5 0..359.75 -> both ascending from 0
        diff = era_25 - r1['values']
        good = np.isfinite(diff)
        # C2 control: same comparison but against the PREVIOUS month's ERA5
        prev = month_mean(var, 2026, 1, days_available(2026, 1, var))
        mis = (regrid_conservative(prev['values'], prev['lat'], prev['lon'], r1['lat'], r1['lon'])
               - r1['values']) if prev['status'] == 'ok' else None
        era1 = month_mean(var, 2026, 1, days_available(2026, 1, var))
        era1_25 = (regrid_conservative(era1['values'], era1['lat'], era1['lon'],
                                       r1['lat'], r1['lon']) if era1['status'] == 'ok' else None)
        r1_prev = r1_month(model_channel, '2026-01')
        r1_prev_v = (r1_prev['values'].reshape(r1['values'].shape)
                     if r1_prev['status'] == 'ok' and r1_prev['values'].shape == r1['values'].shape
                     else (regrid_conservative(r1_prev['values'], r1_prev['lat'], r1_prev['lon'],
                                               r1['lat'], r1['lon']) if r1_prev['status'] == 'ok' else None))
        comparison[model_channel] = {
            'era5_units': units, 'era5_variable': era['variable'], 'n_days': era['n_days'],
            'file_formats_seen': era['file_formats_seen'],
            'gate_range_ok': gate_ok, 'grid_ok': grid_ok_,
            'era5_finite_range': [float(finite.min()), float(finite.max())],
            'global': {'n': int(good.sum()), 'bias_mean': float(diff[good].mean()),
                       'bias_std': float(diff[good].std()),
                       'max_abs': float(np.abs(diff[good]).max()),
                       'r1_range': [float(np.nanmin(r1["values"])), float(np.nanmax(r1["values"]))]},
            'regions': {k: box_stats(era_25, r1['values'], r1['lat'], r1['lon'], v)
                        for k, v in REGIONS.items()},
            'era_change': (era_25 - era1_25).tolist() if era1_25 is not None else None,
            'r1_change': ((r1['values'] - r1_prev_v).tolist()
                          if r1_prev_v is not None else None),
            'near_threshold_cells': {
                str(lev): int(np.sum(np.abs(r1['values'] - lev * 100.0) < 500.0))
                for lev in LEVELS} if model_channel == 'sp' else None,
            'misaligned_month_bias_mean': (float(mis[np.isfinite(mis)].mean()) if mis is not None else None),
            'misaligned_abs_mean': (float(np.abs(mis[np.isfinite(mis)]).mean()) if mis is not None else None),
            'aligned_abs_mean': float(np.abs(diff[good]).mean()),
            'regrid_target_grid': [int(r1['lat'].size), int(r1['lon'].size)],
            'r1_lat': [float(v) for v in r1['lat']], 'r1_lon': [float(v) for v in r1['lon']],
            'era5_on_r1_grid': [[round(float(v), 3) for v in row] for row in era_25],
            'r1_month_values': [[round(float(v), 3) for v in row] for row in r1['values']],
        }
        log(f'  {var}: 单位={units} 值域=[{finite.min():.1f},{finite.max():.1f}] gate={gate_ok} '
            f'bias={diff[good].mean():+.3f} std={diff[good].std():.3f} maxabs={np.abs(diff[good]).max():.3f}')

    # ---- D. the screening flip test (this is what sp is FOR)
    flips = {}
    if 'sp' in comparison:
        era_sp = np.array(comparison['sp']['era5_on_r1_grid'], dtype=float)
        r1_sp = np.array(comparison['sp']['r1_month_values'], dtype=float)
        for lev in LEVELS:
            m_r1 = r1_sp >= lev * 100.0
            m_er = era_sp >= lev * 100.0
            both = np.isfinite(r1_sp) & np.isfinite(era_sp)
            n_flip = int(np.sum((m_r1 != m_er) & both))
            # margin near the threshold: how far is the plateau from flipping?
            near = float(np.nanmin(np.abs(r1_sp - lev * 100.0)))
            flips[str(lev)] = {'flipped_cells': n_flip, 'min_margin_Pa': near,
                               'r1_included': int(np.sum(m_r1 & both)),
                               'era5_included': int(np.sum(m_er & both)),
                               'comparable_cells': int(both.sum())}
            log(f'  层压筛选 {lev} hPa: 翻转 {n_flip} 格（R1 入选 {flips[str(lev)]["r1_included"]}，'
                f'ERA5 入选 {flips[str(lev)]["era5_included"]}，最小余量 {near:.0f} Pa）')

    # ---- E. current month, partial, regional only
    current = {}
    days9 = days_available(2026, 9, 'surface_pressure')
    if days9:
        era9 = month_mean('surface_pressure', 2026, 9, days9)
        stat9 = {}
        for k, b in REGIONS.items():
            la0, la1, lo0, lo1 = b
            lonx = np.where(era9['lon'] < lo0, era9['lon'] + 360.0, era9['lon'])
            il = np.flatnonzero((era9['lat'] >= la0) & (era9['lat'] <= la1))
            io = np.flatnonzero((lonx >= lo0) & (lonx <= lo1))
            sel = era9['values'][np.ix_(il, io)]
            stat9[k] = {'mean_Pa': float(np.nanmean(sel)), 'n': int(np.isfinite(sel).sum())}
        current = {'variable': 'surface_pressure', 'days_used': len(days9),
                   'first': days9[0], 'last': days9[-1], 'partial_month': True,
                   'regional_means': stat9}
        log(f'  2026-09 部分月（{len(days9)} 天，到 {days9[-1]}）: '
            + ', '.join(f'{k}={v["mean_Pa"]/100:.1f} hPa' for k, v in stat9.items()))

    # ---- controls
    #
    # C1  unit injection: take the real monthly sp (Pa) and mislabel it as hPa.
    real_sp = np.array(comparison.get('sp', {}).get('era5_on_r1_grid') or [[0.0]])
    c1 = not magnitude_ok('surface_pressure', real_sp / 100.0)
    #
    # C2 AS ORIGINALLY WRITTEN FAILED, and the failure is informative: it required a
    # month-MISALIGNED comparison to be worse, but the ERA5-minus-R1 sp difference is
    # dominated by a STATIC component (grid / orography), so shifting the month barely
    # changes it (8360.8 vs 8314.8). That is a defect in the control's premise, recorded
    # rather than tuned away. It is replaced by two controls that do have content:
    #
    # C2a  regridding a field onto its OWN grid must return it unchanged -- that tests the
    #      conservative regrid implementation itself.
    # C2b  the MONTH-TO-MONTH CHANGE must agree between the two sources. If ERA5 and R1 see
    #      the same atmosphere, their (Feb - Jan) differences correlate strongly; that is
    #      what makes the comparison meaningful despite the static offset.
    c2a = None
    sp = comparison.get('sp', {})
    if sp.get('r1_month_values'):
        base = np.array(sp['r1_month_values'], dtype=float)
        lat_s = np.array(sp['r1_lat'], dtype=float)
        lon_s = np.array(sp['r1_lon'], dtype=float)
        same = regrid_conservative(base, lat_s, lon_s, lat_s, lon_s)
        c2a = float(np.nanmax(np.abs(same - base)))
    c2b = None
    if sp.get('era_change') and sp.get('r1_change'):
        d_era = np.array(sp['era_change'], dtype=float)
        d_r1 = np.array(sp['r1_change'], dtype=float)
        if d_era.shape == d_r1.shape:
            g = np.isfinite(d_era) & np.isfinite(d_r1)
            if g.sum() > 10:
                c2b = float(np.corrcoef(d_era[g], d_r1[g])[0, 1])
    if not c1:
        FAILURES.append('C1 failed: the magnitude gate accepted sp in hPa')
    if c2a is not None and c2a > 1e-6:
        FAILURES.append(f'C2a failed: regridding onto the same grid changed the field by {c2a}')
    if c2b is not None and c2b <= 0.5:
        FAILURES.append(f'C2b failed: month-to-month changes disagree (r={c2b:.3f}) -- the two '
                        f'sources would not be seeing the same signal')
    log(f'  C1 单位注入被拒={c1}  C2a 同网格重网格最大改动={c2a}  '
        f'C2b 月际变化相关 r={c2b if c2b is None else round(c2b, 3)}')

    # ---- predictions
    era5_sst_units = comparison.get('sst', {}).get('era5_units')
    preds = [
        {'id': 'P1', 'claim': 'ERA5 sst 单位是 K', 'observed': era5_sst_units,
         'hit': era5_sst_units == 'K'},
        {'id': 'P2', 'claim': 'sp 偏差全局平均绝对值 < 2 hPa',
         'observed': abs(comparison.get('sp', {}).get('global', {}).get('bias_mean', 9e9)),
         'hit': abs(comparison.get('sp', {}).get('global', {}).get('bias_mean', 9e9)) < 200.0},
        {'id': 'P3', 'claim': '高原框 |偏差| 明显大于全球平均',
         'observed': {'plateau_abs': abs(comparison.get('sp', {}).get('regions', {}).get('plateau', {}).get('mean') or 0),
                      'global_abs': abs(comparison.get('sp', {}).get('global', {}).get('bias_mean', 0))},
         'hit': abs(comparison.get('sp', {}).get('regions', {}).get('plateau', {}).get('mean') or 0)
                > abs(comparison.get('sp', {}).get('global', {}).get('bias_mean', 0))},
        {'id': 'P4', 'claim': '500/850 零翻转、700 少于 50 格',
         'observed': {k: v['flipped_cells'] for k, v in flips.items()},
         'hit': flips.get('500', {}).get('flipped_cells', 9) == 0
                and flips.get('850', {}).get('flipped_cells', 9) == 0
                and flips.get('700', {}).get('flipped_cells', 99) < 50},
        {'id': 'P5', 'claim': '2026-09 可取 22 天', 'observed': len(days9),
         'hit': len(days9) == 22},
        {'id': 'P6', 'claim': '（**该条表述有缺陷，见 observed 注**）sst 偏差比 sp 偏差大',
         'observed': {'sp_global_std_Pa': comparison.get('sp', {}).get('global', {}).get('bias_std'),
                      'sst_global_std_K': comparison.get('sst', {}).get('global', {}).get('bias_std'),
                      'note': '把 Pa 的标准差与 K 的标准差比大小**没有意义**——该预测的表述本身不成立，'
                              '无论实测为何都不构成证据；保留原句以便看出是**预测写错**而不是数据异常',
                      'relative_std': {
                          'sp': (comparison.get('sp', {}).get('global', {}).get('bias_std') or 0)
                                / max(abs(comparison.get('sp', {}).get('global', {}).get('r1_range', [1, 1])[1] or 1), 1),
                          'sst': (comparison.get('sst', {}).get('global', {}).get('bias_std') or 0)
                                 / max(abs(comparison.get('sst', {}).get('global', {}).get('r1_range', [1, 1])[1] or 1), 1)}},
         'hit': (comparison.get('sst', {}).get('global', {}).get('bias_std') or 0)
                > (comparison.get('sp', {}).get('global', {}).get('bias_std') or 0)},
    ]

    verdict = 'instrument_failure' if FAILURES else 'feasible_pending_declaration'
    report = {
        'question_id': contract['question_id'], 'version': contract['version'],
        'generated_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'contract_sha256': cas.sha256_file(CONTRACT),
        'availability': avail, 'newest_day_seen': newest_full, 'server_day': server_day,
        'lag_days_vs_server': lag,
        'comparison_2026_02': {k: {kk: vv for kk, vv in v.items()
                                   if kk not in ('monthly_mean_era25', 'r1_month_values')}
                               for k, v in comparison.items()},
        'screening_flip_2026_02': flips,
        'current_month_partial_2026_09': current,
        'controls': {
            'C1_unit_injection_rejected': c1,
            'C2a_identity_regrid_max_change': c2a,
            'C2b_month_to_month_change_correlation': c2b,
            'C2_as_written_month_misalignment': {
                'result': 'FAILED and recorded as a control defect',
                'aligned_abs_mean': sp.get('aligned_abs_mean'),
                'misaligned_abs_mean': sp.get('misaligned_abs_mean'),
                'diagnosis': 'the difference is dominated by a STATIC component (grid/orography), '
                             'so shifting the month barely changes it; the premise was wrong, '
                             'not the data'},
        },
        'predictions': preds, 'predictions_hit': sum(1 for p in preds if p['hit']),
        'predictions_total': len(preds),
        'failures': FAILURES, 'verdict': verdict,
        'verdict_text': {
            'feasible_pending_declaration': '来源可达、单位与量级合格；能否用于 sp/sst 仍是**未作出的声明**',
            'instrument_failure': '闸门或对照不成立 ⇒ 不报判定'}[verdict],
        'residuals': [
            '只比了**一个重叠月**（2026-02）；一个月就是一个月',
            '只取 00/06/12/18Z 四个时次（与 R1 月平均的取样口径一致，但不是 ERA5 的全部 24 时次）',
            '层的**观测域掩码**（冻结件里的 *_domain）用的是 R1 **训练期最小值**，本件无法以 ERA5 重算那一步'
            '（要处理 1979–2014 共 432 个月）⇒ 本件回答的是「**某个月的**层压筛选是否翻转」，不是「域是否改变」',
            '2026-09 是**部分月**（到可取的最后一天），不是整月读数',
            '零凭据访问的是第三方公有桶；保留策略与可用性由 Google 决定，非我们能承诺',
        ],
        'wall_seconds': round(time.perf_counter() - started, 1),
    }
    (OUT / 'report.json').write_text(
        json.dumps(jsonable(report), ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    (OUT / 'run.log').write_text('\n'.join(LOG) + '\n')
    log(json.dumps({'verdict': verdict, 'predictions': f'{report["predictions_hit"]}/{report["predictions_total"]}',
                    'failures': FAILURES, 'wall_seconds': report['wall_seconds']}, ensure_ascii=False))
    return 1 if FAILURES else 0


if __name__ == '__main__':
    try:
        code = main()
    except BaseException as exc:                      # leave a trace, never exit silently
        import traceback
        OUT.mkdir(parents=True, exist_ok=True)
        tb = traceback.format_exc()
        FAILURES.append(f'{type(exc).__name__}: {exc}')
        (OUT / 'report.json').write_text(json.dumps({
            'question_id': 'xue.derived.era5-sp-sst-feasibility',
            'version': 'era5-sp-sst-feasibility-v1',
            'generated_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'verdict': 'instrument_failure', 'failures': FAILURES, 'traceback': tb,
        }, ensure_ascii=False, indent=2) + '\n')
        (OUT / 'run.log').write_text('\n'.join(LOG) + '\n')
        print('INSTRUMENT FAILURE:', exc, flush=True)
        print(tb, flush=True)
        code = 1
    sys.exit(code)
