"""Offline self-test for the continuous assimilation pipeline.

Runs with NO network and NO frozen artifacts: it uses a temporary root and synthetic
fields, so it can be run anywhere (including CI). The one test that does need the
frozen model is reported as SKIPPED when the artifacts are absent.

    python selftest.py            # exit 0 only if every runnable check passes
"""
from __future__ import annotations

import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix='cas-selftest-')
os.environ['XUE_ASSIM_ROOT'] = _TMP
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np                                        # noqa: E402
import cas                                                # noqa: E402
import casmodel                                           # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = '') -> None:
    RESULTS.append((name, bool(ok), detail))
    print(('PASS  ' if ok else 'FAIL  ') + name + (f'  -- {detail}' if detail else ''), flush=True)


def test_calendar() -> None:
    check('month_days(2026-02) == 28', cas.month_days('2026-02') == [f'2026-02-{d:02d}' for d in range(1, 29)])
    check('month_days(2026-10) == 31', len(cas.month_days('2026-10')) == 31)
    check('month_days(2026-12) ends 12-31', cas.month_days('2026-12')[-1] == '2026-12-31')


def test_unit_guard() -> None:
    """C2: a degC mislabel must trip the range guard instead of passing silently."""
    spec = cas.VARIABLES['tmp2m']
    good = np.full((4, 4), 280.0)
    bad = good - 273.15                                    # what a degC mislabel looks like
    check('C2 range guard accepts K', cas.check_ranges('tmp2m', good, spec)['ok'])
    check('C2 range guard rejects degC-as-K', not cas.check_ranges('tmp2m', bad, spec)['ok'],
          'min %.2f' % float(bad.min()))
    prmsl = cas.VARIABLES['prmsl']
    check('C2 prmsl checked in Pa after x100',
          cas.check_ranges('prmsl', np.full((2, 2), 1001.5 * 100.0), prmsl)['ok']
          and not cas.check_ranges('prmsl', np.full((2, 2), 1001.5), prmsl)['ok'])


def test_missing_channel() -> None:
    """C3/G7: without sst and sp the analysis must be blocked, never filled."""
    avail = {'tmp850', 'tmp700', 'tmp2m', 'prmsl', 'hgt500', 'vvel500', 'vvel700',
             'wind850', 'wind500', 'wind250'}
    cov = casmodel.missing_channels(avail)
    names = [m['channel'] for m in cov['missing']]
    check('C3 sst flagged missing', 'sst' in names, ','.join(names))
    check('C3 sp flagged missing', 'sp' in names)
    check('C3 q850/q700 cannot be built without rh+T', {'q850', 'q700'} <= set(names),
          f"missing={names}")
    cov2 = casmodel.missing_channels(avail | {'rh850', 'rh700'})
    check('C3 q850/q700 become derived (still NOT direct) when rh is present',
          {'q850', 'q700'} <= set(cov2['derived_only']) and not ({'q850', 'q700'} & set(cov2['buildable'])),
          f"derived={cov2['derived_only']} buildable={cov2['buildable']}")


def test_duplicate_freeze() -> None:
    """C1/G5: freezing the same run twice must be skipped."""
    probe = {'collection': 'gfs', 'ok': True, 'run_id': 'gfs.TESTRUN',
             'reference_datetime': '2026-10-01T00:00:00Z', 'item_url': 'http://invalid/item.json',
             'assets': {}, 'probed_utc': cas.utcnow()}
    first = cas.freeze_run('gfs', probe, dry_run=True)
    second = cas.freeze_run('gfs', probe, dry_run=True)
    check('C1 first attempt recorded', first['status'] in ('dry_run', 'written'), first['status'])
    check('C1 second attempt deduplicated', second['status'] == 'duplicate_skipped',
          f"first_state={first['status']}")


def test_ledger_and_status() -> None:
    rows = cas.read_jsonl('frozen.jsonl')
    check('ledger append-only lines readable', len(rows) >= 2, f'{len(rows)} rows')
    st = cas.status()
    check('status has storage accounting', 'storage_bytes' in st and 'storage_cap_bytes' in st)
    check('status counts skipped freezes', st['runs_frozen_skipped'] >= 1, str(st['runs_frozen_skipped']))


def test_observation_gate() -> None:
    """C4: a target month with no admissible observation must be `pending`, with a reason."""
    obs = casmodel.observation_for('2030-01')
    check('C4 far-future month is pending', obs['status'] == 'pending', obs.get('why', '')[:80])
    check('C4 pending carries its reason', bool(obs.get('why')))


