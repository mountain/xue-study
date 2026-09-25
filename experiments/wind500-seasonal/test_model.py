import unittest
import numpy as np
from train import basis,fit,forecast
class ScientificChecks(unittest.TestCase):
 def test_solid_rotation_and_gradient(self):
  lat=np.arange(87.5,-90,-2.5);lon=np.arange(0,360,2.5)
  B,W,G,labels=basis(lat,lon)
  self.assertLess(float(abs(G-np.eye(len(labels))).max()),.006)
  shape=(len(lat),len(lon));east=np.broadcast_to(np.cos(np.deg2rad(lat))[:,None],shape).ravel();zero=np.zeros_like(east)
  for field,family in [(np.r_[east,zero],'toroidal'),(np.r_[zero,east],'poloidal')]:
   c=np.linalg.solve(G,B.T@(W*field));p=c@B.T
   self.assertLess(float(np.max(abs(p-field))),1e-10)
   keep=np.array([r['l']==1 and r['m']==0 and r['family']==family for r in labels])
   self.assertLess(float(abs(c[~keep]).max()),1e-10)
 def test_heldout_cannot_change_fit(self):
  rng=np.random.default_rng(1301);c=rng.normal(size=(120,6));m=np.arange(120)%12;train=np.arange(84)
  a=fit(c,m,train);c[84:]=1e9;b=fit(c,m,train)
  for x,y in zip(a,b):np.testing.assert_array_equal(x,y)
 def test_zero_anomaly_and_even_mask(self):
  clim=np.arange(72,dtype=float).reshape(12,6);rho=np.full(6,.5);c=clim[0].copy()
  np.testing.assert_array_equal(forecast(c,0,clim,rho,3,np.ones(6),1),clim[3])
  c+=2;mask=np.array([0,1,0,1,0,1]);pred=forecast(c,0,clim,rho,2,mask,1)
  np.testing.assert_array_equal(pred-clim[2],mask*.5)
 def test_insufficient_training_rejected(self):
  with self.assertRaises(ValueError):fit(np.ones((12,2)),np.arange(12),np.arange(12))
if __name__=='__main__':unittest.main()
