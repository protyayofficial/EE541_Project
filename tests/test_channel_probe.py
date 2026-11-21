"""Continuous AR lognormal generation, timed numerical probes and causal forecasts."""
import json
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
from src.channel import ChannelModel,channel_sequence,conditional_means,bound_gain,GAIN_FLOOR
from src.forecasting import raw_forecasts
from src.scheduling import Config,solve_cvxpy,solve_lp,verify_plan
from src.radio import PacketRadio,Receiver,simulation_settings
from src.experiment import make_trace,run_policy
from src.auditing import saved_config,audit_packets
from proposal_study import run,apply_margins
from final_evaluation import planned_runs as synthetic_matrix
from final_solar_evaluation import planned_runs as solar_matrix


class ChannelProbeTests(unittest.TestCase):
    def test_initializations_and_exact_seeded_recursions(self):
        for normalized in (False,True):
            for sigma in (.2,.45,.8):
                model=ChannelModel(.68,sigma,normalized)
                rng=np.random.default_rng(np.random.SeedSequence([5000,42017]))
                v=sigma*sigma/(1-.68*.68)
                x=rng.normal(0,np.sqrt(v)) if normalized else 0.
                expected=[]
                for _ in range(20):
                    x=.68*x+rng.normal(0,sigma)
                    expected.append(np.exp(x-(v/2 if normalized else 0.)))
                actual=channel_sequence(20,5000,model)
                np.testing.assert_array_equal(actual,expected)
                np.testing.assert_array_equal(actual,channel_sequence(100,5000,model)[:20])
                self.assertFalse(np.array_equal(actual,channel_sequence(20,5001,model)))

    def test_stationary_normalization_correlation_and_no_quantization(self):
        for sigma in (.2,.45,.8):
            model=ChannelModel(.68,sigma,True);gain=channel_sequence(100000,71,model)
            self.assertTrue(np.isfinite(gain).all() and (gain>0).all())
            self.assertEqual(len(np.unique(gain)),len(gain))
            self.assertGreater(gain.max(),1.)
            self.assertAlmostEqual(gain.mean(),1.,delta=.04)
            logs=np.log(gain)
            self.assertAlmostEqual(logs.var(),model.variance,delta=.025)
            self.assertAlmostEqual(np.corrcoef(logs[:-1],logs[1:])[0,1],.68,delta=.015)
        original=channel_sequence(100000,71,ChannelModel(.68,.8,False))[1000:]
        self.assertAlmostEqual(original.mean(),np.exp(.5*ChannelModel(.68,.8,False).variance),delta=.08)

    def test_invalid_parameters_and_gain_overflow_are_explicit(self):
        for args in ((1.,.45,True),(-.1,.45,True),(.68,np.inf,True),(.68,1e308,True),(.68,-1.,True),(.68,.45,'yes')):
            with self.assertRaises(ValueError):ChannelModel(*args)
        for gain in (0.,-1.,np.inf,np.nan):
            with self.assertRaises(ValueError):Receiver(1).probe(gain)
        with self.assertRaises(ValueError):channel_sequence(10,1,ChannelModel(.68,10000.,True))
        with self.assertRaises(ValueError):bound_gain([np.nan])
        self.assertEqual(bound_gain([-10.])[0],GAIN_FLOOR)
        self.assertEqual(bound_gain([100.])[0],100.)
        g,_,_=apply_margins(np.array([1e-50,1e-50]),np.ones(2),np.ones(2),np.zeros(3),'nominal')
        self.assertEqual(g[0],1e-50)
        self.assertEqual(g[1],GAIN_FLOOR)

    def test_conditional_forecasts_against_independent_gaussian_recursion(self):
        for normalized in (False,True):
            model=ChannelModel(.68,.45,normalized);g=.17389171
            actual=conditional_means(g,np.arange(6),model)
            self.assertEqual(actual[0],g)
            mean=np.log(g)+model.center;variance=0.
            for k in range(6):
                self.assertAlmostEqual(actual[k],np.exp(mean+variance/2-model.center),places=14)
                mean=.68*mean;variance=.68**2*variance+.45**2
            raw=raw_forecasts({'gain':[],'arrival':[],'harvest':[]},g,6,t=0,model=model)[0]
            adjusted,_,_=apply_margins(raw,np.ones(6),np.ones(6),np.array([1.,0.,0.]),'fixed_margin')
            self.assertEqual(adjusted[0],g)
            self.assertTrue((adjusted[1:]>0).all())

    def test_missed_observation_gap_and_initial_prior(self):
        history={'gain':[2.7],'gain_times':[2],'arrival':[0]*6,'harvest':[0.]*6}
        model=ChannelModel()
        forecast=raw_forecasts(history,np.nan,4,t=6,model=model)[0]
        np.testing.assert_allclose(forecast,conditional_means(2.7,np.arange(4,8),model))
        empty={'gain':[],'gain_times':[],'arrival':[],'harvest':[]}
        np.testing.assert_array_equal(raw_forecasts(empty,np.nan,3,t=7,model=model)[0],1.)
        original=ChannelModel(.68,.8,False)
        expected=np.exp(.5*original.variance*(1-.68**(2*np.arange(8,11))))
        np.testing.assert_allclose(raw_forecasts(empty,np.nan,3,t=7,model=original)[0],expected)

    def test_numerical_payload_and_report_availability(self):
        cfg=Config();radio=PacketRadio(3,cfg)
        probe=radio.receiver.probe
        def report(g):
            self.assertEqual(radio.now_s,.6)
            self.assertTrue(np.isnan(radio.estimate))
            self.assertIsInstance(g,float)
            return probe(g)
        with patch.object(radio.receiver,'probe',side_effect=report):g,_=radio.probe(7.,.347219)
        self.assertEqual(g,.347219)
        record=radio.execute(0.,0.,7.,0,0.)
        self.assertEqual(record['reported_gain'],.347219)
        self.assertEqual(record['actual_gain'],.347219)
        self.assertEqual(record['energy'],.2)
        self.assertEqual(record['channel_feedback_available_at_s'],.6)
        self.assertEqual(record['interval_end_s'],5.)
        radio.probe(.19,123.4)
        record=radio.execute(3.,3.,.19,3,1.)
        self.assertTrue(np.isnan(record['reported_gain']))
        self.assertEqual(record['attempted'],0)
        self.assertEqual(record['energy'],0.)

    def test_true_gain_held_and_labels_do_not_quantize(self):
        cfg=Config(bit_error_probability=0.)
        trace=dict(gain=np.array([.347219]),condition=['Worst'])
        radio=PacketRadio(3,cfg,trace=trace);g,_=radio.probe(7.,t=0)
        self.assertEqual(g,.347219)
        trace['gain'][0]=100.
        r=radio.execute(3.,3.,7.,0,0.)
        self.assertEqual(r['actual_gain'],.347219)
        radio=PacketRadio(3,cfg)
        with patch.object(radio.receiver,'probe',return_value=1.):radio.probe(7.,.2)
        r=radio.execute(3.,3.,7.,0,0.)
        self.assertEqual(r['attempted'],3)
        self.assertEqual(r['received'],0)
        self.assertGreater(r['data_energy'],0.)

    def test_gap_residual_targets_and_no_hidden_gain_fallback(self):
        cfg=Config(horizon=3,probe_energy=6.9)
        trace=dict(seed=3,gain=np.array([.25,10000.,.9]),arrival=np.zeros(3),harvest=np.array([0.,6.9,0.]))
        df=run(trace,cfg,'adaptive_all')
        np.testing.assert_array_equal(df.probe_executed,[True,False,True])
        self.assertTrue(np.isnan(df.reported_gain.iloc[1]))
        expected=conditional_means(.25,np.array([2]),cfg.channel_model)[0]
        self.assertAlmostEqual(df.raw_error_gain.iloc[2],expected-.9)
        self.assertEqual(df.forecast_origin_t.iloc[2],1)
        self.assertEqual(df.forecast_target_t.iloc[2],2)
        self.assertEqual(df.forecast_channel_lead.iloc[2],2)
        self.assertTrue(audit_packets(df,cfg))
        for mode in ('greedy','adaptive'):
            self.assertTrue(audit_packets(run_policy(trace,mode,cfg),cfg))

    def test_low_gain_starvation_and_energy_examples(self):
        cfg=Config(bit_error_probability=0.)
        for gain,total in ((.2,1.1708159),(.8,.4427040),(1.,.3941632)):
            radio=PacketRadio(3,cfg);radio.probe(7.,gain)
            r=radio.execute(3.,3.,7.,0,0.)
            self.assertEqual(r['attempted'],3)
            self.assertAlmostEqual(r['energy'],total,places=7)
        radio=PacketRadio(3,cfg);radio.probe(.21,1e-8)
        r=radio.execute(3.,3.,.21,5,10.)
        self.assertEqual(r['attempted'],0)
        self.assertEqual(r['energy'],.2)
        self.assertEqual(r['b_next'],8)
        self.assertAlmostEqual(r['E_next'],10.01)

    def test_continuous_matching_baseline_rule_and_packet_audit(self):
        trace=make_trace(8,71);cfg=Config(horizon=2)
        for runner in (lambda m:run(trace,cfg,m),lambda m:run_policy(trace,m,cfg)):
            forward={m:runner(m) for m in ('greedy','channel','nominal')}
            for m in reversed(tuple(forward)):
                other=runner(m)
                for field in ('reported_gain','gain','attempted_ids','retry_numbers','received_ids','queue_next_ids','E_next'):
                    pd.testing.assert_series_equal(forward[m][field],other[field])
                self.assertTrue(audit_packets(other,cfg))
        for gain,power in ((.799,.45),(.8,2.4),(2.,2.4)):
            tr=dict(gain=np.array([gain]),arrival=np.zeros(1),harvest=np.zeros(1))
            self.assertEqual(run(tr,cfg,'channel').p.iloc[0],power)

    def test_expected_goodput_planners_remain_convex_and_feasible(self):
        import cvxpy as cp
        original=cp.Problem.solve;dcp=[]
        def checked(problem,*a,**k):dcp.append(problem.is_dcp());return original(problem,*a,**k)
        cfg=Config(horizon=3)
        gains=conditional_means(.11,np.arange(3),cfg.channel_model)
        with patch.object(cp.Problem,'solve',checked):
            for solver in (solve_cvxpy,solve_lp):
                sol=solver(12.,7.,gains,[5.]*3,[.6]*3,cfg)
                self.assertLess(max(verify_plan(sol,12.,7.,gains,[5.]*3,[.6]*3,cfg).values()),1e-4)
        self.assertTrue(dcp and all(dcp))

    def test_matrices_historical_seeds_and_model_settings(self):
        for normalized,start in ((False,5000),(True,6000)):
            matrix=pd.DataFrame(synthetic_matrix(mean_normalize=normalized))
            self.assertEqual(len(matrix),300)
            self.assertFalse(matrix.duplicated().any())
            self.assertEqual(set(matrix.seed),set(range(start,start+10)))
            folder='sweep_normalized' if normalized else 'sweep'
            saved=json.loads((Path(__file__).resolve().parents[1]/'results/final_evaluation'/folder/'settings.json').read_text())
            self.assertEqual(saved['seed_start'],start)
        self.assertEqual(len(solar_matrix()),300)
        cfg=Config();settings=simulation_settings(cfg)
        self.assertEqual(saved_config(settings),cfg)
        self.assertEqual(settings['channel_model']['version'],'correlated-lognormal-v1')
        self.assertEqual(settings['channel_model']['feedback'],'accurate_numerical_gain')
        with self.assertRaises(ValueError):saved_config(settings|{'radio_model':'condition-probe-ack-v2'})

    def test_matched_other_streams_and_independent_forecast_audit(self):
        reference=make_trace(5,81)
        for sigma in (.2,.45,.8):
            for normalized in (True,False):
                other=make_trace(5,81,channel_sigma=sigma,mean_normalize=normalized)
                for field in ('arrival','harvest'):np.testing.assert_array_equal(reference[field],other[field])
        cfg=Config(horizon=3);df=run(reference,cfg,'nominal')
        self.assertTrue(audit_packets(df,cfg))
        for field,index in (('forecast_current_gain',0),('forecast_next_gain',0),
                            ('forecast_origin_t',1),('forecast_channel_lead',1),('channel_forecast_anchor_t',1)):
            changed=df.copy();changed.loc[index,field]+=1
            with self.subTest(field=field),self.assertRaises(AssertionError):audit_packets(changed,cfg)
        with self.assertRaisesRegex(ValueError,'channel_sigma'):
            run(reference,replace(cfg,channel_sigma=.8),'greedy')


if __name__=='__main__':unittest.main()
