import unittest
import numpy as np
from dataclasses import replace
from src.scheduling import Config,solve_cvxpy,verify_plan
from final_evaluation import make_evaluation_trace, evaluate
from offline_reference import solve_one
from proposal_study import run

class FinalEvaluationTests(unittest.TestCase):
    def test_matched_bounded_seeded_trace(self):
        a=make_evaluation_trace(25,501,.6);b=make_evaluation_trace(25,501,.6)
        for k in ('condition','gain','arrival','harvest'):np.testing.assert_array_equal(a[k],b[k])
        self.assertTrue(np.all((a['arrival']>=0)&(a['arrival']<=10)))
        c=make_evaluation_trace(25,502,.6);self.assertFalse(np.array_equal(a['gain'],c['gain']))
        self.assertTrue((make_evaluation_trace(25,501,.6,sigma=.8)['gain']>0).all())
    def test_fixed_and_channel_heuristics_are_physically_feasible(self):
        cfg=replace(Config(),horizon=4);tr=make_evaluation_trace(12,501,1.)
        for mode in ('fixed','channel'):
            d=run(tr,cfg,mode)
            self.assertTrue((d.p*cfg.tau<=d.E+1e-7).all())
            self.assertTrue((d.d<=d.b+1e-7).all())
            self.assertTrue((d['drop']<=d.arrivals+1e-7).all())

    def test_offline_reference_is_feasible_expected_goodput_not_pathwise_bound(self):
        cfg=replace(Config(),horizon=4);tr=make_evaluation_trace(8,502,.7)
        online=run(tr,cfg,'nominal');cost=evaluate(online,cfg)['realized_cost']
        row,plan=solve_one('synthetic','test',502,tr,cfg)
        self.assertIn(row['status'],('optimal','optimal_inaccurate'))
        self.assertEqual(len(plan),8);self.assertLess(row['max_violation'],1e-4)
        self.assertEqual(row['reference_kind'],'deterministic_expected_goodput')
        np.testing.assert_allclose(plan.b_next,plan.b-cfg.success_probability*plan.d+plan.arrival-plan.o,atol=1e-6)
        self.assertTrue(np.isfinite(cost))  # No sample-path ordering is implied.

    def test_solvers_are_individually_selectable(self):
        cfg=replace(Config(),horizon=4);g=np.ones(4);a=np.ones(4)*2;h=np.ones(4)
        x=solve_cvxpy(12,7,g,a,h,cfg,solver_preference='CLARABEL')
        y=solve_cvxpy(12,7,g,a,h,cfg,solver_preference='SCS')
        self.assertEqual(x['solver'],'CLARABEL');self.assertEqual(y['solver'],'SCS')
        self.assertLess(max(verify_plan(y,12,7,g,a,h,cfg).values()),1e-4)
        self.assertLess(abs(x['objective']-y['objective'])/max(1,abs(x['objective'])),1e-3)
        with self.assertRaises(ValueError):solve_cvxpy(12,7,g,a,h,cfg,solver_preference='nonexistent')
if __name__=='__main__':unittest.main()
