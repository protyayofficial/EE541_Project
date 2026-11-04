"""Checks for causal predictions, physical feasibility, and solver accounting."""
import unittest
from dataclasses import replace
import numpy as np
from src.scheduling import Config, verify_plan
from src.experiment import make_trace
from research_experiments import causal_forecasts
from uncertainty_study import forecasts_at, rollout
from reliability_study import solve_lex

class UncertaintyTests(unittest.TestCase):
    def test_forecast_ignores_unobserved_future(self):
        cfg=replace(Config(),horizon=5)
        a=causal_forecasts(make_trace(20,seed=44),21)
        b={k:v.copy() for k,v in a.items()}
        for k in ('gain','arrival','harvest'): b[k][8:] += 100
        history={'gain':list(a['gain'][:7]),'arrival':list(a['arrival'][:7]),
                 'harvest':list(a['harvest'][:7]),'b':[12], 'E':[7]}
        for mode in ('ar_nominal','ar_calibrated','ar_gated','ema_nominal'):
            x=forecasts_at(7,a,cfg,mode,history,[])
            y=forecasts_at(7,b,cfg,mode,history,[])
            for left,right in zip(x,y): np.testing.assert_allclose(left,right)

    def test_residual_checker_checks_power_and_data_caps(self):
        cfg=Config(); sol={'p':np.array([4.]),'d':np.array([11.]),'b':np.array([12.,1.]),
            'E':np.array([7.,3.]),'o':np.array([0.]),'w':np.array([0.])}
        result=verify_plan(sol,12,7,np.ones(1),np.zeros(1),np.zeros(1),cfg)
        self.assertGreater(result['power_cap'],0);self.assertGreater(result['data_cap'],0)

    def test_lex_solution_and_physical_rollout(self):
        cfg=replace(Config(),horizon=4)
        g=np.ones(4); arrivals=np.full(4,3.); harvest=np.ones(4)
        sol=solve_lex(12,7,g,arrivals,harvest,cfg)
        self.assertLessEqual(max(verify_plan(sol,12,7,g,arrivals,harvest,cfg).values()),1e-4)
        self.assertLessEqual(sol['planned_loss'],sol['planned_loss_budget']+1e-4)
        trace=causal_forecasts(make_trace(10,seed=98),21)
        df=rollout(trace,cfg,'ar_calibrated','cvxpy')
        self.assertTrue((df.d <= df.b + 1e-7).all())
        self.assertTrue((df['drop'] <= df.arrivals + 1e-7).all())
        self.assertTrue((df.violation <= 1e-4).all())
        self.assertIn('stage2_fallback',df)

if __name__=='__main__': unittest.main()
