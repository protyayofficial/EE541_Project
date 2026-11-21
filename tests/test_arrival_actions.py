"""Uniform arrivals, bounded causal forecasts, five-packet actions and energy."""
import json
import unittest
from dataclasses import replace
from unittest.mock import patch

import numpy as np

from final_evaluation import make_evaluation_trace
from proposal_study import apply_margins, run
from src.auditing import audit_packets, saved_config
from src.experiment import make_trace, run_policy
from src.forecasting import raw_forecasts
from src.radio import PacketRadio, simulation_settings
from src.scheduling import Config, solve_cvxpy, solve_lp, verify_plan


class ArrivalActionTests(unittest.TestCase):
    def test_zero_and_ten_arrivals_overflow_after_actual_ack_departures(self):
        cfg=Config(horizon=2,data_max=3.)
        trace=dict(seed=11,condition=np.full(4,'Excellent'),gain=np.ones(4),
                   arrival=np.array([0,10,10,10]),harvest=np.full(4,2.))
        for runner in (lambda:run(trace,cfg,'greedy'),lambda:run_policy(trace,'greedy',cfg)):
            # Each batch attempts three IDs but only two are acknowledged.
            with patch('src.radio.reception_uniform',side_effect=[0.,1.,0.]*4):
                df=runner()
            np.testing.assert_array_equal(df.attempted,3)
            np.testing.assert_array_equal(df.acknowledged,2)
            np.testing.assert_array_equal(df.b_next,[10,18,26,32])
            np.testing.assert_array_equal(df.forced_drop,[0,0,0,2])
            self.assertEqual(json.loads(df.overflow_ids.iloc[-1]),[40,41])
            self.assertEqual(df.b_next.iloc[-1],12+df.arrivals.sum()-df.acknowledged.sum()-df['drop'].sum())
            for row in df.itertuples(index=False):
                self.assertEqual(len(json.loads(row.queue_next_ids)),row.b_next)
                self.assertEqual(len(set(json.loads(row.queue_next_ids))),row.b_next)
                self.assertEqual(row.forced_drop,max(0,row.b-row.acknowledged+row.arrivals-32))

    def test_uniform_arrivals_are_reproducible_and_matched_across_scenarios(self):
        trace=make_trace(2000,seed=124)
        repeated=make_trace(2000,seed=124)
        for key in trace:
            np.testing.assert_array_equal(trace[key],repeated[key])
        arrivals=trace['arrival']
        np.testing.assert_array_equal(arrivals,np.floor(arrivals))
        values,counts=np.unique(arrivals,return_counts=True)
        np.testing.assert_array_equal(values,np.arange(11))
        self.assertTrue(np.issubdtype(arrivals.dtype,np.integer))
        np.testing.assert_array_equal(arrivals,np.random.default_rng(124).integers(0,11,size=2000))
        np.testing.assert_allclose(counts/len(arrivals),1./11,atol=.025,rtol=0)
        self.assertAlmostEqual(arrivals.mean(),5.,delta=.2)
        self.assertFalse(np.array_equal(arrivals,make_trace(2000,seed=125)['arrival']))
        self.assertTrue(((trace['forecast_arrival']>=0)&(trace['forecast_arrival']<=10)).all())
        # Solar callers use this same generator and replace only harvest.
        solar=make_trace(20,seed=124)
        for harvest in (.6,1.2):
            synthetic=make_evaluation_trace(20,124,harvest)
            np.testing.assert_array_equal(synthetic['arrival'],solar['arrival'])
        for slot_seconds in (60.,3600.):
            df=run(solar,replace(Config(),slot_seconds=slot_seconds),'greedy')
            np.testing.assert_array_equal(df.arrivals,solar['arrival'])

    def test_forecast_prior_and_uncertainty_bounds_preserve_custom_traces(self):
        empty={'gain':[],'arrival':[],'harvest':[]}
        np.testing.assert_array_equal(raw_forecasts(empty,1.,3)[1],5.)
        for observations,expected in (([0]*100,40./108),([100]*100,10.)):
            np.testing.assert_array_equal(raw_forecasts(empty|{'arrival':observations},1.,3)[1],expected)
        arrivals=np.array([-1.,1.,9.,11.])
        g,h=np.ones(4),np.ones(4)
        np.testing.assert_array_equal(apply_margins(g,arrivals,h,np.zeros(3),'nominal')[1],[0,1,9,10])
        np.testing.assert_array_equal(apply_margins(g,arrivals,h,np.array([0.,100.,0.]),'adaptive_all')[1],10.)
        tr=make_trace(3,seed=10);tr['arrival'][:]=[0.,25.,0.]
        cfg=Config(horizon=2)
        cases=(('proposal_study.solve_cvxpy','proposal_study.margins',solve_cvxpy,
                lambda:run(tr,cfg,'adaptive_all')),
               ('src.experiment.solve_lp','src.experiment._margins',solve_lp,
                lambda:run_policy(tr,'adaptive',cfg)))
        for target,margin_target,solver,runner in cases:
            forecasts=[]
            def capture(b,e,g,a,h,c,**kwargs):
                forecasts.append(a.copy())
                self.assertTrue(((a>=0)&(a<=10)).all())
                return solver(b,e,g,a,h,c,**kwargs)
            with patch(target,side_effect=capture),patch(margin_target,return_value=np.array([0.,100.,0.])):
                df=runner()
            np.testing.assert_array_equal(forecasts[0],10.)
            np.testing.assert_array_equal(df.arrivals,[0.,25.,0.])
            self.assertTrue(audit_packets(df,cfg))

    def test_both_planners_have_continuous_configured_attempt_bound(self):
        cfg=Config(horizon=3)
        self.assertEqual(cfg.data_max,5.)
        for solve in (solve_cvxpy,solve_lp):
            g,a,h=np.ones(3),np.full(3,5.),np.ones(3)
            s=solve(12.,7.,g,a,h,cfg)
            self.assertLess(max(verify_plan(s,12.,7.,g,a,h,cfg).values()),1e-4)
            self.assertTrue((s['d']<=cfg.data_max+1e-5).all())
            self.assertGreater(s['d'][0],cfg.data_max-.01)
        # A continuous plan can recommend fractional service; execution floors it.
        cfg=Config(horizon=1)
        power=float(np.expm1(np.log(2)*1.5/cfg.rate_scale))
        s=solve_cvxpy(12.,cfg.control_energy+power*cfg.tau,np.ones(1),np.ones(1),np.zeros(1),cfg)
        self.assertAlmostEqual(s['d'][0],1.5,delta=1e-4)

    def test_failed_attempts_consume_full_energy_independent_of_objective_weight(self):
        results=[]
        for weight in (0.,.15,1000.):
            cfg=Config(bit_error_probability=1.,energy_weight=weight,
                       probe_energy=.1,channel_report_energy=.2,ack_energy=.3)
            radio=PacketRadio(4,cfg)
            radio.probe(1.,1.)
            r=radio.execute(100.,3.,1.,2,2.)
            self.assertEqual(r['attempted'],4)
            self.assertEqual(r['acknowledged'],0)
            self.assertEqual(r['b_next'],6)
            self.assertGreater(r['data_energy'],0.)
            self.assertAlmostEqual(r['energy'],r['p']*cfg.tau+cfg.control_energy)
            self.assertLessEqual(r['energy'],1.)
            self.assertAlmostEqual(r['E_next'],1.-r['energy']+2.)
            results.append(r['energy'])
        np.testing.assert_array_equal(results,results[0])
        # The objective coefficient changes cost, never joules debited.
        for solve in (solve_cvxpy,solve_lp):
            objectives=[]
            for weight in (1.,2.):
                cfg=Config(horizon=1,energy_weight=weight,probe_energy=.6)
                s=solve(0.,7.,np.ones(1),np.zeros(1),np.zeros(1),cfg)
                self.assertAlmostEqual(s['p'][0]*cfg.tau+cfg.control_energy*s['u'][0],.6,delta=1e-5)
                objectives.append(s['objective'])
            self.assertAlmostEqual(objectives[1]-objectives[0],.6,delta=1e-5)

    def test_unaffordable_data_cannot_use_same_slot_harvest(self):
        cfg=Config(horizon=2,probe_energy=6.99)
        tr=make_trace(2,seed=41);tr['gain'][:]=1.;tr['condition'][:]='Excellent';tr['harvest'][:]=10.
        for runner in (lambda m:run(tr,cfg,m),lambda m:run_policy(tr,m,cfg)):
            for mode in ('greedy','fixed','nominal'):
                df=runner(mode)
                first=df.iloc[0]
                self.assertEqual(first.attempted,0)
                self.assertEqual(first.data_energy,0.)
                self.assertAlmostEqual(first.control_energy,6.99)
                self.assertAlmostEqual(first.E_next,10.01)
                self.assertEqual(first.b_next,12+tr['arrival'][0])
                self.assertGreater(df.attempted.iloc[1],0)
                self.assertTrue(df.attempted.isin(range(int(cfg.data_max)+1)).all())
                self.assertTrue(audit_packets(df,cfg))

    def test_settings_record_uniform_support_action_bound_and_battery_semantics(self):
        settings=simulation_settings(Config())
        model=settings['arrival_model']
        self.assertEqual(model['distribution'],'discrete_uniform')
        self.assertEqual(model['support'],list(range(11)))
        self.assertEqual(model['probabilities'],[1./11]*11)
        self.assertEqual(model['mean'],5.)
        self.assertEqual(settings['config']['data_max'],5.)
        self.assertEqual(settings['config']['packet_bits'],256.)
        self.assertIn('objective penalty only',settings['battery_accounting'])
        self.assertEqual(saved_config(settings),Config())
        self.assertEqual(settings['traffic_scenario'],'high_load')
        self.assertGreater(settings['mean_arrival_excess'],0.)
        old=settings|{'arrival_model':dict(distribution='discrete_uniform',support=[1,2,3,4,5],probabilities=[.2]*5,mean=3.)}
        with self.assertRaisesRegex(ValueError,'arrival model'):saved_config(old)
        obsolete={k:v for k,v in settings.items() if k!='arrival_model'}
        with self.assertRaisesRegex(ValueError,'arrival model'):
            saved_config(obsolete)


if __name__=='__main__':
    unittest.main()
