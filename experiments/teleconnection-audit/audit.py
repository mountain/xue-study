"""Finite source and three-region covariance audit. See frozen contract.json."""
from pathlib import Path
import csv,hashlib,json,sys,time
import numpy as np
import xarray as xr
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

HERE=Path(__file__).resolve().parent
STUDY=HERE.parents[1]
OUT=STUDY/'archive/teleconnection-audit-v1'
sys.path.insert(0,str(HERE.parent/'multivariate-refinement'))
from project import geometry,area_weights,load_field
from fields import INPUTS,ROOT,COARSE
CONTRACT=json.loads((HERE/'contract.json').read_text())
REGIONS=CONTRACT['regions']
PAIRS=[(0,1),(0,2),(1,2)]


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def corr(a):return np.corrcoef(a,rowvar=False)


def seasonal(a,month,train):
    return np.stack([a[train&(month==m)].mean(axis=0) for m in range(12)])


def surrogates(a,rng,n):
    a=a-a.mean(axis=0);f=np.fft.rfft(a,axis=0)
    phase=rng.uniform(0,2*np.pi,(n,len(f),a.shape[1]))
    s=f[None]*np.exp(1j*phase);s[:,0]=0
    if len(a)%2==0:s[:,-1]=f[-1]*rng.choice([-1,1],(n,a.shape[1]))
    return np.fft.irfft(s,n=len(a),axis=1)


def batch_corr(a):
    a=a-a.mean(axis=1,keepdims=True)
    a=a/np.sqrt(np.sum(a*a,axis=1,keepdims=True))
    return np.stack([np.sum(a[:,:,i]*a[:,:,j],axis=1) for i,j in PAIRS],axis=1)


def holm(p):
    order=np.argsort(p);out=np.empty(len(p));largest=0.
    for k,i in enumerate(order):
        largest=max(largest,(len(p)-k)*p[i]);out[i]=min(1,largest)
    return out


def uncertainty(a,n=1999):
    rng=np.random.default_rng(20260924);observed=np.array([corr(a)[i,j] for i,j in PAIRS])
    s=surrogates(a,rng,n)
    np.testing.assert_allclose(np.abs(np.fft.rfft(s[0],axis=0))[1:],np.abs(np.fft.rfft(a-a.mean(axis=0),axis=0))[1:],atol=1e-10)
    null=batch_corr(s)
    p=(1+(abs(null)>=abs(observed)).sum(axis=0))/(n+1)
    block=24
    starts=rng.integers(0,len(a),(n,int(np.ceil(len(a)/block))))
    indices=((starts[:,:,None]+np.arange(block))%len(a)).reshape(n,-1)[:,:len(a)]
    boot=batch_corr(a[indices]);ci=np.quantile(boot,[.025,.975],axis=0)
    years=len(a)//12
    shifted=np.array([[np.corrcoef(a[:,i],np.roll(a[:,j],12*k))[0,1] for i,j in PAIRS] for k in range(1,years)])
    pshift=(1+(abs(shifted)>=abs(observed)).sum(axis=0))/years
    rows=[{'pair':[REGIONS[i]['id'],REGIONS[j]['id']],'r':float(observed[k]),
        'bootstrap_CI95':ci[:,k].tolist(),'phase_null_p':float(p[k]),'phase_null_p_Holm3':float(holm(p)[k]),
        'whole_year_circular_shift_p':float(pshift[k]),'whole_year_shift_p_Holm3':float(holm(pshift)[k])}
        for k,(i,j) in enumerate(PAIRS)]
    return rows,{'phase_null_correlations':null,'bootstrap_correlations':boot,'whole_year_shift_correlations':shifted}


def regional(u,v,lat,lon,domain,small=False):
    weights=area_weights(lat,lon).reshape(len(lat),len(lon));out=[];counts=[]
    for r in REGIONS:
        la,lo=r['lat'],r['lon']
        if small:la=[r['point'][0]-5,r['point'][0]+5];lo=[r['point'][1]-10,r['point'][1]+10]
        mask=(lat[:,None]>=la[0])&(lat[:,None]<=la[1])&(lon[None,:]>=lo[0])&(lon[None,:]<=lo[1])&domain
        assert np.isfinite(u[:,mask]).all() and np.isfinite(v[:,mask]).all()
        w=weights[mask];w/=w.sum();uu=u[:,mask]@w;vv=v[:,mask]@w
        out.append(np.stack([uu,vv,np.hypot(uu,vv),np.hypot(u[:,mask],v[:,mask])@w],axis=1));counts.append(int(mask.sum()))
    return np.stack(out,axis=1),counts


