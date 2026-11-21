"""Proposal-specific causality, bounds and physical execution tests."""
import unittest
from dataclasses import replace
import numpy as np
from proposal_study import margins,apply_margins,raw_forecasts,run
from src.experiment import make_trace
from src.scheduling import Config,capacity

class ProposalTests(unittest.TestCase):
    def test_fixed_margins_preserve_current_observed_channel(self):
        g=np.array([2.,2.]);a=np.array([1.,1.]);h=np.array([.5,.5])
        gg,aa,hh=apply_margins(g,a,h,np.array([.38,1.,.25]),'fixed_margin')
        self.assertEqual(gg[0],2.);self.assertLess(gg[1],g[1])
        self.assertTrue(np.all(aa>=a));self.assertTrue(np.all(hh<=h))
        np.testing.assert_array_equal(g,[2.,2.])

    def test_margin_ablations_and_zero_floor(self):
        history=[(-1.,2.,-3.)]*20
        np.testing.assert_allclose(margins(history,'adaptive_all'),[0.,2.,0.])
        np.testing.assert_allclose(margins(history,'adaptive_channel'),[0.,0.,0.])
        np.testing.assert_allclose(margins(history,'adaptive_arrival'),[0.,2.,0.])
        np.testing.assert_allclose(margins(history,'adaptive_harvest'),[0.,0.,0.])

    def test_causal_prediction_ignores_unobserved_future(self):
        trace=make_trace(8,seed=75)
        altered={k:np.array(v,copy=True) for k,v in trace.items()}
        for key in ('arrival','harvest'):altered[key][5:]+=100
        altered['gain'][5:]=.2;altered['condition'][5:]='Worst'
        cfg=replace(Config(),horizon=4)
        original=run(trace,cfg,'adaptive_all');changed=run(altered,cfg,'adaptive_all')
        np.testing.assert_allclose(original.p.iloc[:5],changed.p.iloc[:5],atol=1e-7)
        np.testing.assert_allclose(original.d.iloc[:5],changed.d.iloc[:5],atol=1e-7)

    def test_zero_margin_matches_nominal(self):
        cfg=replace(Config(),horizon=4);trace=make_trace(8,seed=71)
        nominal=run(trace,cfg,'nominal');zero=run(trace,cfg,'adaptive_all',margin_scale=0.)
        np.testing.assert_allclose(nominal.p,zero.p,atol=1e-7)
        np.testing.assert_allclose(nominal.d,zero.d,atol=1e-7)
        with self.assertRaises(ValueError):run(trace,cfg,'adaptive_all',margin_scale=-1.)
        with self.assertRaises(ValueError):run(trace,cfg,'not_a_method')

    def test_battery_guard_removes_margin_above_threshold(self):
        cfg=replace(Config(),horizon=4);trace=make_trace(8,seed=75)
        guarded=run(trace,cfg,'adaptive_guard50')
        self.assertEqual(guarded.margin_harvest.iloc[0],0.)
        self.assertTrue((guarded.margin_gain==0).all())
        self.assertTrue((guarded.margin_arrival==0).all())

    def test_weighted_mpc_physical_rollout(self):
        cfg=replace(Config(),horizon=4);trace=make_trace(8,seed=75)
        for mode in ('nominal','adaptive_all'):
            d=run(trace,cfg,mode)
            self.assertTrue((d.plan_violation<=1e-4).all())
            self.assertTrue((d.p*cfg.tau<=d.E+1e-6).all())
            self.assertTrue((d.d<=d.b+1e-6).all())
            self.assertTrue(np.all(d.d<=capacity(d.p,d.gain,cfg)+1e-6))
            np.testing.assert_allclose(d.b.to_numpy()[1:],(d.b-d.acknowledged+d.arrivals-d['drop']).to_numpy()[:-1],atol=1e-6)
            np.testing.assert_allclose(d.E.to_numpy()[1:],np.minimum(cfg.energy_max,(d.E-d.energy+d.harvest).to_numpy()[:-1]),atol=1e-6)

class FirstSlotRejectionTests(unittest.TestCase):
    def test_no_discretionary_forecast_rejection_when_service_possible(self):
        cfg=replace(Config(),horizon=4)
        trace=make_trace(8,seed=76)
        df=run(trace,cfg,'adaptive_forced')
        self.assertTrue((df.planned_excess_rejection<=2e-4).all())
        self.assertTrue((df.plan_violation<=1e-4).all())
    def test_unavoidable_rejection_is_feasible(self):
        from src.scheduling import solve_cvxpy
        cfg=replace(Config(),horizon=2)
        sol=solve_cvxpy(30.,0.,np.ones(2),np.array([10.,0.]),np.zeros(2),cfg,first_slot_drop_cap=8.000001)
        self.assertLessEqual(sol['o'][0],8.000101)
        self.assertGreaterEqual(sol['o'][0],7.9999)

if __name__=='__main__':unittest.main()
