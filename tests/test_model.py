import unittest
import numpy as np
from src.scheduling import Config, capacity, solve_lp, verify_plan
from src.experiment import make_trace,run_policy

class Tests(unittest.TestCase):
    def test_lp_feasible_under_full_physical_capacity(self):
        cfg=Config(horizon=6)
        g=np.array([.5,1.,2.,.8,1.2,.7]);l=np.array([3.,5.,0.,4.,2.,5.]);H=np.ones(6)
        sol=solve_lp(12,7,g,l,H,cfg)
        self.assertLess(max(verify_plan(sol,12,7,g,l,H,cfg).values()),1e-6)
        self.assertTrue(np.all(sol['d']<=capacity(sol['p'],g,cfg)+1e-7))
    def test_causal_rollout(self):
        cfg=Config(horizon=5)
        trace=make_trace(12,seed=18)
        for name in ['fixed','greedy','channel','nominal','robust','adaptive']:
            df=run_policy(trace,name,cfg)
            self.assertTrue((df.b>=-1e-7).all())
            self.assertTrue((df.b<=cfg.buffer_max+1e-7).all())
            self.assertTrue((df.E<=cfg.energy_max+1e-7).all())
            self.assertTrue((df.d<=df.b+1e-7).all())
            self.assertTrue((df['drop']<=df.arrivals+1e-7).all())

if __name__=='__main__':unittest.main()
