"""Captured production failure: identical model, normalized solver objective."""
import json
from pathlib import Path
import unittest
import numpy as np
from src.scheduling import Config,planned_energy,solve_cvxpy,verify_plan


class SolverRecoveryTests(unittest.TestCase):
    def test_captured_slot171_feasible_and_original_objective_units(self):
        record=json.loads((Path(__file__).parent/'fixtures/cvxpy_slot171_original_5003.json').read_text())
        cfg=Config(**record['config']);args=[record[k] for k in ('b0','e0','gain','arrival','harvest')]
        n=len(record['gain']);zero=np.zeros(n);u=zero.copy();u[0]=1.
        witness=dict(p=zero,d=zero,b=np.full(n+1,record['b0']),
                     E=np.r_[record['e0'],record['e0']+np.cumsum(np.asarray(record['harvest'])-cfg.control_energy*u)],
                     o=np.asarray(record['arrival']),w=zero,u=u)
        self.assertLess(max(verify_plan(witness,*args,cfg).values()),1e-12)
        solution=solve_cvxpy(*args,cfg,**record['kwargs'])
        self.assertEqual((solution['status'],solution['solver']),('optimal','CLARABEL'))
        self.assertLess(max(verify_plan(solution,*args,cfg).values()),1e-6)
        cost=(solution['b'][:-1].sum()+cfg.drop_weight*solution['o'].sum()
              +cfg.energy_weight*planned_energy(solution,record['e0'],cfg).sum()
              +cfg.terminal_weight*solution['b'][-1])
        self.assertAlmostEqual(solution['objective'],cost,places=9)
        self.assertEqual(solution['objective_scale'],35.)
        self.assertAlmostEqual(solution['objective'],2152.96053,delta=1e-3)
        self.assertGreater(solution['d'][0],4.99999)


if __name__=='__main__':unittest.main()
