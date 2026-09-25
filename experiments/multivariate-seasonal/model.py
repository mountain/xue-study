"""Training-only seasonal normalization and coupled multi-lead EOF/ridge learner."""
from dataclasses import dataclass
import numpy as np

@dataclass
class SeasonalState:
    climatology: np.ndarray
    scale: np.ndarray

    def encode(self,c,months): return (c-self.climatology[months])/self.scale
    def decode(self,x,months): return x*self.scale+self.climatology[months]

def fit_state(c,months,train,blocks):
    if len(train)<24 or len(np.unique(months[train]))!=12: raise ValueError('Incomplete training seasons')
    clim=np.stack([c[train[months[train]==m]].mean(axis=0) for m in range(12)])
    a=c[train]-clim[months[train]]
    scale=np.zeros(c.shape[1])
    for start,stop in blocks:
        scale[start:stop]=max(float(np.sqrt(np.mean(np.sum(a[:,start:stop]**2,axis=1)))),1e-12)
    if np.any(scale==0): raise ValueError('Blocks must cover state')
    return SeasonalState(clim,scale)

def pairs(train,lead):
    targets=train[np.isin(train-lead,train)]
    return targets-lead,targets

def eof(x,train,max_rank):
    # Seasonal centering already gives zero mean over complete training years.
    return np.linalg.svd(x[train],full_matrices=False)[2][:max_rank].T

def fit_maps(x,train,vectors,penalty):
    projected=x@vectors
    maps=[]
    for lead in range(1,7):
        origin,target=pairs(train,lead)
        a=projected[origin]; b=x[target]; n=len(origin)
        maps.append(np.linalg.solve(a.T@a/n+penalty*np.eye(a.shape[1]),a.T@b/n))
    return np.stack(maps)

def predict(x,targets,vectors,maps):
    return np.stack([(x[targets-lead]@vectors)@maps[lead-1] for lead in range(1,7)])

def select(x,train,valid,ranks,penalties):
    all_vectors=eof(x,train,min(max(ranks),x.shape[1]))
    rows=[]; best=None
    for rank in sorted(set(min(r,x.shape[1]) for r in ranks)):
        vectors=all_vectors[:,:rank]
        for penalty in penalties:
            maps=fit_maps(x,train,vectors,penalty)
            predictions=predict(x,valid,vectors,maps)
            loss=float(np.mean(np.sum((predictions-x[valid][None,:,:])**2,axis=2)))
            rows.append({'rank':rank,'penalty':penalty,'validation_loss':loss})
            if best is None or loss<best[0]: best=(loss,vectors.copy(),maps,rows[-1])
    return best[1],best[2],best[3],rows

def independent_ar(x,train):
    origin,target=pairs(train,1)
    return np.clip(np.sum(x[origin]*x[target],axis=0)/np.maximum(np.sum(x[origin]**2,axis=0),1e-12),-.98,.98)

def score_coefficients(projection,predictions,targets,channels):
    """Exact area-weighted errors, including discarded spatial modes separately."""
    result={}
    for ch in channels:
        name=ch['name']; a,b=ch['start'],ch['stop']
        delta=predictions[:,:,a:b]-projection[name+'_c'][targets][None,:,:]
        g=projection[name+'_gram'][targets]
        mse=np.einsum('lti,tij,ltj->lt',delta,g,delta).mean(axis=1)
        full=mse+projection[name+'_residual'][targets].mean()
        result[name]={'resolved_mse':mse.tolist(),'full_mse':full.tolist(),
            'units':'log(kg kg-1)' if name.startswith('q') else ch['units']}
    return result