def calibration():
    rng=np.random.default_rng(1717);n=1200;t=np.arange(n);month=t%12;train=t<840
    noise=rng.normal(size=(n,3))
    for k in range(1,n):noise[k]=.5*noise[k-1]+noise[k]
    annual=20*np.cos(t*2*np.pi/12)[:,None]
    a=annual+noise;clim=seasonal(a,month,train);res=a-clim[month]
    poisoned=a.copy();poisoned[~train]+=1e8
    np.testing.assert_array_equal(clim,seasonal(poisoned,month,train))
    shared=rng.normal(size=n)
    for k in range(1,n):shared[k]=.7*shared[k-1]+shared[k]
    b=annual+noise+3*shared[:,None];b-=seasonal(b,month,train)[month]
    raw=np.array([corr(a)[i,j] for i,j in PAIRS]);ind=np.array([corr(res)[i,j] for i,j in PAIRS]);coupled=np.array([corr(b)[i,j] for i,j in PAIRS])
    assert raw.min()>.98 and abs(ind).max()<.12 and coupled.min()>.85
    return {'seed':1717,'sample_months':n,'common_annual_cycle_raw_r':raw.tolist(),
        'independent_AR_anomaly_r':ind.tolist(),'injected_shared_AR_anomaly_r':coupled.tolist(),
        'future_poison_does_not_change_season_fit':True,'scope':'finite instrument calibration, not a significance theorem'}


