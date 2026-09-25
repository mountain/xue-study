"""Train, select on validation only, report development backtests, write forecasts."""
from datetime import datetime, timezone
import hashlib
import json
import numpy as np
from scipy.interpolate import RegularGridInterpolator
from fields import HERE, INPUTS, ROOT, CHANNELS
from project import build, geometry, load_field, interpolate_surface_pressure
from model import fit_state, select, predict, independent_ar, score_coefficients

def physical_humidity(projection,predictions,targets,channels):
    result={}
    for ch in channels:
        name=ch['name']
        if not name.startswith('q'): continue
        truth,lat,lon,_=load_field(name); truth=truth[targets].reshape(len(targets),-1)
        b,w=geometry(tuple(lat),tuple(lon),6)
        valid=projection[name+'_domain'].ravel()[None,:] & np.isfinite(truth)
        valid &= interpolate_surface_pressure(lat,lon)[targets]>=ch['level']*100
        weights=valid*w[None,:]; weights/=weights.sum(axis=1)[:,None]
        observed=np.where(valid,truth,0.)
        result[name]={}
        for model,coeff in predictions.items():
            errors=[]
            for lead in range(6):
                fields=np.exp(coeff[lead,:,ch['start']:ch['stop']]@b.scalar.T)
                assert np.isfinite(fields).all()
                errors.append(float(np.sqrt(np.mean(np.sum((fields-observed)**2*weights,axis=1)))))
            result[name][model]={'full_rmse_kg_kg':errors}
    return result

def forecast_grids(projection,coeff,channels):
    lat=np.arange(87.5,-90.,-2.5);lon=np.arange(0.,360.,2.5)
    basis,_=geometry(tuple(lat),tuple(lon),6)
    yy,xx=np.meshgrid(lat,lon,indexing='ij');points=np.stack([yy.ravel(),xx.ravel()],axis=1)
    output={}; domains={}
    for ch in channels:
        name=ch['name']; a,b=ch['start'],ch['stop']
        matrix=basis.vector if len(ch['fields'])==2 else basis.scalar[:,None,:]
        f=np.einsum('tp,ncp->tnc',coeff[:,a:b],matrix)
        if name.startswith('q'): f=np.exp(f)
        native_lat=projection[name+'_lat']; native_lon=projection[name+'_lon']
        domain=projection[name+'_domain'].astype(float)
        domain=np.c_[domain,domain[:,0]]
        interp=RegularGridInterpolator((native_lat[::-1],np.r_[native_lon,360.]),
            domain[::-1],method='nearest',bounds_error=False,fill_value=0.)
        mask=interp(points)>=.5
        domains[name]=mask.reshape(len(lat),len(lon))
        for k,code in enumerate(ch['fields']):
            value=f[:,:,k].reshape(6,len(lat),len(lon))
            output[code]=np.where(domains[name][None,:,:],value,np.nan).astype('float32')
    # Static training-derived domains plus predicted surface pressure screening.
    for ch in channels:
        if ch['level'] is not None:
            for code in ch['fields']:
                output[code]=np.where(output['sp']>=ch['level']*100,output[code],np.nan)
    return {'lat':lat,'lon':lon,**output}

