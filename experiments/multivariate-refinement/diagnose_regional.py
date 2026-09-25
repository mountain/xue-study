"""Post-publication spatial audit; never alter the frozen models or forecasts.

Separate native training climatology, its spectral representation, learned
anomaly and cached January/February 2026 reanalysis (excluded from fitting).
"""
from pathlib import Path
import sys,json
import numpy as np
import xarray as xr
from scipy.interpolate import RegularGridInterpolator
from scipy.ndimage import maximum_filter
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from fields import ROOT,COARSE,INPUTS
from project import geometry,load_field,area_weights

OUT=ROOT.parent/'regional-audit-20260924'
OUT.mkdir(exist_ok=True)


def load_future(fragment,key,level=None):
    file=next(INPUTS.glob('*'+fragment+'*nc'))
    with xr.open_dataset(file,engine='h5netcdf') as ds:
        a=ds[key].sel(time=slice('2026-01-01','2026-02-28'))
        if level is not None:a=a.sel(level=level)
        a=a.transpose('time','lat','lon').load()
        order=np.argsort(-a.lat.values)
        order=order[abs(a.lat.values[order])<89.999]
        return a.values[:,order].astype(float),a.lat.values[order],a.lon.values,str(file)


def interp(values,lat,lon,target_lat,target_lon):
    yy,xx=np.meshgrid(target_lat,target_lon,indexing='ij')
    extended=np.concatenate([values,values[:,:,:1]],axis=2)
    f=RegularGridInterpolator((lat[::-1],np.r_[lon,360]),extended[:,::-1].transpose(1,2,0))
    return f(np.stack([yy.ravel(),xx.ravel()],axis=1)).T.reshape(len(values),len(target_lat),len(target_lon))


def borders(ax,global_map=False):
    geo=json.loads(Path('/home/ubuntu/climatetensor-xue/web/public/countries.geojson').read_text())
    for feature in geo['features']:
        g=feature['geometry']; polygons=g['coordinates'] if g['type']=='MultiPolygon' else [g['coordinates']]
        for poly in polygons:
            xy=np.array(poly[0])
            if global_map:
                xy[:,0]%=360
                cuts=np.where(abs(np.diff(xy[:,0]))>180)[0]+1
                for part in np.split(xy,cuts):ax.plot(part[:,0],part[:,1],color='0.25',lw=.35)
            else:ax.plot(xy[:,0],xy[:,1],color='0.25',lw=.4)


def peaks(a,lat,lon,number=3):
    z=np.where(np.isfinite(a)&(lat[:,None]>10)&(lat[:,None]<75),a,-np.inf)
    local=maximum_filter(z,size=(9,21),mode=('nearest','wrap'))
    ij=np.argwhere((z==local)&np.isfinite(z))
    ij=sorted(ij,key=lambda p:z[tuple(p)],reverse=True)
    result=[]
    for i,j in ij:
        if any(min(abs(float(lon[j])-r['lon']),360-abs(float(lon[j])-r['lon']))<40 for r in result):continue
        result.append({'lat':float(lat[i]),'lon':float(lon[j]),'value':float(z[i,j])})
        if len(result)==number:break
    return result