def main():
    start=time.monotonic();OUT.mkdir(exist_ok=True)
    if (OUT/'result.json').exists():raise FileExistsError('Completed audit exists; preserve this version')
    cal=calibration();(OUT/'calibration.json').write_text(json.dumps(cal,indent=2)+'\n')
    u,lat,lon,dates=load_field('u500');v,vlat,vlon,vdates=load_field('v500')
    np.testing.assert_array_equal(lat,vlat);np.testing.assert_array_equal(lon,vlon);np.testing.assert_array_equal(dates,vdates)
    provenance=[]
    for code,key,values in [('u500','uwnd',u),('v500','vwnd',v)]:
        receipt=json.loads((INPUTS/(code+'.json')).read_text());path=INPUTS/receipt['url'].split('/Datasets/')[1].replace('/','__')
        assert sha(path)==receipt['source_sha256'] and sha(INPUTS/(code+'.npz'))==receipt['sha256']
        with xr.open_dataset(path,engine='h5netcdf') as ds:
            selected=ds[key].sel(level=500,time=slice('1979-01-01','2025-12-31')).transpose('time','lat','lon')
            order=np.argsort(-selected.lat.values);order=order[abs(selected.lat.values[order])<89.999]
            np.testing.assert_array_equal(selected.values[:,order],values)
            assert ds[key].attrs['units']=='m/s'
        provenance.append({**receipt,'raw_snapshot_path':str(path),'raw_to_npz_500hPa_exact':True})
    month=dates.astype('datetime64[M]').astype(int)%12;train=dates<'2015-01'
    projection=np.load(ROOT/'projection-L12.npz');domain=projection['wind500_domain']
    a,counts=regional(u,v,lat,lon,domain);clim=seasonal(a,month,train);anomaly=a-clim[month]
    t=np.arange(len(dates));design=np.c_[np.ones(len(t)),(t-t[train].mean())/12]
    trend=np.linalg.lstsq(design[train],anomaly[train].reshape(train.sum(),-1),rcond=None)[0]
    detrended=anomaly-(design@trend).reshape(anomaly.shape)
    fields=['u','v','vector_speed','mean_grid_vector_speed'];historical={}
    for k,name in enumerate(fields):
        historical[name]={'raw_r':corr(a[:,:,k]).tolist(),'seasonal_cycle_r':corr(clim[:,:,k]).tolist(),
            'anomaly_r':corr(anomaly[:,:,k]).tolist(),'train_anomaly_r':corr(anomaly[train,:,k]).tolist(),
            'later_2015_2025_anomaly_r':corr(anomaly[~train,:,k]).tolist(),
            'DJF_anomaly_r':corr(anomaly[np.isin(month,[11,0,1]),:,k]).tolist(),
            'detrended_anomaly_r':corr(detrended[:,:,k]).tolist()}
    primary,simulation=uncertainty(anomaly[:,:,2])
    small,_=regional(u,v,lat,lon,domain,small=True);sm=small-seasonal(small,month,train)[month]
    sensitivity={name:corr(sm[:,:,k]).tolist() for k,name in enumerate(fields)}
    # Derive the quoted climatological speeds independently at fixed coordinates.
    source_points=[];forecasts={};columns=[]
    for r in REGIONS:
        i=np.flatnonzero(lat==r['point'][0])[0];j=np.flatnonzero(lon==r['point'][1])[0]
        p=np.c_[u[:,i,j],v[:,i,j]];c=seasonal(p,month,train)
        row={'region':r['id'],'lat':float(lat[i]),'lon':float(lon[j]),'training_years':36,
             'native_monthly_mean_u_v':c.tolist(),'native_speed_of_mean_vector':np.linalg.norm(c,axis=1).tolist(),
             'January_mean_speed_of_monthly_vectors':float(np.mean(np.linalg.norm(p[train&(month==0)],axis=1)))}
        source_points.append(row);columns.append(p)
    point_data=np.concatenate(columns,axis=1)
    with (OUT/'source-point-monthly.csv').open('w') as f:
        writer=csv.writer(f);writer.writerow(['month']+[r['id']+'_'+c for r in REGIONS for c in ['u_m_s','v_m_s']])
        writer.writerows([[d,*x] for d,x in zip(dates,point_data)])
    for degree,folder in [(6,COARSE),(12,ROOT)]:
        model=np.load(folder/'model.npz');fc=np.load(folder/'forecast.npz')
        ch=next(c for c in json.loads(str(model['channels_json'])) if c['name']=='wind500');sl=slice(ch['start'],ch['stop'])
        b,_=geometry(tuple(lat),tuple(lon),degree)
        c=np.einsum('tp,ncp->tnc',model['climatology'][:6,sl],b.vector).reshape(6,len(lat),len(lon),2)
        pred=np.einsum('tp,ncp->tnc',fc['coefficients'][:,sl],b.vector).reshape(6,len(lat),len(lon),2)
        f,_=regional(pred[:,:,:,0],pred[:,:,:,1],lat,lon,domain)
        c,_=regional(c[:,:,:,0],c[:,:,:,1],lat,lon,domain)
        forecasts[f'L{degree}']={'months':fc['months'].tolist(),'region_u_v_speed_mean_grid_speed':f.tolist(),
            'spectral_background':c.tolist(),'learned_difference':(f-c).tolist(),
            'speed_correlation_six_frames_DESCRIPTIVE':corr(f[:,:,2]).tolist(),
            'background_speed_correlation_six_frames_DESCRIPTIVE':corr(c[:,:,2]).tolist(),
            'speed_difference_correlation_six_frames_DESCRIPTIVE':corr((f-c)[:,:,2]).tolist(),
            'sample_months':6,'independent_samples':False,'forecast_sha256':sha(folder/'forecast.npz')}
        for k,r in enumerate(REGIONS):
            pb,_=geometry((r['point'][0],),(r['point'][1],),degree)
            vec=np.einsum('tp,ncp->tnc',model['climatology'][:6,sl],pb.vector)[:,0]
            pvec=np.einsum('tp,ncp->tnc',fc['coefficients'][:,sl],pb.vector)[:,0]
            source_points[k][f'L{degree}_background_u_v']=vec.tolist()
            source_points[k][f'L{degree}_background_speed']=np.linalg.norm(vec,axis=1).tolist()
            source_points[k][f'L{degree}_forecast_u_v']=pvec.tolist()
            source_points[k][f'L{degree}_forecast_speed']=np.linalg.norm(pvec,axis=1).tolist()
    with (OUT/'regional-monthly.csv').open('w') as f:
        writer=csv.writer(f);writer.writerow(['month']+[r['id']+'_'+k for r in REGIONS for k in fields]+[r['id']+'_'+k+'_anomaly' for r in REGIONS for k in fields])
        writer.writerows([[d,*x.ravel(),*y.ravel()] for d,x,y in zip(dates,a,anomaly)])
    np.savez_compressed(OUT/'simulations.npz',**simulation)
    np.savez_compressed(OUT/'series.npz',dates=dates,physical=a,climatology=clim,anomaly=anomaly,detrended_anomaly=detrended)
    result={'contract_sha256':sha(HERE/'contract.json'),'adva_commit':'1ecd29b47d216b4e1c482d61a1c3e68252f8a07b',
       'native_adva_certificate':False,'regions':REGIONS,'region_gridpoint_counts':counts,'source_receipts':provenance,
       'source_point_background':source_points,'samples':{'all':len(dates),'train':int(train.sum()),'later':int((~train).sum()),'DJF':int(np.isin(month,[11,0,1]).sum())},
       'historical':historical,'primary_inference':primary,'small_box_sensitivity':sensitivity,'forecasts':forecasts,
       'calibration':cal,'limits':CONTRACT['limits'],'elapsed_seconds':time.monotonic()-start}
    plot(result,a,anomaly,dates)
    (OUT/'result.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'source_background':[{k:p[k] for k in ['region','native_speed_of_mean_vector','L12_background_speed','L12_forecast_speed']} for p in source_points],
                     'primary_inference':primary,'historical':historical,'small_box_sensitivity':sensitivity,'elapsed_seconds':result['elapsed_seconds']},indent=2))


