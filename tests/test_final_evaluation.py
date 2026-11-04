import unittest
import numpy as np
from dataclasses import replace
from src.scheduling import Config,solve_cvxpy,verify_plan
from final_evaluation import make_evaluation_trace, evaluate
from offline_reference import solve_one
from proposal_study import run

class FinalEvaluationTests(unittest.TestCase):
    def test_matched_bounded_seeded_trace(self):
        a=make_evaluation_trace(25,501,.2,.6);b=make_evaluation_trace(25,501,.2,.6)
        for k in ('gain','arrival','harvest'):np.testing.assert_array_equal(a[k],b[k])
        self.assertTrue(np.all((a['arrival']>=0)&(a['arrival']<=10)))
        c=make_evaluation_trace(25,501,.8,.6);self.assertFalse(np.allclose(a['gain'],c['gain']))
        norm=make_evaluation_trace(25,501,.8,.6,True);norm2=make_evaluation_trace(25,501,.8,.6,True)
        np.testing.assert_array_equal(norm['gain'],norm2['gain']);self.assertFalse(np.allclose(norm['gain'],c['gain']))
    def test_fixed_and_channel_heuristics_are_physically_feasible(self):
        cfg=replace(Config(),horizon=4);tr=make_evaluation_trace(12,501,.4,1.)
        for mode in ('fixed','channel'):
            d=run(tr,cfg,mode)
            self.assertTrue((d.p*cfg.tau<=d.E+1e-7).all())
            self.assertTrue((d.d<=d.b+1e-7).all())
            self.assertTrue((d['drop']<=d.arrivals+1e-7).all())

    def test_offline_reference_plan_is_feasible_and_no_worse_than_online(self):
        cfg=replace(Config(),horizon=4);tr=make_evaluation_trace(8,502,.4,.7)
        online=run(tr,cfg,'nominal');cost=evaluate(online,cfg)['realized_cost']
        row,plan=solve_one('synthetic','test',502,tr,cfg)
        self.assertIn(row['status'],('optimal','optimal_inaccurate'))
        self.assertEqual(len(plan),8);self.assertLess(row['max_violation'],1e-4)
        self.assertLessEqual(row['objective'],cost+1e-3)

    def test_solvers_are_individually_selectable(self):
        cfg=replace(Config(),horizon=4);g=np.ones(4);a=np.ones(4)*2;h=np.ones(4)
        x=solve_cvxpy(12,7,g,a,h,cfg,solver_preference='CLARABEL')
        y=solve_cvxpy(12,7,g,a,h,cfg,solver_preference='SCS')
        self.assertEqual(x['solver'],'CLARABEL');self.assertEqual(y['solver'],'SCS')
        self.assertLess(max(verify_plan(y,12,7,g,a,h,cfg).values()),1e-4)
        self.assertLess(abs(x['objective']-y['objective'])/max(1,abs(x['objective'])),1e-3)
        with self.assertRaises(ValueError):solve_cvxpy(12,7,g,a,h,cfg,solver_preference='nonexistent')
if __name__=='__main__':unittest.main()
