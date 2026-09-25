"""Finite numerical prototype. Fit only the declared past; test never tunes it."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json
import numpy as np
from scipy.special import sph_harm_y
ROOT=Path('/home/ubuntu/xue-study/archive/wind500-seasonal-v1')
HERE=Path(__file__).resolve().parent

def basis(lat,lon,degree=6):
    theta,phi=np.meshgrid(np.deg2rad(90-lat),np.deg2rad(lon),indexing='ij')
    columns=[]; labels=[]
    for l in range(1,degree+1):
        for m in range(l+1):
            y,dy=sph_harm_y(l,m,theta,phi,diff_n=1)
            for phase in (['real'] if m==0 else ['real','imag']):
                norm=np.sqrt(4*np.pi/(l*(l+1)))*(1 if m==0 else np.sqrt(2))
                east=getattr(dy[...,1],phase)/np.sin(theta)*norm
                north=-getattr(dy[...,0],phase)*norm
                for family,u,v in [('toroidal',-north,east),('poloidal',east,north)]:
                    columns.append(np.r_[u.ravel(),v.ravel()])
                    labels.append(dict(l=l,m=m,phase=phase,family=family))
    B=np.stack(columns,axis=1)
    w=np.broadcast_to(np.cos(np.deg2rad(lat))[:,None],theta.shape).ravel().copy();w/=w.sum()
    W=np.r_[w,w]
    G=B.T@(W[:,None]*B)
    return B,W,G,labels

def fit(coeff,months,train):
    if len(train)<24 or len(set(months[train]))!=12:raise ValueError('at least two years covering all months required')
    clim=np.stack([coeff[train[months[train]==m]].mean(axis=0) for m in range(12)])
    anom=coeff-clim[months]
    pairs=train[1:]; pairs=pairs[np.isin(pairs-1,train)]
    x=anom[pairs-1];y=anom[pairs]
    rho=np.clip((x*y).sum(axis=0)/np.maximum((x*x).sum(axis=0),1e-12),-.98,.98)
    return clim,rho

def forecast(c,month,clim,rho,lead,mask,shrink):
    return clim[(month+lead)%12]+(c-clim[month])*((rho*shrink)**lead)*mask

def score(coeff,months,targets,clim,rho,mask,shrink,G):
    out=[]
    for lead in range(1,7):
        origin=targets-lead
        pred=forecast(coeff[origin],months[origin],clim,rho,lead,mask,shrink)
        d=pred-coeff[targets]
        err=np.einsum('ni,ij,nj->n',d,G,d)
        out.append(float(err.mean()))
    return out

def main():
    u=np.load(ROOT/'uwnd500.npz');v=np.load(ROOT/'vwnd500.npz')
    for k in ('time','lat','lon'):assert np.array_equal(u[k],v[k]),k
    dates=u['time']; months=dates.astype('datetime64[M]').astype(int)%12
    assert np.array_equal(np.diff(dates.astype('datetime64[M]').astype(int)),np.ones(len(dates)-1))
    lat=u['lat'][1:-1];lon=u['lon'];n=len(lat)*len(lon)
    fields=np.concatenate([u['values'][:,1:-1].reshape(len(dates),-1),v['values'][:,1:-1].reshape(len(dates),-1)],axis=1).astype(float)
    B,W,G,labels=basis(lat,lon)
    coeff=np.linalg.solve(G,(fields@(W[:,None]*B)).T).T
    residual=fields-coeff@B.T
    residual_mse=np.sum(residual**2*W,axis=1)
    train=np.where(dates<'2015-01')[0];valid=np.where((dates>='2015-01')&(dates<'2020-01'))[0];test=np.where((dates>='2020-01')&(dates<='2025-12'))[0]
    assert len(train)==432 and len(valid)==60 and len(test)==72
    clim,rho=fit(coeff,months,train)
    even=np.array([r['family']=='toroidal' and r['l']%2==0 for r in labels],float)
    masks={'full':np.ones(len(labels)),'even':even}
    chosen={};validation={}
    for name,mask in masks.items():
        rows=[{'shrink':s,'mse_by_lead':score(coeff,months,valid,clim,rho,mask,s,G)} for s in [0.,.25,.5,.75,1.]]
        winner=min(rows,key=lambda r:np.mean(r['mse_by_lead']))
        chosen[name]=winner['shrink'];validation[name]=rows
    baseline=score(coeff,months,test,clim,rho,np.zeros(len(labels)),0,G)
    metrics={}
    for name in ['climatology','persistence','full','even']:
        if name=='climatology':mse=baseline
        elif name=='persistence':mse=score(coeff,months,test,clim,np.ones_like(rho),np.ones(len(labels)),1,G)
        else:mse=score(coeff,months,test,clim,rho,masks[name],chosen[name],G)
        metrics[name]=[{'lead_months':i+1,'samples':len(test),'spectral_vector_rmse_ms':float(np.sqrt(x)),'resolved_vector_rmse_ms':float(np.sqrt(x+residual_mse[test].mean())),'skill_vs_climatology':float(1-x/baseline[i])} for i,x in enumerate(mse)]
    # A reproducible historical origin, after the untouched test interval.
    origin=int(np.where(dates=='2025-12')[0][0]); targetmonths=np.arange(np.datetime64('2026-01'),np.datetime64('2026-07'),dtype='datetime64[M]')
    outputs={}
    for name,mask in masks.items():
        c=np.stack([forecast(coeff[origin],months[origin],clim,rho,h,mask,chosen[name]) for h in range(1,7)])
        f=c@B.T
        outputs[name+'_u']=f[:,:n].reshape(6,len(lat),len(lon)).astype('float32')
        outputs[name+'_v']=f[:,n:].reshape(6,len(lat),len(lon)).astype('float32')
    np.savez_compressed(ROOT/'forecast.npz',lat=lat,lon=lon,months=targetmonths.astype(str),**outputs)
    np.savez_compressed(ROOT/'model.npz',climatology=clim,rho=rho,coefficients=coeff,months=months,dates=dates,gram=G)
    contract=HERE/'contract.json'
    report={'version':'climatetensor-wind500-spectral-ar1-v1','generated_utc':datetime.now(timezone.utc).isoformat(),'status':'historical-origin experimental forecast; not a current operational forecast','native_adva':False,'assimilation':False,'initial_month':'2025-12','reference_run_time':'2026-01-01T00:00:00Z','target_months':targetmonths.astype(str).tolist(),'training':['1979-01','2014-12'],'validation':['2015-01','2019-12'],'test':['2020-01','2025-12'],'degree':6,'coefficients':len(labels),'retained_even_anomaly_coefficients':int(even.sum()),'grid_step_degrees':2.5,'spatial_resolution_note':'degree 6 large-scale field, not 2.5 degree forecast skill; excludes exact pole rows','monthly_statistic':'Each frame is a calendar-month average, timestamped at the middle of that month; intermediate animation is display interpolation only','selected_shrinkage':chosen,'validation_candidates':validation,'metrics':metrics,'gram_max_error':float(abs(G-np.eye(len(labels))).max()),'projection_residual_vector_rmse_ms':float(np.sqrt(residual_mse[test].mean())),'contract_sha256':hashlib.sha256(contract.read_bytes()).hexdigest(),'sources':[json.loads((ROOT/f'{var}500.json').read_text()) for var in ('uwnd','vwnd')],'limitations':['Reanalysis verification, not independent observations or operational as-of testing','Monthly target averages, not instantaneous weather; skill not established for local weather or hazards','Only degrees 1–6; higher-frequency spatial structures omitted','Historical December 2025 initial state; generated September 2026, not available in real time at that origin','Even-only means even toroidal anomaly plus full seasonal climatology','No native Adva learner or assimilation is executed']}
    (ROOT/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'selected_shrinkage':chosen,'metrics':metrics,'gram_max_error':report['gram_max_error']},indent=2))
if __name__=='__main__':main()
