"""Native-grid, masked scalar/vector spherical projections and scoring geometry."""
import json
import sys
from functools import lru_cache
import numpy as np
from scipy.interpolate import RegularGridInterpolator
from fields import HERE, INPUTS, ROOT, CHANNELS, COARSE, DEGREE
sys.path.insert(0,str(HERE.parent/'typed-spectrum'))
from spectrum import SphereBasis, latlon_points

def area_weights(lat, lon):
    lat = np.asarray(lat,dtype=float)
    assert np.all(np.diff(lat)<0)
    edges = np.r_[90., (lat[1:]+lat[:-1])/2, -90.]
    rows = np.sin(np.deg2rad(edges[:-1]))-np.sin(np.deg2rad(edges[1:]))
    return np.repeat(rows/(2*len(lon)),len(lon))

def load_field(code):
    with np.load(INPUTS/(code+'.npz')) as f:
        order=np.argsort(-f['lat']); order=order[abs(f['lat'][order])<89.999]
        return f['values'][:,order].astype(float), f['lat'][order], f['lon'].copy(), f['time'].copy()

@lru_cache(maxsize=4)
def geometry(lat,lon,degree):
    b=SphereBasis(latlon_points(np.asarray(lat,dtype=float),np.asarray(lon,dtype=float)),degree)
    return b, area_weights(lat,lon)

def interpolate_surface_pressure(lat,lon):
    values, slat, slon, _ = load_field('sp')
    # Periodic longitude seam; no extrapolation in latitude at pressure-grid points.
    values=np.concatenate([values,values[:,:,:1]],axis=2)
    interp=RegularGridInterpolator((slat[::-1],np.r_[slon,360.]),
        values[:,::-1].transpose(1,2,0),bounds_error=True)
    yy,xx=np.meshgrid(lat,lon,indexing='ij')
    return interp(np.stack([yy.ravel(),xx.ravel()],axis=1)).T

def masked_project(matrix, values, weights, masks):
    """Exclude invalid cells before arithmetic; retain exact observed-domain Gram.

    matrix (points, components, coefficients), values (times, points, components).
    Identical domains share a Gram solve. No regularization is hidden here.
    """
    nt,npoints,ncomponents=values.shape; p=matrix.shape[-1]
    assert matrix.shape[:2]==(npoints,ncomponents)
    valid=masks & np.isfinite(values).all(axis=2) & (weights[None,:]>0)
    groups={}
    for t,row in enumerate(valid): groups.setdefault(np.packbits(row).tobytes(),[]).append(t)
    coeff=np.empty((nt,p)); grams=[]; index=np.empty(nt,dtype=np.int32); residual=np.empty(nt)
    conditions=[]
    for times in groups.values():
        mask=valid[times[0]]
        if mask.sum()<p: raise ValueError('Insufficient domain')
        w=np.repeat(weights[mask]/weights[mask].sum(),ncomponents)
        b=matrix[mask].reshape(-1,p)
        y=values[times][:,mask].reshape(len(times),-1)
        g=b.T@(w[:,None]*b)
        condition=np.linalg.cond(g); conditions.append(float(condition))
        if condition>1e8: raise ValueError('Ill-conditioned observation domain')
        c=np.linalg.solve(g,(y@(w[:,None]*b)).T).T
        coeff[times]=c; index[times]=len(grams); grams.append(g)
        residual[times]=np.sum((y-c@b.T)**2*w,axis=1)
    bank=np.stack(grams)
    return coeff,bank,index,residual,{'distinct_domains':len(groups),
        'gram_storage_bytes':int(bank.nbytes+index.nbytes),
        'avoided_repeated_gram_bytes':int(nt*p*p*8-bank.nbytes-index.nbytes),
        'max_gram_condition':max(conditions),'min_area_fraction':float((valid@weights).min())}

def build(degree=DEGREE):
    ROOT.mkdir(parents=True,exist_ok=True)
    artifact=ROOT/f'projection-L{degree}.npz'
    if artifact.exists(): return artifact
    arrays={}; records=[]; offset=0
    pressure=None; reference_dates=None
    coarse=np.load(COARSE/'projection-L6.npz')
    for channel in CHANNELS:
        name=channel['name']; values,lat,lon,dates=load_field(channel['fields'][0])
        if reference_dates is None: reference_dates=dates
        if not np.array_equal(dates,reference_dates): raise ValueError('Misaligned channel dates')
        fields=[values.reshape(len(dates),-1)]
        for code in channel['fields'][1:]:
            v,la,lo,dt=load_field(code)
            assert np.array_equal(lat,la) and np.array_equal(lon,lo) and np.array_equal(dates,dt)
            fields.append(v.reshape(len(dates),-1))
        y=np.stack(fields,axis=2)
        training=dates<'2015-01'
        fixed=np.isfinite(y[training]).all(axis=(0,2))
        masks=np.broadcast_to(fixed,(len(dates),len(fixed))).copy()
        if channel['level'] is not None:
            if pressure is None: pressure=interpolate_surface_pressure(lat,lon)
            assert pressure.shape==masks.shape
            fixed &= pressure[training].min(axis=0)>=channel['level']*100
            masks &= fixed[None,:] & (pressure>=channel['level']*100)
        floor_count=0
        if name.startswith('q'):
            floor_count=int(((y[:,:,0]<1e-7)&masks).sum())
            y=np.log(np.maximum(y,1e-7))
        b,w=geometry(tuple(lat),tuple(lon),degree)
        matrix=b.vector if len(fields)==2 else b.scalar[:,None,:]
        if not np.array_equal(fixed.reshape(len(lat),len(lon)),coarse[name+'_domain']):
            raise ValueError('L12 and frozen L6 must use identical observation domains')
        c,g,gi,e,diag=masked_project(matrix,y,w,masks)
        size=c.shape[1]
        arrays[name+'_c']=c; arrays[name+'_gram_bank']=g; arrays[name+'_gram_index']=gi
        arrays[name+'_residual']=e
        arrays[name+'_domain']=fixed.reshape(len(lat),len(lon))
        arrays[name+'_lat']=lat; arrays[name+'_lon']=lon
        records.append({**channel,'start':offset,'stop':offset+size,
            'source_grid':[len(lat),len(lon)],'humidity_floor_count':floor_count,**diag})
        offset+=size
        print(json.dumps({'projected':name,'coefficients':size,**diag}),flush=True)
    arrays['dates']=dates
    arrays['coefficients']=np.concatenate([arrays[ch['name']+'_c'] for ch in CHANNELS],axis=1)
    arrays['channels_json']=np.array(json.dumps(records))
    arrays['degree']=np.array(degree)
    arrays['storage_schema']=np.array('unique-domain-gram-v1')
    np.savez_compressed(artifact,**arrays)
    return artifact

if __name__=='__main__': build()
