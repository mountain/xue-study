"""Download immutable local source snapshots and selected 1979–2025 fields."""
import concurrent.futures
from datetime import datetime, timezone
import hashlib
import json
import subprocess
import numpy as np
import xarray as xr
from fields import BASE, INPUTS, SOURCES

def fetch(source):
    path, key, units, scale, offset, selected = source
    INPUTS.mkdir(parents=True, exist_ok=True)
    local = INPUTS / path.replace('/', '__')
    if not local.exists():
        part = local.with_suffix('.part')
        subprocess.run(['curl','-fLsS','--retry','3','--max-time','600',
                        '-o',str(part),BASE+path], check=True)
        part.replace(local)
    source_hash = hashlib.sha256(local.read_bytes()).hexdigest()
    with xr.open_dataset(local, engine='h5netcdf') as ds:
        assert ds[key].attrs['units'] == units, (path, ds[key].attrs)
        for code, level in selected:
            dest = INPUTS / (code+'.npz')
            if dest.exists() and dest.with_suffix('.json').exists():
                print('cached', code, flush=True)
                continue
            field = ds[key].sel(time=slice('1979-01-01','2025-12-31'))
            if level is not None: field = field.sel(level=level)
            field = field.transpose('time','lat','lon').load()
            dates = field.time.values.astype('datetime64[M]').astype(str)
            assert len(dates)==564 and dates[0]=='1979-01' and dates[-1]=='2025-12'
            values = field.values.astype('float64')*scale+offset
            assert np.isfinite(values).any(axis=(1,2)).all()
            with dest.with_suffix('.tmp').open('wb') as f:
                np.savez_compressed(f, values=values.astype('float32'), time=dates,
                                    lat=field.lat.values, lon=field.lon.values)
            dest.with_suffix('.tmp').replace(dest)
            receipt = {'code':code,'url':BASE+path,'source_key':key,'source_units':units,
                'conversion':{'scale':scale,'offset':offset}, 'level_hpa':level,
                'months':[dates[0],dates[-1]],'shape':list(values.shape),
                'source_last_month':str(ds.time.values[-1]), 'source_sha256':source_hash,
                'sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),
                'retrieved_utc':datetime.now(timezone.utc).isoformat()}
            dest.with_suffix('.json').write_text(json.dumps(receipt,indent=2)+'\n')
            print(json.dumps(receipt),flush=True)

if __name__=='__main__':
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(fetch,SOURCES))