def main():
    result={'scope':'post-publication diagnosis, no refit or changed scientific files',
        'reference_climatology':'native 1979-2014 calendar-month means',
        'verification':'cached January/February 2026 NCEP R1, excluded from model training, selection and prior development backtest',
        'temperature_is':'2 metre air temperature, not land skin or soil temperature',
        'plateau_box':'28-36N, 80-100E; geographic box, not an elevation mask',
        'months':['2026-01','2026-02','2026-03','2026-04','2026-05','2026-06'],
        'models':{}}
    native,lat,lon,dates=load_field('t2m')
    month=dates.astype('datetime64[M]').astype(int)%12
    climate=np.stack([native[(dates<'2015-01')&(month==k)].mean(axis=0) for k in range(6)])
    actual,alat,alon,source=load_future('surface_gauss__air.2m','air')
    np.testing.assert_array_equal(lat,alat);np.testing.assert_array_equal(lon,alon)
    result['verification_temperature_source']=source
    box=(lat[:,None]>=28)&(lat[:,None]<=36)&(lon[None,:]>=80)&(lon[None,:]<=100)
    weight=area_weights(lat,lon).reshape(len(lat),len(lon))*box;weight/=weight.sum()
    mean=lambda a:np.sum(a*weight,axis=(-2,-1))
    temp_plot={}
    rlat=np.arange(45,19.9,-1.25);rlon=np.arange(65,110.1,1.25)
    points=[('plateau centre',32.5,87.5),('Lhasa vicinity',29.65,91.1)]
    wind_native={}
    for key in ['u500','v500']:
        values,wlat,wlon,wdates=load_field(key)
        wind_native[key]=np.stack([values[(wdates<'2015-01')&(month==k)].mean(axis=0) for k in range(6)])
    uactual,_,_,_=load_future('pressure__uwnd','uwnd',500)
    vactual,_,_,_=load_future('pressure__vwnd','vwnd',500)
    wind_fig,axs=plt.subplots(3,3,figsize=(17,9),layout='constrained')
    clim_u,clim_v=wind_native['u500'],wind_native['v500']
    wind_draw=[('Native training climate: January speed',np.hypot(clim_u[0],clim_v[0]),0,45,'viridis'),
       ('Native training climate: June speed',np.hypot(clim_u[5],clim_v[5]),0,45,'viridis'),
       ('Native climate: Jan to June vector change',np.hypot(clim_u[5]-clim_u[0],clim_v[5]-clim_v[0]),0,30,'magma')]
    for ax,(title,z,lo,hi,cm) in zip(axs[0],wind_draw):
        ax.pcolormesh(wlon,wlat,z,vmin=lo,vmax=hi,cmap=cm,shading='auto');ax.set_title(title,fontsize=10)
    for row,(degree,folder) in enumerate([(6,COARSE),(12,ROOT)],start=1):
        model=np.load(folder/'model.npz');forecast=np.load(folder/'forecast.npz')
        channels=json.loads(str(model['channels_json']))
        tch=next(c for c in channels if c['name']=='t2m');sl=slice(tch['start'],tch['stop'])
        basis,_=geometry(tuple(lat),tuple(lon),degree)
        reconstruction=(model['climatology'][:6,sl]@basis.scalar.T).reshape(6,len(lat),len(lon))
        predicted=(forecast['coefficients'][:,sl]@basis.scalar.T).reshape(6,len(lat),len(lon))
        anomaly=predicted-reconstruction
        # A diagnostic ablation only: restore the native training climatology,
        # without fitting to 2026 data or replacing either published forecast.
        restored=climate+anomaly
        np.testing.assert_allclose(predicted[:2]-actual,
            (reconstruction[:2]-climate[:2])+anomaly[:2]+(climate[:2]-actual),atol=1e-12)
        tag=f'L{degree}'
        r={'plateau_box_mean_C':{'native_climate':(mean(climate)-273.15).tolist(),
              'spectral_climate':(mean(reconstruction)-273.15).tolist(),
              'forecast':(mean(predicted)-273.15).tolist(),'actual_Jan_Feb':(mean(actual)-273.15).tolist()},
           'plateau_box_mean_bias_K':{'representation':mean(reconstruction-climate).tolist(),
              'learned_anomaly':mean(anomaly).tolist(),
              'forecast_minus_actual_Jan_Feb':mean(predicted[:2]-actual).tolist(),
              'native_climate_minus_actual_Jan_Feb':mean(climate[:2]-actual).tolist()},
           'plateau_box_RMSE_Jan_Feb_K':np.sqrt(mean((predicted[:2]-actual)**2)).tolist(),
           'diagnostic_native_background_restored_NOT_PUBLISHED':{
               'formula':'native 1979-2014 monthly climatology + unchanged learned spectral anomaly',
               'plateau_bias_Jan_Feb_K':mean(restored[:2]-actual).tolist(),
               'plateau_RMSE_Jan_Feb_K':np.sqrt(mean((restored[:2]-actual)**2)).tolist(),
               'scope':'two-month diagnostic ablation, not a newly validated or published forecast'},
           'points':[]}
        for label,y,x in points:
            one=lambda a:interp(a,lat,lon,np.array([y]),np.array([x]))[:,0,0]
            # For a point, evaluate the model exactly rather than interpolate its reconstruction.
            pb,_=geometry((y,),(x,),degree)
            pc=(model['climatology'][:6,sl]@pb.scalar.T)[:,0]
            pf=(forecast['coefficients'][:,sl]@pb.scalar.T)[:,0]
            r['points'].append({'label':label,'lat':y,'lon':x,'reference_sampling':'bilinear native-grid reference; exact spectral model',
                'native_climate_C':(one(climate)-273.15).tolist(),'spectral_climate_C':(pc-273.15).tolist(),
                'forecast_C':(pf-273.15).tolist(),'actual_Jan_Feb_C':(one(actual)-273.15).tolist(),
                'representation_bias_K':(pc-one(climate)).tolist(),'learned_anomaly_K':(pf-pc).tolist()})
        rb,_=geometry(tuple(rlat),tuple(rlon),degree)
        temp_plot[tag]=(forecast['coefficients'][0,sl]@rb.scalar.T).reshape(len(rlat),len(rlon))-273.15
        temp_plot[tag+'_bias']=((model['climatology'][0,sl]@rb.scalar.T).reshape(len(rlat),len(rlon))
                                -interp(climate[:1],lat,lon,rlat,rlon)[0])
        temp_plot[tag+'_anomaly']=((forecast['coefficients'][0,sl]-model['climatology'][0,sl])@rb.scalar.T).reshape(len(rlat),len(rlon))
        wch=next(c for c in channels if c['name']=='wind500');ws=slice(wch['start'],wch['stop'])
        wb,_=geometry(tuple(wlat),tuple(wlon),degree)
        wc=np.einsum('tp,ncp->tnc',model['climatology'][:6,ws],wb.vector).reshape(6,len(wlat),len(wlon),2)
        wf=np.einsum('tp,ncp->tnc',forecast['coefficients'][:,ws],wb.vector).reshape(6,len(wlat),len(wlon),2)
        speed=np.linalg.norm(wf,axis=-1);wdelta=wf[5]-wf[0];cdelta=wc[5]-wc[0]
        wa=wf-wc
        nh=wlat>0
        r['wind500']={'units':'m/s','monthly_NH_max_speed':np.nanmax(speed[:,nh],axis=(1,2)).tolist(),
           'monthly_NH_max_vector_step':np.nanmax(np.linalg.norm(np.diff(wf,axis=0),axis=-1)[:,nh],axis=(1,2)).tolist(),
           'Jan_June_vector_change_max':float(np.nanmax(np.linalg.norm(wdelta,axis=-1)[nh])),
           'Jan_June_speed_change_max_abs':float(np.nanmax(abs(speed[5]-speed[0])[nh])),
           'NH_max_learned_anomaly_vector':np.nanmax(np.linalg.norm(wa,axis=-1)[:,nh],axis=(1,2)).tolist(),
           'January_speed_peaks':peaks(speed[0],wlat,wlon),
           'Jan_June_vector_change_peaks':peaks(np.linalg.norm(wdelta,axis=-1),wlat,wlon),
           'native_January_speed_peaks':peaks(np.hypot(clim_u[0],clim_v[0]),wlat,wlon),
           'actual_January_speed_peaks':peaks(np.hypot(uactual[0],vactual[0]),wlat,wlon)}
        for p in r['wind500']['Jan_June_vector_change_peaks']:
            i=np.argmin(abs(wlat-p['lat']));j=np.argmin(abs(wlon-p['lon']))
            p['spectral_climate_vector_change']=float(np.linalg.norm(cdelta[i,j]))
            p['learned_anomaly_vector_change']=float(np.linalg.norm(wdelta[i,j]-cdelta[i,j]))
            p['native_climate_vector_change']=float(np.hypot(clim_u[5,i,j]-clim_u[0,i,j],clim_v[5,i,j]-clim_v[0,i,j]))
        for ax,title,z,hi,cm in zip(axs[row],[f'{tag} forecast: January speed',f'{tag} forecast: June speed',f'{tag}: Jan to June vector change'],
                                  [speed[0],speed[5],np.linalg.norm(wdelta,axis=-1)],[45,45,30],['viridis','viridis','magma']):
            im=ax.pcolormesh(wlon,wlat,z,vmin=0,vmax=hi,cmap=cm,shading='auto');ax.set_title(title,fontsize=10)
            if row==2:wind_fig.colorbar(im,ax=axs[:,list(axs[row]).index(ax)],label='m/s',shrink=.65)
        result['models'][tag]=r
    for ax in axs.ravel():
        borders(ax,True);ax.set_xlim(0,360);ax.set_ylim(0,80);ax.set_xticks([0,90,180,270,360]);ax.set_yticks([0,30,60])
    wind_fig.suptitle('500 hPa monthly vector winds: absolute speed versus seasonal change (not gusts)')
    wind_fig.savefig(OUT/'wind-decomposition.png',dpi=150);plt.close(wind_fig)
    fig,axs=plt.subplots(2,4,figsize=(17,8),layout='constrained')
    native_c=interp(climate[:1],lat,lon,rlat,rlon)[0]-273.15
    actual_c=interp(actual[:1],lat,lon,rlat,rlon)[0]-273.15
    panels=[('Native January training climate',native_c,-30,30,'coolwarm'),
        ('L6 January forecast',temp_plot['L6'],-30,30,'coolwarm'),
        ('L12 January forecast',temp_plot['L12'],-30,30,'coolwarm'),
        ('January 2026 reanalysis (not fitted)',actual_c,-30,30,'coolwarm'),
        ('L6 seasonal representation bias',temp_plot['L6_bias'],-20,20,'RdBu_r'),
        ('L12 seasonal representation bias',temp_plot['L12_bias'],-20,20,'RdBu_r'),
        ('L12 learned temperature anomaly',temp_plot['L12_anomaly'],-3,3,'RdBu_r'),
        ('L12 forecast minus Jan 2026 reanalysis',temp_plot['L12']-actual_c,-20,20,'RdBu_r')]
    for ax,(title,z,lo,hi,cm) in zip(axs.ravel(),panels):
        im=ax.pcolormesh(rlon,rlat,z,vmin=lo,vmax=hi,cmap=cm,shading='auto')
        borders(ax);ax.set_xlim(65,110);ax.set_ylim(20,45);ax.set_title(title,fontsize=10)
        ax.plot([80,100,100,80,80],[28,28,36,36,28],'k--',lw=.7)
        ax.plot(87.5,32.5,'ko',ms=3);fig.colorbar(im,ax=ax,shrink=.7,label='°C / K difference')
    fig.suptitle('Tibetan Plateau: 2 m air temperature; January; no elevation correction applied')
    fig.savefig(OUT/'plateau-decomposition.png',dpi=160);plt.close(fig)
    (OUT/'diagnosis.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