def plot(result,a,anomaly,dates):
    labels=['East Asia','N. America','Middle East'];colors=['#087e8b','#be5b28','#7b4c9a']
    fig,axs=plt.subplots(2,3,figsize=(14,8),layout='constrained')
    fc=result['forecasts']['L12'];f=np.array(fc['region_u_v_speed_mean_grid_speed']);c=np.array(fc['spectral_background'])
    for k,label in enumerate(labels):
        axs[0,0].plot(np.arange(1,7),f[:,k,2],color=colors[k],label=label)
        axs[0,0].plot(np.arange(1,7),c[:,k,2],color=colors[k],ls='--')
        axs[0,1].plot(np.arange(1,7),f[:,k,2]-c[:,k,2],color=colors[k],label=label)
    axs[0,0].set(title='L12 speed: forecast solid / seasonal dashed',xlabel='2026 month',ylabel='m/s');axs[0,0].legend(fontsize=8)
    axs[0,1].set(title='L12 learned speed difference: only six frames',xlabel='2026 month',ylabel='m/s');axs[0,1].axhline(0,color='.6',lw=.6)
    for ax,name,title in [(axs[0,2],'raw_r','Native monthly speed: raw r'),(axs[1,0],'anomaly_r','Native speed: calendar-month anomalies'),(axs[1,1],'later_2015_2025_anomaly_r','Native speed anomalies: 2015-2025')]:
        mat=np.array(result['historical']['vector_speed'][name]);im=ax.imshow(mat,vmin=-1,vmax=1,cmap='RdBu_r')
        ax.set_xticks(range(3),labels,rotation=20,fontsize=8);ax.set_yticks(range(3),labels,fontsize=8);ax.set_title(title,fontsize=10)
        for i in range(3):
            for j in range(3):ax.text(j,i,f'{mat[i,j]:.2f}',ha='center',va='center',color='white' if abs(mat[i,j])>.65 else 'black')
        fig.colorbar(im,ax=ax,shrink=.7)
    for k,(i,j) in enumerate(PAIRS):
        r=result['primary_inference'][k];lo,hi=r['bootstrap_CI95']
        axs[1,2].errorbar(r['r'],k,xerr=[[r['r']-lo],[hi-r['r']]],fmt='o',capsize=3,color=colors[k])
    axs[1,2].set_yticks(range(3),[f'{labels[i]} / {labels[j]}' for i,j in PAIRS],fontsize=8)
    axs[1,2].set(title='Native anomaly r: 24-month block CI',xlabel='Pearson r',xlim=(-1,1));axs[1,2].axvline(0,color='.5',lw=.6)
    fig.suptitle('Three-region 500 hPa audit: seasonal phase is structure, not noise\nSame-source monthly reanalysis; association does not establish a causal pathway',fontsize=12)
    fig.savefig(OUT/'three-region-audit.png',dpi=160);plt.close(fig)


if __name__=='__main__':main()
