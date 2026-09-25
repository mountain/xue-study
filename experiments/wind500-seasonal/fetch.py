"""Cache the explicitly selected 500 hPa monthly means via HTTP ranges."""
import hashlib,json,time
from pathlib import Path
from datetime import datetime,timezone
import fsspec,numpy as np,xarray as xr
ROOT=Path('/home/ubuntu/xue-study/archive/wind500-seasonal-v1')
ROOT.mkdir(parents=True,exist_ok=True)
for name in ('uwnd','vwnd'):
 output=ROOT/f'{name}500.npz'
 if output.exists():
  print('cached',output,flush=True);continue
 url=f'https://downloads.psl.noaa.gov/Datasets/ncep.reanalysis.derived/pressure/{name}.mon.mean.nc'
 for attempt in range(3):
  try:
   with fsspec.open(url,block_size=65536,cache_type='blockcache') as f:
    with xr.open_dataset(f,engine='h5netcdf') as ds:
     field=ds[name].sel(level=500,time=slice('1979-01-01','2025-12-31')).load()
     assert field.attrs['units']=='m/s'
     assert np.isfinite(field.values).all() and abs(field.values).max()<180
     with output.with_suffix('.tmp').open('wb') as out:
      np.savez_compressed(out,values=field.values,time=field.time.values.astype('datetime64[M]').astype(str),lat=field.lat.values,lon=field.lon.values)
     output.with_suffix('.tmp').replace(output)
     receipt={'source':url,'selection':'level=500 hPa, 1979-01 through 2025-12','source_last_month':str(ds.time.values[-1]),'units':'m/s','shape':list(field.shape),'retrieved_utc':datetime.now(timezone.utc).isoformat(),'sha256':hashlib.sha256(output.read_bytes()).hexdigest()}
     output.with_suffix('.json').write_text(json.dumps(receipt,indent=2)+'\n')
     print(json.dumps(receipt),flush=True)
   break
  except Exception as e:
   print('retry',name,attempt,str(e),flush=True)
   if attempt==2:raise
   time.sleep(2)
