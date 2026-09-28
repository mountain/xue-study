"""External reference: what the operational CFSv2 says about 2026-12.

Not our model's output. Single ensemble member, raw absolute values, no
anomalisation against hindcast climatology and no skill mask -- therefore NOT
the official CPC seasonal product (that one uses ensembles, anomalies and
historical skill). Recorded only as a same-target-period counterpart.

Reads over HTTPS from the xue data service; writes one JSON report.
"""
import json
from pathlib import Path

import numpy as np
import xarray as xr

RUN = 'cfs.2026092512'
BASE = f'https://dataset.ringsaturn.me/xue/{RUN}'
OUT = Path('/home/ubuntu/xue-study/archive/cfs-reference-2026-12-v1')
TARGET_MONTHS = ['2026-10', '2026-11', '2026-12', '2027-01']
REGIONS = {'east_asia': (25., 40., 130., 170.),
           'north_america': (32.5, 47.5, 280., 310.),      # 280-310E == 80-50W
           'middle_east': (20., 35., 35., 65.)}
NINO34 = (-5., 5., 190., 240.)                            # 5S-5N, 170W-120W (== 190-240E)


def month_mean(da, month):
    """Mean over the six-hourly steps whose valid time falls in `month`."""
    sel = da.sel(time=da.time.dt.strftime('%Y-%m') == month)
    if sel.sizes['time'] == 0:
        return None, 0
    return sel.mean('time'), int(sel.sizes['time'])


def area_mean(field, lat, lon, box):
    la0, la1, lo0, lo1 = box
    lonx = np.where(lon < 0, lon + 360., lon)
    box_lon = ((lo0 + 180) % 360) - 180, ((lo1 + 180) % 360) - 180
    mlat = np.where((lat >= la0) & (lat <= la1))[0]
    if box_lon[0] <= box_lon[1]:
        mlon = np.where((lon >= box_lon[0]) & (lon <= box_lon[1]))[0]
    else:                                                  # box crosses the dateline
        mlon = np.where((lon >= box_lon[0]) | (lon <= box_lon[1]))[0]
    block = field[np.ix_(mlat, mlon)]
    w = np.cos(np.deg2rad(lat[mlat]))[:, None] * np.ones((1, len(mlon)))
    return float(np.nansum(block * w) / np.nansum(np.isfinite(block) * w))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    if (OUT / 'report.json').exists():
        raise FileExistsError('reference report already exists')
    wind = xr.open_zarr(f'{BASE}/wind500.half.zarr')
    lat = np.asarray(wind.latitude.values)
    lon = np.asarray(wind.longitude.values)
    u, v = wind['ugrd500'], wind['vgrd500']

    speeds, steps, hgt = {}, {}, {}
    for month in TARGET_MONTHS:
        um, n = month_mean(u, month)
        vm, _ = month_mean(v, month)
        steps[month] = n
        speeds[month] = {k: float(np.hypot(area_mean(um.values, lat, lon, b),
                                          area_mean(vm.values, lat, lon, b)))
                         for k, b in REGIONS.items()}
    try:
        h = xr.open_zarr(f'{BASE}/hgt500.half.zarr')['hgt500']
        for month in TARGET_MONTHS:
            hm, _ = month_mean(h, month)
            hgt[month] = float(area_mean(hm.values, lat, lon, (30., 60., 0., 360.)))
    except Exception as exc:                                # keep the wind result either way
        hgt = {'error': f'{type(exc).__name__}: {exc}'}

    nino = {}
    try:
        ts = xr.open_zarr(f'{BASE}/tmpsfc.half.zarr')['tmpsfc']
        tlat = np.asarray(ts.latitude.values)
        tlon = np.asarray(ts.longitude.values)
        for month in TARGET_MONTHS:
            tm, _ = month_mean(ts, month)
            raw = area_mean(tm.values, tlat, tlon, NINO34)
            # tmpsfc arrives in degrees Celsius on this service; only convert if it looks like Kelvin
            nino[month] = round(raw - 273.15 if raw > 100. else raw, 3)
    except Exception as exc:
        nino = {'error': f'{type(exc).__name__}: {exc}'}

    report = {
        'reference': 'external operational CFSv2, NOT this project\'s model output',
        'run': RUN,
        'source': BASE,
        'member': '01 (single member)',
        'cadence': '6-hourly; monthly means computed from valid times within each month',
        'grid': f'{len(lat)}x{len(lon)} (~2 deg)',
        'caveats': [
            'single member, raw absolute values',
            'not anomalised against hindcast climatology; no skill mask',
            'therefore not the official CPC seasonal product',
            'this project\'s own model cannot reach these months (its inputs end 2026-02, so 2026-12 would be lead 10)'],
        'target_months': TARGET_MONTHS,
        'six_hourly_steps_per_month': steps,
        'region_500hPa_vector_mean_speed_ms': speeds,
        'nino34_tmpsfc_proxy_degC': nino,
        'nino34_proxy_note': 'proxy: CFSv2 surface temperature over 5S-5N/170W-120W (this service stores it in degC); '
                             'not an SST analysis and not the CPC ONI',
        'hgt500_zonal_mean_30_60N_m': hgt,
    }
    (OUT / 'report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
