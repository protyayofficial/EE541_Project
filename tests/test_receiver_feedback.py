"""Feedback, stochastic retransmission, conservation and convex planning."""
import io
import json
import unittest
from dataclasses import replace
from unittest.mock import patch

import numpy as np
import pandas as pd

from proposal_study import run
from final_evaluation import evaluate
from src.auditing import audit_packets, saved_config
from src.experiment import make_trace, run_policy, summarize
from src.radio import PacketQueue, PacketRadio, Receiver, reception_uniform, simulation_settings
from src.scheduling import Config, capacity, solve_cvxpy, solve_lp, verify_plan


class ReceiverTests(unittest.TestCase):
    def test_three_attempted_two_acknowledged_and_retry_priority(self):
        cfg = Config()
        radio = PacketRadio(5, cfg, seed=123)
        radio.probe(7., 1.)
        # Fail the middle packet, then succeed on its retry.
        with patch('src.radio.reception_uniform', side_effect=[0., 1., 0.]):
            r = radio.execute(3.7, 3., 7., 0, 0.)
        self.assertEqual(json.loads(r['attempted_ids']), [0,1,2])
        self.assertEqual(json.loads(r['acknowledged_ids']), [0,2])
        self.assertEqual(r['acknowledged'], 2)
        self.assertEqual(radio.queue.ids, [1,3,4])
        self.assertEqual(r['b_next'], 3)
        radio.probe(r['E_next'], 1.)
        with patch('src.radio.reception_uniform', return_value=0.):
            retried = radio.execute(1., 3., r['E_next'], 0, 0.)
        self.assertEqual(json.loads(retried['attempted_ids']), [1])
        self.assertEqual(json.loads(retried['retry_numbers']), [1])
        self.assertEqual(radio.queue.ids, [3,4])
        self.assertEqual(retried['cumulative_delivered'], 3)

    def test_duplicate_receptions_and_acks_are_idempotent(self):
        cfg = Config(bit_error_probability=0.)
        rx = Receiver(10)
        received, delivered = rx.receive([0,1], [0,0], 3., 1., cfg)
        self.assertEqual(delivered, [0,1])
        # Receiver can repeat its ACK, without counting more delivered bits.
        again, new = rx.receive([0,1], [1,1], 3., 1., cfg)
        self.assertEqual(again, received)
        self.assertEqual(new, [])
        queue = PacketQueue(3, cfg)
        queue.attempts(2,time_s=1.6)
        self.assertEqual(queue.acknowledge([0,0,1,1,99],time_s=3.6), [0,1])
        self.assertEqual(queue.acknowledge(again), [])
        self.assertEqual(queue.ids, [2])
        self.assertEqual(len(rx.delivered)*cfg.packet_bits, 512.)
        self.assertEqual(3, len(rx.delivered)+len(queue.ids))

    def test_success_failure_zero_and_failed_attempt_energy(self):
        for ber, recommendation, expected in ((0.,3.7,3),(1.,3.7,0),(0.,0.,0)):
            cfg = Config(bit_error_probability=ber)
            radio = PacketRadio(3, cfg)
            radio.probe(7., 1.)
            r = radio.execute(recommendation, 3., 7., 0, 0.)
            self.assertEqual(r['delivered'], expected)
            self.assertEqual(r['b_next'], 3-expected)
            if recommendation:
                self.assertGreater(r['data_energy'], 0.)
                self.assertEqual(r['attempted'], 3)
                self.assertAlmostEqual(r['E_next'], 7.-r['energy'])
            else:
                self.assertEqual(r['energy'], cfg.probe_energy)
                self.assertEqual(r['channel_estimate'], 1.)
            self.assertEqual(r['throughput_bps'], expected*256./cfg.slot_seconds)

    def test_true_channel_is_used_for_physical_reception(self):
        cfg = Config(bit_error_probability=0.)
        radio = PacketRadio(3, cfg)
        with patch.object(radio.receiver, 'probe', return_value=1.):
            radio.probe(7., .2)
        r = radio.execute(3., 3., 7., 0, 0.)
        self.assertEqual(r['attempted'], 3)
        self.assertEqual(r['received'], 0)
        self.assertGreater(r['energy'], 0.)

    def test_success_probability_and_matched_independent_draws(self):
        cfg = Config()
        self.assertEqual(cfg.packet_bits, 256.)
        self.assertAlmostEqual(cfg.success_probability, (1.-9.89e-6)**256)
        self.assertAlmostEqual(1.-cfg.success_probability, .00253, places=5)
        self.assertAlmostEqual(replace(cfg,packet_bits=512.).success_probability,
                               cfg.success_probability**2)
        draws = [reception_uniform(71,i,0) for i in range(2000)]
        self.assertEqual(len(draws), len(set(draws)))
        self.assertNotEqual(draws[0], reception_uniform(72,0,0))
        self.assertNotEqual(draws[0], reception_uniform(71,0,1))
        # Empirical distribution check at a larger error rate, with fixed seed.
        cfg = replace(cfg, bit_error_probability=.004)
        rx = Receiver(71)
        successes = [int(bool(rx.receive([i],[0],3.,1.,cfg)[0])) for i in range(2000)]
        self.assertLess(abs(np.mean(successes)-cfg.success_probability), .04)

    def test_control_costs_reservation_and_same_slot_harvest(self):
        cfg = Config(bit_error_probability=0.,probe_energy=.2,channel_report_energy=.3,
                     ack_energy=.4,probe_seconds=.1,channel_report_seconds=.2,ack_seconds=.3)
        radio = PacketRadio(3,cfg)
        report, available = radio.probe(1.,1.)
        self.assertEqual(report,1.)
        self.assertAlmostEqual(available,.1)
        r = radio.execute(3.,3.,1.,1,12.)
        self.assertEqual(r['attempted'],1)
        self.assertAlmostEqual(r['control_energy'],.9)
        self.assertLessEqual(r['energy'],1.)
        self.assertEqual(r['E_next'],cfg.energy_max)
        self.assertGreater(r['spill'],0.)
        radio = PacketRadio(3,cfg)
        report, _ = radio.probe(.5,1.)
        self.assertEqual(report,1.)
        r = radio.execute(3.,3.,.5,2,5.)
        self.assertEqual(r['attempted'],0)
        self.assertAlmostEqual(r['energy'],.5)
        self.assertAlmostEqual(r['E_next'],5.)
        self.assertEqual(radio.queue.ids,[0,1,2,3,4])
        # A probe/report remains available on a deliberately idle data slot.
        radio.probe(1.,.8)
        r = radio.execute(0.,0.,1.,0,0.)
        self.assertEqual(r['channel_estimate'],.8)
        self.assertAlmostEqual(r['energy'],.9)
        with self.assertRaises(ValueError):
            replace(cfg,slot_seconds=1.5)
        for field, value in (('ack_energy',-1.),('probe_seconds',np.nan),
                             ('bit_error_probability',1.1)):
            with self.assertRaises(ValueError):
                replace(cfg,**{field:value})


