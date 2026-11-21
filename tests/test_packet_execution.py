"""Whole-packet execution and accounting, independent of fluid planning."""
import unittest
from dataclasses import replace
from unittest.mock import patch

import numpy as np

from src.scheduling import Config, capacity, execute_packets
from src.experiment import make_trace, run_policy
from src.auditing import audit_packets
from proposal_study import METHODS, run


class PacketExecutionTests(unittest.TestCase):
    def test_fractional_recommendation_and_packet_bits(self):
        cfg = Config(bit_error_probability=0.)
        self.assertEqual(cfg.packet_bits, 256.)
        d, p = execute_packets(3.7, 3., 12, 7., 1., cfg)
        self.assertEqual(d, 3)
        self.assertEqual(d * cfg.packet_bits, 768)
        self.assertAlmostEqual(float(capacity(p, 1., cfg)), 3.)
        self.assertLess(p, 3.)
        limited, _ = execute_packets(3.7, 3., 2, 7., 1., cfg)
        self.assertEqual(limited, 2)
        limited, _ = execute_packets(3.7, 3., 12, 7., 1., replace(cfg, data_max=2.5))
        self.assertEqual(limited, 2)

    def test_insufficient_channel_or_battery_sends_nothing(self):
        cfg = Config(bit_error_probability=0.)
        for gain, energy in ((0., 7.), (.001, 7.), (1., .001), (1., 0.)):
            for fixed in (False, True):
                with self.subTest(gain=gain, energy=energy, fixed=fixed):
                    self.assertEqual(execute_packets(3.7, 3., 12, energy, gain, cfg,
                                                     fixed_power=fixed), (0, 0.))

    def test_zero_backlog_and_near_integer_limits(self):
        cfg = Config(bit_error_probability=0.)
        self.assertEqual(execute_packets(3.7, 3., 0, 7., 1., cfg), (0, 0.))
        # No upward tolerance may exceed recommendation, queue or service cap.
        below_three = np.nextafter(3., 0.)
        for recommended, queue, service in ((below_three, 12, 3.),
                                            (3.7, below_three, 3.),
                                            (3.7, 12, below_three)):
            d, p = execute_packets(recommended, 3., queue, 7., 1.,
                                   replace(cfg, data_max=service))
            self.assertLessEqual(d, min(recommended, queue, service))
            self.assertLessEqual(p, cfg.power_max)
            self.assertLessEqual(d, float(capacity(p, 1., cfg))+1e-12)
        one_packet_power = float(np.expm1(np.log(2)/cfg.rate_scale))
        for budget in (np.nextafter(one_packet_power, 0.), one_packet_power):
            d, p = execute_packets(3.7, budget, 12, budget*cfg.tau, 1., cfg)
            self.assertLessEqual(p, budget)
            self.assertLessEqual(p*cfg.tau, budget*cfg.tau)
            self.assertLessEqual(d, float(capacity(budget, 1., cfg)))

    def test_shared_packet_size_controls_capacity_and_throughput(self):
        cfg = replace(Config(bit_error_probability=0.), packet_bits=512., data_max=3.)
        self.assertAlmostEqual(float(capacity(1., 1., cfg)),
                               cfg.bandwidth_hz*cfg.tau/512.)
        trace = make_trace(2, seed=42)
        trace['gain'][:] = 1.
        trace['condition'][:] = 'Excellent'
        trace['arrival'][:] = 0.
        for df in (run(trace, cfg, 'greedy'), run_policy(trace, 'greedy', cfg)):
            np.testing.assert_array_equal(df.d, [3, 3])
            np.testing.assert_allclose(df.throughput_bps*cfg.slot_seconds, 1536.)
        limited_cfg = replace(cfg,power_max=.001)
        for mode in ('greedy', 'fixed', 'channel'):
            for df in (run(trace, limited_cfg, mode), run_policy(trace, mode, limited_cfg)):
                np.testing.assert_array_equal(df.d, 0)
                np.testing.assert_array_equal(df.p, 0.)
                np.testing.assert_array_equal(df.throughput_bps, 0.)

    def test_fixed_power_is_preserved_only_when_sending(self):
        cfg = Config(bit_error_probability=0.)
        self.assertEqual(execute_packets(3.7, 1.2, 12, 7., 1., cfg,
                                         fixed_power=True), (3, 1.2))
        self.assertEqual(execute_packets(0., 1.2, 12, 7., 1., cfg,
                                         fixed_power=True), (0, 0.))

    @staticmethod
    def plan():
        return dict(p=np.array([1.2]), d=np.array([3.7]), o=np.array([2.7]),
                    max_violation=0., status='optimal', solver='mock')

    def test_current_execution_overflow_and_metrics(self):
        cfg = Config(bit_error_probability=0.)
        # First slot leaves 12 - 3 + 22 = 31; second leaves 32 with one drop.
        trace = dict(gain=np.ones(2), arrival=np.array([22., 5.]), harvest=np.zeros(2))
        with patch('proposal_study.solve_cvxpy', return_value=self.plan()):
            df = run(trace, cfg, 'nominal')
        self.assertEqual(df.b.iloc[1], 31)
        self.assertEqual(df.d.iloc[1], 3)
        self.assertEqual(df['drop'].iloc[1], 1)
        self.assertEqual((df.b-df.acknowledged+df.arrivals-df['drop']).iloc[1], 32)
        np.testing.assert_allclose(df.throughput_bps * cfg.slot_seconds, 768.)
        np.testing.assert_allclose(df.energy, df.p * cfg.tau+cfg.control_energy)
        self.assertAlmostEqual(df.E.iloc[1], 7.-df.energy.iloc[0])
        np.testing.assert_allclose(capacity(df.p, df.gain, cfg), df.d)

    def test_legacy_overflow_and_proactive_rejection(self):
        cfg = Config(bit_error_probability=0.)
        trace = make_trace(2, seed=42)
        trace['gain'][:] = 1.
        trace['condition'][:] = 'Excellent'
        trace['arrival'][:] = 5.
        with patch('src.experiment.solve_lp', return_value=self.plan()), \
             patch('src.experiment.verify_plan', return_value={'mock': 0.}):
            overflow = run_policy(trace, 'nominal', cfg, b0=31, allow_proactive=False)
            proactive = run_policy(trace, 'nominal', cfg, b0=12, allow_proactive=True)
        self.assertEqual(overflow.d.iloc[0], 3)
        self.assertEqual(overflow.forced_drop.iloc[0], 1)
        self.assertEqual(overflow.b.iloc[1], 32)
        self.assertEqual(proactive.planned_drop.iloc[0], 2)
        self.assertEqual(proactive.proactive.iloc[0], 2)
        self.assertEqual(proactive.forced_drop.iloc[0], 0)
        np.testing.assert_array_equal(proactive['drop'], proactive.forced_drop+proactive.proactive)

    def test_invalid_actual_counts_are_rejected(self):
        cfg = Config(bit_error_probability=0.)
        for value in (1.5, -1., np.nan, np.inf):
            trace = make_trace(3, seed=42)
            trace['arrival'] = trace['arrival'].astype(float)
            trace['arrival'][0] = value
            with self.assertRaises(ValueError):
                run(trace, cfg, 'greedy')
            with self.assertRaises(ValueError):
                run_policy(trace, 'greedy', cfg)
        trace = make_trace(3, seed=42)
        for initial in (1.5, -1., np.nan, np.inf, 33.):
            with self.assertRaises(ValueError):
                run_policy(trace, 'greedy', cfg, b0=initial)
        for runner in (lambda c: run(trace, c, 'greedy'),
                       lambda c: run_policy(trace, 'greedy', c)):
            with self.assertRaises(ValueError):
                runner(replace(cfg, buffer_max=32.5))

    def test_all_policies_keep_actual_counts_integral_and_account_actions(self):
        cfg = replace(Config(), horizon=3)
        trace = make_trace(5, seed=42)
        current = (*METHODS, 'fixed', 'channel', 'adaptive_guard50', 'adaptive_guard75',
                   'nominal_forced', 'adaptive_forced', 'adaptive_arrival_forced',
                   'adaptive_harvest_forced')
        cases = [(mode, lambda m=mode: run(trace, cfg, m)) for mode in current]
        for backend in ('lp', 'cvxpy'):
            for mode in ('fixed', 'channel', 'greedy', 'nominal', 'robust', 'adaptive', 'adaptive_risk'):
                cases.append((f'legacy/{backend}/{mode}',
                              lambda m=mode, be=backend: run_policy(trace, m, cfg, backend=be)))
        for label, simulate in cases:
            with self.subTest(policy=label):
                df = simulate()
                self.assertTrue(audit_packets(df,cfg))
                self.assertEqual(cfg.data_max,5.)
                self.assertTrue(df.attempted.isin(range(int(cfg.data_max)+1)).all())
                np.testing.assert_array_equal(df.arrivals,trace['arrival'])
                np.testing.assert_array_equal(df.condition,trace['condition'])
                np.testing.assert_array_equal(df.probe_energy,.2*df.probe_executed)
                for field in ('arrivals', 'b', 'd', 'drop', 'forced_drop', 'planned_drop', 'proactive'):
                    if field in df:
                        np.testing.assert_array_equal(df[field], np.floor(df[field]))
                next_queue = df.b-df.acknowledged+df.arrivals-df['drop']
                np.testing.assert_array_equal(next_queue, np.floor(next_queue))
                np.testing.assert_array_equal(df.b.iloc[1:], next_queue.iloc[:-1])
                self.assertEqual(next_queue.iloc[-1],
                                 df.b.iloc[0]+df.arrivals.sum()-df.acknowledged.sum()-df['drop'].sum())
                if 'planned_drop' in df:
                    np.testing.assert_array_equal(df['drop'], df.forced_drop+df.proactive)
                    self.assertTrue((df['drop'] <= df.arrivals).all())
                    self.assertTrue((df.planned_drop <= df.arrivals).all())
                else:
                    np.testing.assert_array_equal(df['drop'],
                        np.maximum(0, df.b-df.acknowledged+df.arrivals-cfg.buffer_max))
                    np.testing.assert_allclose(df.energy, df.p*cfg.tau+df.control_energy)
                self.assertTrue(((next_queue >= 0) & (next_queue <= cfg.buffer_max)).all())
                np.testing.assert_allclose(df.throughput_bps, df.delivered*256./cfg.slot_seconds)
                self.assertTrue((df.p[df.d == 0] == 0).all())
                self.assertTrue((df.p*cfg.tau <= df.E+1e-8).all())
                self.assertTrue((df.d <= capacity(df.p, df.gain, cfg)+1e-8).all())
                np.testing.assert_allclose(df.E.iloc[1:],
                    np.minimum(cfg.energy_max, df.E-df.energy+df.harvest).iloc[:-1])
                mode = label.rsplit('/', 1)[-1]
                if mode in ('fixed', 'channel', 'fixed_fraction'):
                    target = (np.full(len(df), 1.2) if mode == 'fixed' else
                              np.where(df.channel_estimate >= .8, 2.4, .45) if mode == 'channel' else
                              (1.1/cfg.energy_max)*(df.E-df.control_energy)/cfg.tau)
                    expected = np.minimum(np.minimum(target, cfg.power_max), (df.E-df.control_energy)/cfg.tau)
                    np.testing.assert_allclose(df.p[df.d > 0], expected[df.d > 0])
                else:
                    np.testing.assert_allclose(capacity(df.p, df.gain, cfg), df.d, atol=1e-8)


if __name__ == '__main__':
    unittest.main()
