"""Virtual phase timing, causal availability and independent runtime checks."""
import io
import json
import unittest
from dataclasses import replace
from unittest.mock import patch

import numpy as np
import pandas as pd

from final_evaluation import evaluate
from scheduling_policies import METHODS, run
from src.auditing import audit_metrics, audit_packets, saved_config, trajectory_config
from src.course_data import SOURCE_INTERVALS
from src.experiment import make_trace, run_policy, summarize
from src.forecasting import raw_forecasts
from src.radio import PacketRadio, simulation_settings
from src.scheduling import Config


class PhaseTimingTests(unittest.TestCase):
    def test_default_boundaries_and_validation(self):
        cfg = Config()
        p = cfg.phase_boundaries()
        phases = ('probe', 'channel_report', 'decision', 'data', 'ack', 'update', 'guard')
        np.testing.assert_allclose([p[x+'_start_s'] for x in phases], [0., .3, .6, 1.6, 2.6, 3.6, 4.6])
        np.testing.assert_allclose([p[x+'_end_s'] for x in phases], [.3, .6, 1.6, 2.6, 3.6, 4.6, 5.])
        self.assertAlmostEqual(cfg.guard_seconds, .4)
        self.assertEqual(replace(cfg, slot_seconds=4.6).guard_seconds, 0.)
        for kwargs in ({'slot_seconds':4.59}, {'decision_seconds':1.5},
                       {'update_seconds':-1.}, {'decision_seconds':np.nan},
                       {'update_seconds':np.inf}, {'ack_seconds':2.}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                replace(cfg, **kwargs)
        for origin in (-1., np.nan, np.inf):
            with self.assertRaises(ValueError): cfg.phase_boundaries(origin)

    def test_report_reception_ack_and_next_state_event_order(self):
        cfg = Config()
        radio = PacketRadio(3, cfg)
        events = []
        probe, receive = radio.receiver.probe, radio.receiver.receive
        ack, arrive, advance = radio.queue.acknowledge, radio.queue.arrive, radio._advance

        def report(condition):
            events.append(('report', radio.now_s))
            self.assertIsNone(radio.reported_condition)
            self.assertTrue(np.isnan(radio.estimate))
            self.assertEqual(radio.now_s, .6)
            return probe(condition)

        def reception(*args):
            events.append(('receive', radio.now_s))
            self.assertEqual(radio.queue.ids, [0, 1, 2])
            self.assertEqual(radio.now_s, 2.6)
            return receive(*args)

        def acknowledge(ids,**kwargs):
            events.append(('ack', radio.now_s))
            self.assertEqual(radio.now_s, 3.6)
            self.assertEqual(radio.queue.ids, [0, 1, 2])
            return ack(ids,**kwargs)

        def arrivals(*args,**kwargs):
            events.append(('arrivals', radio.now_s))
            self.assertEqual(radio.now_s, 5.)
            self.assertEqual(radio.queue.ids, [1])
            return arrive(*args,**kwargs)

        def clock(timestamp):
            if timestamp == 4.6:
                # ACKs have departed, but new arrivals are still unavailable.
                self.assertEqual(radio.queue.ids, [1])
            return advance(timestamp)

        def history():
            events.append(('history', radio.now_s))
            self.assertEqual(radio.now_s, 5.)

        with patch.object(radio.receiver, 'probe', side_effect=report), \
             patch.object(radio.receiver, 'receive', side_effect=reception), \
             patch.object(radio.queue, 'acknowledge', side_effect=acknowledge), \
             patch.object(radio.queue, 'arrive', side_effect=arrivals), \
             patch.object(radio, '_advance', side_effect=clock), \
             patch('src.radio.reception_uniform', side_effect=[.1, .9999, .2]), \
             patch('time.sleep', side_effect=AssertionError('no real-time sleeping')):
            estimate, available = radio.probe(2., .8)
            self.assertEqual(estimate, .8)
            self.assertAlmostEqual(available, 1.8)
            self.assertEqual(radio.now_s, .6)
            r = radio.execute(3., 3., 2., 4, 10., on_update=history)
        self.assertEqual(events, [('report', .6), ('receive', 2.6), ('ack', 3.6),
                                  ('arrivals', 5.), ('history', 5.)])
        self.assertEqual(json.loads(r['acknowledged_ids']), [0, 2])
        self.assertEqual(json.loads(r['queue_next_ids']), [1, 3, 4, 5, 6])
        self.assertAlmostEqual(r['E_next'], 2.-r['energy']+10.)
        self.assertEqual(r['arrivals_available_at_s'], r['harvest_available_at_s'])
        self.assertEqual(r['harvest_available_at_s'], 5.)

    def test_a0_starvation_and_arrivals_advance_full_intervals(self):
        cfg = Config(bit_error_probability=0.)
        radio = PacketRadio(0, cfg)
        with patch('time.sleep', side_effect=AssertionError('no sleeping')):
            radio.probe(.2, .2)
            idle = radio.execute(3., 3., .2, 3, .1)
            self.assertEqual(idle['attempted'], 0)  # no same-slot arrivals
            self.assertEqual(idle['energy'], .2)
            self.assertEqual(idle['E_next'], .1)
            self.assertEqual(radio.now_s, 5.)
            with patch.object(radio.receiver, 'probe', side_effect=AssertionError('unaffordable probe')):
                report, available = radio.probe(.1, 1.)
            self.assertTrue(np.isnan(report))
            self.assertEqual(available, .1)
            inactive = radio.execute(3., 3., .1, 0, 1.)
            self.assertFalse(inactive['probe_executed'])
            self.assertTrue(np.isnan(inactive['channel_feedback_available_at_s']))
            self.assertTrue(np.isnan(inactive['ack_processed_at_s']))
            self.assertEqual(inactive['energy'], 0.)
            self.assertEqual(inactive['attempted'], 0)  # same-slot harvest cannot fund data
            self.assertEqual(radio.now_s, 10.)
            radio.probe(inactive['E_next'], 1.)
            active = radio.execute(3., 3., inactive['E_next'], 0, 0.)
        self.assertEqual(active['attempted'], 3)
        self.assertEqual(active['interval_start_s'], 10.)
        self.assertEqual(active['interval_end_s'], 15.)

    def test_durations_do_not_add_energy_or_change_one_second_data_cost(self):
        for cfg in (Config(bit_error_probability=1.),
                    Config(bit_error_probability=1., slot_seconds=60., decision_seconds=2., update_seconds=3.)):
            radio = PacketRadio(3, cfg)
            radio.probe(2., .2)
            r = radio.execute(3., 3., 2., 0, 0.)
            expected = (2**(3*256/3000)-1)/.2
            self.assertEqual(r['attempted'], 3)
            self.assertEqual(r['acknowledged'], 0)
            self.assertAlmostEqual(r['data_energy'], expected)
            self.assertAlmostEqual(r['energy'], .2+expected)
            self.assertAlmostEqual(r['E_next'], 2.-.2-expected)
            self.assertEqual(r['data_end_s']-r['data_start_s'], 1.)
        cfg = Config(channel_report_energy=.1, ack_energy=.2)
        radio = PacketRadio(3, cfg)
        radio.probe(.4, .8)  # probe + report affordable; ACK and data blocked
        r = radio.execute(3., 3., .4, 0, 0.)
        self.assertTrue(r['probe_available'])
        self.assertFalse(r['exchange_available'])
        self.assertAlmostEqual(r['energy'], .3)
        self.assertEqual(r['interval_end_s'], 5.)
        self.assertTrue(np.isnan(r['ack_processed_at_s']))

    def test_solar_intervals_and_saved_settings_are_explicit(self):
        settings = simulation_settings(Config()) | {'dataset_slot_seconds': SOURCE_INTERVALS}
        self.assertEqual(settings['phase_timing_model'], 'fixed-phases-v1')
        self.assertEqual(settings['phase_energy_costs']['probe_joules'], .2)
        self.assertEqual(settings['phase_energy_costs']['decision_joules'], 0.)
        for dataset, seconds in SOURCE_INTERVALS.items():
            cfg = trajectory_config(settings, dataset)
            self.assertEqual(cfg.slot_seconds, seconds)
            self.assertAlmostEqual(cfg.guard_seconds, seconds-4.6)
            df = run(make_trace(2, 4), cfg, 'greedy')
            np.testing.assert_allclose(df.interval_end_s, [seconds, 2*seconds])
            np.testing.assert_allclose(df.data_end_s-df.data_start_s, 1.)
            self.assertTrue(audit_packets(df, cfg))
        obsolete = settings.copy(); obsolete.pop('phase_timing_model')
        with self.assertRaisesRegex(ValueError, 'timing'): saved_config(obsolete)

    def test_solver_runtime_and_budget_are_separate_from_virtual_time(self):
        cfg = Config(horizon=2)
        trace = make_trace(2, 9)
        # perf_counter brackets: whole decision, solve start/end, whole decision.
        # Arbitrarily slow host computation still occupies the fixed virtual window.
        stamps = [10., 10.1, 11.6, 11.8, 30., 30.1, 31.6, 31.8]
        for implementation in ('proposal', 'legacy'):
            with self.subTest(implementation=implementation), \
                 patch('time.perf_counter', side_effect=stamps):
                df = (run(trace, cfg, 'nominal') if implementation == 'proposal' else
                      run_policy(trace, 'nominal', cfg, backend='lp'))
            np.testing.assert_allclose(df.solver_runtime_s, 1.5)
            np.testing.assert_allclose(df.decision_runtime_s, 1.8)
            self.assertTrue(df.solver_budget_exceeded.all())
            self.assertTrue(df.decision_budget_exceeded.all())
            np.testing.assert_allclose(df.interval_end_s, [5., 10.])
            np.testing.assert_allclose(df.decision_end_s-df.decision_start_s, 1.)
            self.assertTrue(audit_packets(df, cfg))
            if implementation == 'proposal':
                np.testing.assert_allclose(df.solve_ms, 1500.)
                metrics = evaluate(df, cfg)
                self.assertEqual(metrics['solver_budget_exceedances'], 2)
                self.assertEqual(metrics['decision_budget_exceedances'], 2)
                self.assertTrue(audit_metrics(df, pd.Series(metrics), cfg))
            else:
                np.testing.assert_allclose(df.solve_s, 1.5)
                self.assertEqual(summarize(df,cfg).solver_budget_exceedances.iloc[0], 2)

    def test_controllers_forecast_after_feedback_using_committed_history(self):
        cfg = Config(horizon=2)
        trace = make_trace(3, 28)
        for module in ('scheduling_policies','src.experiment'):
            radios = []
            def create(*args, **kwargs):
                radio = PacketRadio(*args, **kwargs)
                radios.append(radio)
                return radio
            def forecast(history, gain, horizon,**kwargs):
                radio = radios[0]
                self.assertEqual(radio.now_s, radio.interval*5.+.6)
                self.assertEqual(gain, radio.estimate)
                self.assertEqual(history['arrival'], list(trace['arrival'][:radio.interval]))
                self.assertEqual(history['harvest'], list(trace['harvest'][:radio.interval]))
                return raw_forecasts(history,gain,horizon,**kwargs)
            with self.subTest(module=module), patch(module+'.PacketRadio',side_effect=create), \
                 patch(module+'.raw_forecasts',side_effect=forecast):
                df = run(trace,cfg,'nominal') if module=='scheduling_policies' else run_policy(trace,'nominal',cfg)
            self.assertTrue(audit_packets(df,cfg))

    def test_exact_budget_boundary_and_deadline_policy(self):
        cfg = Config()
        records = []
        for solver, decision in ((1., 1.), (1.01, 1.02)):
            radio = PacketRadio(3, cfg)
            radio.probe(2., 1.)
            records.append(radio.execute(3., 3., 2., 0, 0., solver_runtime_s=solver,
                                         decision_runtime_s=decision))
        self.assertFalse(records[0]['solver_budget_exceeded'])
        self.assertFalse(records[0]['decision_budget_exceeded'])
        self.assertTrue(records[1]['solver_budget_exceeded'])
        for key in ('attempted_ids', 'acknowledged_ids', 'energy', 'E_next', 'interval_end_s'):
            self.assertEqual(records[0][key], records[1][key])

    def test_all_policies_timing_and_csv_audit_rejects_corruption(self):
        cfg = Config(horizon=2)
        trace = make_trace(3, 19)
        for mode in (*METHODS, 'fixed', 'channel', 'adaptive_guard50', 'adaptive_guard75',
                     'nominal_forced', 'adaptive_forced', 'adaptive_arrival_forced', 'adaptive_harvest_forced'):
            df = run(trace, cfg, mode)
            np.testing.assert_allclose(df.interval_end_s, [5., 10., 15.])
            self.assertTrue(audit_packets(df, cfg))
            if mode in ('greedy','fixed_fraction','fixed','channel'):
                self.assertEqual(df.loc[0, 'solver_runtime_s'], 0.)
        for mode in ('fixed', 'channel', 'greedy', 'nominal', 'robust', 'adaptive', 'adaptive_risk'):
            for backend in ('lp','cvxpy'):
                df = run_policy(trace, mode, cfg, backend=backend)
                np.testing.assert_allclose(df.interval_end_s, [5., 10., 15.])
                self.assertTrue(audit_packets(df, cfg))
        df = run(trace, cfg, 'greedy')
        restored = pd.read_csv(io.StringIO(df.to_csv(index=False)))
        self.assertTrue(audit_packets(restored, cfg))
        for field in ('channel_feedback_available_at_s', 'ack_processed_at_s',
                      'decision_end_s', 'arrivals_available_at_s', 'harvest_available_at_s',
                      'interval_end_s', 'solver_runtime_s', 'decision_budget_s'):
            bad = restored.copy(); bad.loc[0, field] += .1
            with self.subTest(field=field), self.assertRaises(AssertionError): audit_packets(bad,cfg)
        bad = restored.copy(); bad.loc[0,'decision_budget_exceeded'] = True
        with self.assertRaises(AssertionError): audit_packets(bad,cfg)

    def test_interval_lifecycle_prevents_early_reprobe_and_wrong_energy(self):
        radio = PacketRadio(1, Config())
        with self.assertRaises(RuntimeError): radio.execute(0., 0., 1., 0, 0.)
        radio.probe(1., .8)
        with self.assertRaises(RuntimeError): radio.probe(1., .4)
        with self.assertRaises(ValueError): radio.execute(0., 0., 2., 0, 0.)
        for solver, decision in ((-1.,0.),(2.,1.),(np.nan,1.),(0.,np.inf)):
            with self.assertRaises(ValueError):
                radio.execute(0.,0.,1.,0,0.,solver_runtime_s=solver,decision_runtime_s=decision)
        radio.execute(0., 0., 1., 0, 0.)
        with self.assertRaises(ValueError): radio.probe(.8, .8, t=0)


if __name__ == '__main__':
    unittest.main()