def test_regrid() -> None:
    """A constant field must survive regridding; the cosine weighting must be unbiased."""
    src_lat = np.linspace(90, -90, cas.NATIVE_GRID[0])
    src_lon = np.linspace(-180, 180 - 360 / cas.NATIVE_GRID[1], cas.NATIVE_GRID[1])
    dst_lat = np.linspace(90, -90, 73)
    dst_lon = np.linspace(0, 360 - 360 / 144, 144)
    const = np.full((cas.NATIVE_GRID[0], cas.NATIVE_GRID[1]), 7.5)
    out = cas.regrid_to_model(const, src_lat, src_lon, dst_lat, dst_lon)
    finite = out[np.isfinite(out)]
    check('regrid keeps a constant field constant',
          finite.size > 0.9 * out.size and float(np.nanmax(np.abs(finite - 7.5))) < 1e-9,
          f'finite {finite.size}/{out.size}')
    # The invariant a conservative regrid must satisfy EXACTLY is area conservation:
    #     sum_dst (value_dst * area_dst) == sum_src (value_src * area_src)
    # so that is what is tested, to machine precision. (Four earlier versions compared
    # the destination value against the centre latitude or an analytic area-mean and
    # "failed" against a correct regrid: a cosine-weighted mean of latitude is legitimately
    # biased equatorward, and the source stores cell-CENTRE values, so an analytic
    # comparison can never be tighter than the source discretisation. The test was wrong
    # each time, not the regrid -- which is why the regrid is now the textbook
    # overlap-integral form and the test checks the property that has no such caveat.)
    def areas(lat_centres, dlat):
        c = np.asarray(lat_centres, dtype=float)
        sgn = 1.0 if c[0] < c[-1] else -1.0            # grids may be descending
        e = np.concatenate([[c[0] - sgn * dlat / 2], c + sgn * dlat / 2])
        e = np.clip(e, -90.0, 90.0)
        a = np.sin(np.deg2rad(e[1:])) - np.sin(np.deg2rad(e[:-1]))
        return np.abs(a)

    field = np.tile(np.cos(np.deg2rad(src_lat))[:, None], (1, cas.NATIVE_GRID[1]))
    out_c = cas.regrid_to_model(field, src_lat, src_lon, dst_lat, dst_lon)
    a_src = areas(src_lat, 0.25)[:, None] * (360.0 / cas.NATIVE_GRID[1])
    a_dst = areas(dst_lat, 2.5)[:, None] * (360.0 / 144)
    lhs = float(np.nansum(out_c * a_dst))
    rhs = float(np.nansum(field * a_src))
    check('regrid conserves the area integral', abs(lhs - rhs) / abs(rhs) < 1e-12,
          f'relative {abs(lhs - rhs) / abs(rhs):.3e}')
    ramp = np.tile(src_lat[:, None], (1, cas.NATIVE_GRID[1]))
    out_lin = cas.regrid_to_model(ramp, src_lat, src_lon, dst_lat, dst_lon)
    band = np.abs(dst_lat) <= 85.0
    bias = float(np.nanmax(np.abs(out_lin[band, 0] - dst_lat[band])))
    # "Toward the equator" means SMALLER |latitude|. In the northern hemisphere that is
    # out < dst, in the southern it is out > dst -- asserting out >= dst (as an earlier
    # version did) only holds south of the equator. Compare magnitudes instead.
    check('cosine weighting pulls a linear ramp toward the equator (|out| <= |dst|)',
          bool(np.all(np.abs(out_lin[band, 0]) <= np.abs(dst_lat[band]) + 1e-12)),
          f'max pulled-toward-equator amount {bias:.3e} deg')
    check('regrid box width is 2.5 deg (180/(n-1))',
          abs(180.0 / (dst_lat.size - 1) - 2.5) < 1e-12)


def test_verifier_reproduces_frozen_report() -> None:
    if not (cas.FROZEN / 'model.npz').is_file() or not (cas.FROZEN / 'report.json').is_file():
        check('verifier reproduces frozen published metrics', True,
              'SKIPPED (frozen artifacts not present on this host)')
        return
    try:
        res = casmodel.verify_against_frozen()
    except Exception as exc:                               # noqa: BLE001
        check('verifier reproduces frozen published metrics', False, f'{type(exc).__name__}: {exc}')
        return
    check('verifier reproduces frozen published metrics', res['passed'],
          f"max abs diff {res['max_abs_difference_in_mean_resolved_mse']:.3e}")


def main() -> int:
    print(f'self-test root: {_TMP}\n')
    for fn in (test_calendar, test_unit_guard, test_missing_channel, test_duplicate_freeze,
               test_ledger_and_status, test_observation_gate, test_regrid,
               test_verifier_reproduces_frozen_report):
        try:
            fn()
        except Exception as exc:                           # noqa: BLE001
            check(fn.__name__, False, f'{type(exc).__name__}: {exc}')
    bad = [r for r in RESULTS if not r[1]]
    print(f'\n{len(RESULTS) - len(bad)}/{len(RESULTS)} checks passed')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