class FeedbackIntegrationTests(unittest.TestCase):
    def test_every_policy_skips_unaffordable_control_and_resumes_after_harvest(self):
        from proposal_study import METHODS
        cfg=Config(horizon=2,probe_energy=8.,channel_report_energy=0.,ack_energy=0.)
        tr=make_trace(2,seed=77);tr['harvest'][:]=5.
        runners=[lambda m=m:run(tr,cfg,m) for m in
                 (*METHODS,'fixed','channel','adaptive_guard50','adaptive_guard75',
                  'nominal_forced','adaptive_forced','adaptive_arrival_forced','adaptive_harvest_forced')]
        runners += [lambda m=m,be=be:run_policy(tr,m,cfg,backend=be) for be in ('lp','cvxpy')
                    for m in ('fixed','channel','greedy','nominal','robust','adaptive','adaptive_risk')]
        for simulate in runners:
            df=simulate()
            self.assertEqual(df.solver_status.iloc[0],'no_control_energy')
            self.assertTrue(np.isnan(df.channel_estimate.iloc[0]))
            self.assertEqual(df.energy.iloc[0],0.)
            self.assertEqual(df.E_next.iloc[0],12.)
            self.assertEqual(df.b_next.iloc[0],min(32,12+tr['arrival'][0]))
            self.assertEqual(df.channel_estimate.iloc[1],tr['gain'][1])
            self.assertEqual(df.control_energy.iloc[1],8.)
            self.assertTrue(audit_packets(df,cfg))

    def test_reports_precede_planning_and_history_uses_reports(self):
        tr = make_trace(3,seed=88)
        for runner, target in ((lambda c:run(tr,c,'nominal'),'proposal_study.solve_cvxpy'),
                               (lambda c:run_policy(tr,'nominal',c),'src.experiment.solve_lp')):
            seen = []
            solver = solve_cvxpy if 'proposal' in target else solve_lp
            def check(b,e,g,a,h,c,**kwargs):
                seen.append(g[0])
                self.assertEqual(g[0],.8)
                return solver(b,e,g,a,h,c,**kwargs)
            with patch('src.radio.Receiver.probe',return_value=.8),patch(target,side_effect=check):
                df = runner(replace(Config(),horizon=2))
            self.assertEqual(len(seen),3)
            np.testing.assert_array_equal(df.channel_estimate,.8)
        # Gain history must use the report, never the true gain.
        for target, runner in (('proposal_study.raw_forecasts',lambda:run(tr,Config(),'greedy')),
                               ('src.experiment.raw_forecasts',lambda:run_policy(tr,'greedy'))):
            from src.forecasting import raw_forecasts
            histories=[]
            def capture(history,g,h,**kwargs):
                histories.append(list(history['gain']))
                return raw_forecasts(history,g,h,**kwargs)
            with patch('src.radio.Receiver.probe',return_value=.8),patch(target,side_effect=capture):
                runner()
            self.assertEqual(histories,[[],[.8],[.8,.8]])

    def test_future_values_and_oracle_fields_do_not_change_current_actions(self):
        cfg = Config(horizon=3,bit_error_probability=.002)
        tr = make_trace(6,seed=88)
        other = {k:np.array(v,copy=True) for k,v in tr.items()}
        for name in ('arrival','harvest'):
            other[name][3:] += 100
        other['gain'][3:]=.2;other['condition'][3:]='Worst'
        for name in ('forecast_gain','forecast_arrival','forecast_harvest'):
            other[name][:] = 999.
        for runner in (lambda x:run(x,cfg,'adaptive_all'),
                       lambda x:run_policy(x,'adaptive',cfg)):
            a,b = runner(tr),runner(other)
            for field in ('p','d','acknowledged','channel_estimate','queue_next_ids'):
                np.testing.assert_array_equal(a[field].iloc[:3],b[field].iloc[:3])

    def test_policy_order_does_not_change_reception_and_ids_include_drops(self):
        cfg = Config(horizon=2,bit_error_probability=.002)
        tr = make_trace(5,seed=90)
        tr['arrival'][:] = 25
        modes = ('greedy','fixed','nominal')
        for runner in (lambda m:run(tr,cfg,m),lambda m:run_policy(tr,m,cfg)):
            forward = {m:runner(m) for m in modes}
            reverse = {m:runner(m) for m in reversed(modes)}
            matched = {}
            for m in modes:
                df = forward[m]
                for field in ('attempted_ids','retry_numbers','received_ids','queue_next_ids'):
                    pd.testing.assert_series_equal(df[field],reverse[m][field])
                self.assertTrue(audit_packets(df,cfg))
                for r in df.itertuples():
                    successes=set(json.loads(r.received_ids))
                    for i,retry in zip(json.loads(r.attempted_ids),json.loads(r.retry_numbers)):
                        key=(i,retry)
                        if key in matched:self.assertEqual(matched[key],i in successes)
                        matched[key]=i in successes
                self.assertEqual(json.loads(df.arrival_ids.iloc[1]),list(range(37,62)))
                self.assertGreater(df['drop'].sum(),0)

    def test_both_simulators_battery_final_state_metrics_and_csv_audit(self):
        cfg = Config(horizon=2,bit_error_probability=1.,probe_energy=.2,
                     channel_report_energy=.3,ack_energy=.4)
        tr = make_trace(5,seed=42)
        tr['harvest'][:] = 0.
        tr['gain'][:]=1.;tr['condition'][:]='Excellent'
        for df in (run(tr,cfg,'greedy'),run_policy(tr,'greedy',cfg,e0=1.)):
            self.assertGreater(df.data_energy.sum(),0.)
            self.assertEqual(df.delivered.sum(),0)
            self.assertEqual(df.throughput_bps.sum(),0.)
            self.assertEqual(df.acknowledged.sum(),0)
            self.assertTrue(audit_packets(df,cfg))
            self.assertTrue(audit_packets(pd.read_csv(io.StringIO(df.to_csv(index=False))),cfg))
            self.assertEqual(df.b_next.iloc[-1],12+df.arrivals.sum()-df['drop'].sum())
            self.assertTrue((df.E_next>=0).all())
        df=run(tr,cfg,'greedy')
        self.assertEqual(evaluate(df,cfg)['terminal_queue'],df.b_next.iloc[-1])
        legacy=run_policy(tr,'greedy',cfg)
        self.assertAlmostEqual(summarize(legacy,cfg).energy_J.iloc[0],legacy.energy.sum())
        corrupted=df.copy();corrupted.loc[0,'acknowledged_ids']='[999]'
        with self.assertRaises(AssertionError):audit_packets(corrupted,cfg)
        self.assertEqual(saved_config(simulation_settings(cfg)),cfg)
        with self.assertRaises(ValueError):saved_config({})

    def test_proactive_rejection_retains_ids_and_all_failure_overflow(self):
        cfg=Config(bit_error_probability=1.)
        tr=make_trace(1,seed=11);tr['gain'][:]=1.;tr['condition'][:]='Excellent';tr['arrival'][:]=5.
        fake=dict(p=np.array([1.2]),d=np.array([3.7]),o=np.array([2.7]),status='mock')
        with patch('src.experiment.solve_lp',return_value=fake),patch('src.experiment.verify_plan',return_value={'mock':0.}):
            df=run_policy(tr,'nominal',cfg,b0=31)
        r=df.iloc[0]
        self.assertEqual(r.forced_drop,4)
        self.assertEqual(r.proactive,0)
        self.assertEqual(json.loads(r.queue_next_ids),list(range(32)))
        self.assertEqual(json.loads(r.overflow_ids),[32,33,34,35])
        with patch('src.experiment.solve_lp',return_value=fake),patch('src.experiment.verify_plan',return_value={'mock':0.}):
            df=run_policy(tr,'nominal',cfg,b0=12)
        self.assertEqual(json.loads(df.proactive_ids.iloc[0]),[15,16])
        self.assertTrue(audit_packets(df,cfg))

    def test_continuous_planners_use_expected_goodput_and_control_reservations(self):
        for ber in (0.,.002,1.):
            cfg=Config(horizon=3,bit_error_probability=ber,probe_energy=.2,
                       channel_report_energy=.1,ack_energy=.2)
            for solver in (solve_cvxpy,solve_lp):
                for energy in (.1,7.):
                    s=solver(12.,energy,np.ones(3),np.full(3,2.),np.ones(3),cfg)
                    self.assertLess(max(verify_plan(s,12.,energy,np.ones(3),np.full(3,2.),np.ones(3),cfg).values()),1e-4)
                    np.testing.assert_allclose(s['b'][1:],s['b'][:-1]-cfg.success_probability*s['d']+2.-s['o'],atol=1e-5)
                    if energy<cfg.control_energy:
                        self.assertLess(abs(s['d'][0]),1e-5)
                    else:
                        self.assertLessEqual(s['p'][0]*cfg.tau+cfg.control_energy,energy+1e-5)
                    # solve_cvxpy asserts is_dcp() before invoking its solver.
                    if solver is solve_cvxpy:self.assertIn(s['status'],('optimal','optimal_inaccurate'))


if __name__ == '__main__':
    unittest.main()
