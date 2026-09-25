import unittest
import numpy as np
from model import fit_state,eof,fit_maps,predict,select,pairs
from project import masked_project

class ScientificChecks(unittest.TestCase):
    def test_future_poison_does_not_change_fit_or_selection(self):
        rng=np.random.default_rng(4); c=rng.normal(size=(144,8));months=np.arange(144)%12
        train=np.arange(96);valid=np.arange(96,120); blocks=[(0,4),(4,8)]
        altered=c.copy();altered[120:]=1e9
        s=fit_state(c,months,train,blocks);t=fit_state(altered,months,train,blocks)
        np.testing.assert_array_equal(s.climatology,t.climatology)
        np.testing.assert_array_equal(s.scale,t.scale)
        for data in [c,altered]:
            state=s.encode(data,months)
            result=select(state,train,valid,[2,4],[.1,1.])
            if data is c: first=result
            else:
                np.testing.assert_array_equal(result[0],first[0])
                np.testing.assert_array_equal(result[1],first[1])
                self.assertEqual(result[2:],first[2:])
        for lead in range(1,7):
            a,b=pairs(train,lead); self.assertTrue(np.all(b<96));self.assertTrue(np.all(b-a==lead))

    def test_actual_cross_variable_learning(self):
        rng=np.random.default_rng(12);x=rng.normal(size=(500,2))
        x[1:,1]=x[:-1,0]+.02*rng.normal(size=499)
        train=np.arange(350);test=np.arange(351,500)
        v=eof(x,train,2);m=fit_maps(x,train,v,.001)
        y=predict(x,test,v,m)[0,:,1]
        self.assertLess(np.mean((y-x[test,1])**2),.005)
        self.assertGreater(abs((v@m[0])[0,1]),.95)

    def test_masked_poison_and_exact_error_decomposition(self):
        rng=np.random.default_rng(1);b=rng.normal(size=(40,2,6));y=rng.normal(size=(4,40,2))
        weights=np.ones(40)/40;masks=np.ones((4,40),bool);masks[:,25:]=False
        c,g,e,_=masked_project(b,y,weights,masks)
        poisoned=y.copy();poisoned[:,25:]=np.nan
        cp,gp,ep,_=masked_project(b,poisoned,weights,masks)
        np.testing.assert_array_equal(c,cp);np.testing.assert_array_equal(e,ep)
        pred=rng.normal(size=(4,6));delta=pred-c
        direct=np.mean(np.sum((np.einsum('tp,ncp->tnc',pred,b[:25])-y[:,:25])**2,axis=2),axis=1)
        np.testing.assert_allclose(direct,np.einsum('ti,tij,tj->t',delta,g,delta)+e,atol=1e-12)

    def test_channel_units_do_not_change_normalized_state(self):
        rng=np.random.default_rng(7);c=rng.normal(size=(60,6));months=np.arange(60)%12
        blocks=[(0,3),(3,6)];s=fit_state(c,months,np.arange(48),blocks)
        converted=c*np.array([1000]*3+[.001]*3)
        t=fit_state(converted,months,np.arange(48),blocks)
        np.testing.assert_allclose(s.encode(c,months),t.encode(converted,months),atol=1e-13)

if __name__=='__main__': unittest.main()