def main():
    contract=json.loads((HERE/'contract.json').read_text())
    path=build()
    with np.load(path) as p: projection={k:p[k] for k in p.files}
    c=projection['coefficients']; dates=projection['dates']
    months=dates.astype('datetime64[M]').astype(int)%12
    assert np.all(np.diff(dates.astype('datetime64[M]').astype(int))==1)
    train=np.where(dates<'2015-01')[0]
    valid=np.where((dates>='2015-01')&(dates<'2020-01'))[0]
    test=np.where(dates>='2020-01')[0]
    assert (len(train),len(valid),len(test))==(432,60,72)
    channels=json.loads(str(projection['channels_json']))
    blocks=[(ch['start'],ch['stop']) for ch in channels]
    state=fit_state(c,months,train,blocks); x=state.encode(c,months)
    vectors,maps,chosen,candidates=select(x,train,valid,contract['ranks'],contract['ridge_mean_loss_penalties'])
    print('selected joint',json.dumps(chosen),flush=True)
    learned=predict(x,test,vectors,maps)
    independent=np.zeros_like(learned); solo_selection={}; solo_models={}
    forecast=(x[-1]@vectors)@maps
    for ch in channels:
        a,b=ch['start'],ch['stop']
        v,m,selection,rows=select(x[:,a:b],train,valid,contract['ranks'],contract['ridge_mean_loss_penalties'])
        independent[:,:,a:b]=predict(x[:,a:b],test,v,m)
        solo_selection[ch['name']]={'chosen':selection,'candidates':rows}
        solo_models[ch['name']+'_vectors']=v;solo_models[ch['name']+'_maps']=m
        print('selected independent',ch['name'],json.dumps(selection),flush=True)
    rho=independent_ar(x,train)
    predictions={'climatology':np.zeros_like(learned),
        'persistence':np.stack([x[test-lead] for lead in range(1,7)]),
        'independent_ar1':np.stack([x[test-lead]*rho**lead for lead in range(1,7)]),
        'independent_channels':independent,'joint':learned}
    aggregate={name:np.mean(np.sum((p-x[test])**2,axis=2),axis=1).tolist() for name,p in predictions.items()}
    physical={name:state.decode(p,months[test]) for name,p in predictions.items()}
    metrics={name:score_coefficients(projection,p,test,channels) for name,p in physical.items()}
    for name,fields in metrics.items():
        for field,scores in fields.items():
            base=metrics['climatology'][field]
            scores['resolved_skill_vs_climatology']=(1-np.array(scores['resolved_mse'])/base['resolved_mse']).tolist()
            scores['full_skill_vs_climatology']=(1-np.array(scores['full_mse'])/base['full_mse']).tolist()
    humidity=physical_humidity(projection,physical,test,channels)
    # Input/output coupling norms in the normalized physical-channel coordinates.
    coupling=np.empty((6,len(channels),len(channels)))
    for lead in range(6):
        operator=vectors@maps[lead]
        for i,(a,b) in enumerate(blocks):
            for j,(s,e) in enumerate(blocks):coupling[lead,i,j]=np.linalg.norm(operator[a:b,s:e])
    target_months=np.array(contract['target_months'])
    target_indices=target_months.astype('datetime64[M]').astype(int)%12
    forecast_coeff=state.decode(forecast,target_indices)
    output=forecast_grids(projection,forecast_coeff,channels)
    np.savez_compressed(ROOT/'forecast.npz',months=target_months,coefficients=forecast_coeff,**output)
    np.savez_compressed(ROOT/'model.npz',climatology=state.climatology,scale=state.scale,
        vectors=vectors,maps=maps,rho=rho,coefficients=c,dates=dates,
        channels_json=projection['channels_json'],**solo_models)
    np.savez_compressed(ROOT/'backtest.npz',target_months=dates[test],
                        **{name:value for name,value in physical.items()})
    report={'version':contract['version'],'generated_utc':datetime.now(timezone.utc).isoformat(),
        'status':'historical-origin experimental monthly forecast; not operational weather',
        'initial_month':'2025-12','target_months':target_months.tolist(),
        'native_adva':False,'assimilation':False,'degree':6,'grid_step_degrees':2.5,
        'training':contract['training'],'validation':contract['validation'],
        'development_backtest':contract['development_backtest'],'prior_exposure':contract['prior_exposure'],
        'samples':{'training':len(train),'validation':len(valid),'development_backtest':len(test)},
        'physical_variables':sum(len(ch['fields']) for ch in channels),'channels':channels,
        'spectral_coefficients':c.shape[1],'selected':chosen,'validation_candidates':candidates,
        'independent_channel_selection':solo_selection,'metrics':metrics,
        'normalized_total_coefficient_mse':aggregate,'physical_humidity':humidity,
        'coupling':{'axes':['lead','input_channel','output_channel'],
                    'channel_order':[ch['name'] for ch in channels],'block_frobenius_norms':coupling.tolist(),
                    'interpretation':'Statistical prediction coefficients, not causal influence'},
        'forecast_ranges':{k:{'min':float(np.nanmin(v)),'max':float(np.nanmax(v)),
                              'finite_fraction':float(np.isfinite(v).mean())} for k,v in output.items() if k not in ['lat','lon']},
        'sources':[json.loads((INPUTS/(code+'.json')).read_text()) for ch in channels for code in ch['fields']],
        'contract_sha256':hashlib.sha256((HERE/'contract.json').read_bytes()).hexdigest(),
        'projection_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
        'resolution_ladder':contract['resolution_ladder'],'deferred_fields':contract['deferred_fields'],
        'limitations':['Only large scales L6, not local weather or typhoon lifecycle',
            'Frames are calendar-month means; animation interpolation has no submonthly forecast meaning',
            'Monthly pressure masking cannot guarantee every underlying hourly sample was above ground',
            'Observed-domain SST harmonic extension is not a land sea-temperature observation',
            'No energy, mass, humidity conservation or causal identification imposed',
            'No new untouched confirmatory test; no independent observations or historical as-of archive',
            'Native resolution was not increased in this stage; output grid spacing is not forecast information resolution']}
    (ROOT/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'selected':chosen,'joint_500hPa':metrics['joint']['wind500'],
                      'aggregate_mse':aggregate},indent=2),flush=True)

if __name__=='__main__':main()

