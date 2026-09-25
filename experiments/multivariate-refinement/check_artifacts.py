"""Check frozen coarse identity, fine-grid nesting, replay and independent native scoring."""
from pathlib import Path
import hashlib,json
import numpy as np
from fields import ROOT,COARSE,DEGREE
from model import SeasonalState
from project import load_field,geometry

def main():
    public=Path('/home/ubuntu/climatetensor-xue/web/public')
    original=json.loads((ROOT/'coarse-preservation-before.json').read_text())
    assert all(hashlib.sha256((public/name).read_bytes()).hexdigest()==sha for name,sha in original.items())
    p=np.load(ROOT/'projection-L12.npz');cp=np.load(COARSE/'projection-L6.npz')
    channels=json.loads(str(p['channels_json']))
    for ch in channels:
        name=ch['name']
        np.testing.assert_array_equal(p[name+'_domain'],cp[name+'_domain'])
        assert np.all(p[name+'_residual']<=cp[name+'_residual']+1e-7),name
    f=np.load(ROOT/'forecast.npz'); sampled=np.load(ROOT/'forecast-on-coarse-grid.npz')
    old_f=np.load(COARSE/'forecast.npz'); m=np.load(ROOT/'model.npz')
    np.testing.assert_array_equal(f['lat'][::2],old_f['lat'])
    np.testing.assert_array_equal(f['lon'][::2],old_f['lon'])
    for ch in channels:
        for name in ch['fields']: np.testing.assert_array_equal(f[name][:,::2,::2],sampled[name])
    state=SeasonalState(m['climatology'],m['scale'])
    pred=state.decode((state.encode(m['coefficients'][-1],11)@m['vectors'])@m['maps'],np.arange(6))
    np.testing.assert_allclose(pred,f['coefficients'],rtol=0,atol=1e-12)
    assert np.nanmin(f['q850'])>0 and np.nanmin(f['q700'])>0
    # Direct native-grid wind errors, independently of stored Gram scoring.
    u,lat,lon,dates=load_field('u500');v,_,_,_=load_field('v500')
    targets=np.flatnonzero(dates>='2020-01')
    truth=np.stack([u[targets].reshape(len(targets),-1),v[targets].reshape(len(targets),-1)],axis=2)
    direct={}
    for degree,folder in [(6,COARSE),(12,ROOT)]:
        report=json.loads((folder/'report.json').read_text())
        ch=next(c for c in report['channels'] if c['name']=='wind500')
        back=np.load(folder/'backtest.npz');basis,weights=geometry(tuple(lat),tuple(lon),degree)
        for lead in [0,5]:
            predicted=np.einsum('tp,ncp->tnc',back['joint'][lead,:,ch['start']:ch['stop']],basis.vector)
            error=float(np.mean(np.sum(np.sum((predicted-truth)**2,axis=2)*weights,axis=1)))
            expected=report['metrics']['joint']['wind500']['full_mse'][lead]
            np.testing.assert_allclose(error,expected,rtol=1e-10)
            direct[f'L{degree}_lead{lead+1}']=error
    result={'preserved_coarse_objects':len(original),'all_coarse_hashes_unchanged':True,
        'same_observation_domains':True,'nested_projection_residual_nonincreasing':True,
        'saved_model_reproduces_forecast':True,'fine_model_coarse_grid_is_exact_subsample':True,
        'original_L6_is_not_replaced_by_subsample':True,'independent_native_wind_mse':direct,
        'positive_specific_humidity':True,'sst_minimum_K':float(np.nanmin(f['sst'])),
        'sst_below_source_floor_271_35_K':int(np.sum(f['sst']<271.35)),
        'sst_status':'Still unqualified against source physical lower bound; research download only, not a map layer.'}
    (ROOT/'quality-check.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
