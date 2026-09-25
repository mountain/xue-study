"""Stage 1: sixteen physical variables, thirteen scalar/vector channels.

This source adapter is NCEP R1 + ERSST v5, not the planned ERA5 adapter.
All stored fields use the logical registry's SI units. No radiation or snow
substitution is made; those channels await a separate source/units audit.
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
INPUTS = Path('/home/ubuntu/climatetensor-inputs/ncep-multivariate')
ROOT = HERE.parents[1] / 'archive/multivariate-seasonal-v1'
BASE = 'https://downloads.psl.noaa.gov/Datasets/'
# file, array key, source unit, scale, offset, [(logical name, pressure)]
SOURCES = [
    ('ncep.reanalysis.derived/pressure/air.mon.mean.nc', 'air', 'degC', 1., 273.15, [('t850', 850)]),
    ('ncep.reanalysis.derived/surface_gauss/air.2m.mon.mean.nc', 'air', 'degK', 1., 0., [('t2m', None)]),
    ('noaa.ersst.v5/sst.mnmean.nc', 'sst', 'degC', 1., 273.15, [('sst', None)]),
    ('ncep.reanalysis.derived/surface_gauss/pres.sfc.mon.mean.nc', 'pres', 'Pascals', 1., 0., [('sp', None)]),
    ('ncep.reanalysis.derived/surface/slp.mon.mean.nc', 'slp', 'millibars', 100., 0., [('msl', None)]),
    ('ncep.reanalysis.derived/pressure/hgt.mon.mean.nc', 'hgt', 'm', 9.80665, 0., [('z500', 500)]),
    ('ncep.reanalysis.derived/pressure/shum.mon.mean.nc', 'shum', 'grams/kg', .001, 0., [('q850', 850), ('q700', 700)]),
    ('ncep.reanalysis.derived/pressure/uwnd.mon.mean.nc', 'uwnd', 'm/s', 1., 0., [('u850', 850), ('u500', 500), ('u250', 250)]),
    ('ncep.reanalysis.derived/pressure/vwnd.mon.mean.nc', 'vwnd', 'm/s', 1., 0., [('v850', 850), ('v500', 500), ('v250', 250)]),
    ('ncep.reanalysis.derived/pressure/omega.mon.mean.nc', 'omega', 'Pascal/s', 1., 0., [('w500', 500), ('w700', 700)]),
]
CHANNELS = [
    {'name': name, 'fields': [name], 'units': units, 'level': level,
     'transform': 'log(q / 1 kg kg-1), floor=1e-7' if name.startswith('q') else 'identity'}
    for name, units, level in [('t850','K',850), ('t2m','K',None), ('sst','K',None),
        ('sp','Pa',None), ('msl','Pa',None), ('z500','m2 s-2',500),
        ('q850','kg kg-1',850), ('q700','kg kg-1',700),
        ('w500','Pa s-1',500), ('w700','Pa s-1',700)]
] + [{'name': f'wind{level}', 'fields': [f'u{level}',f'v{level}'],
      'units': 'm s-1', 'level': level, 'transform': 'identity'} for level in [850,500,250]]
