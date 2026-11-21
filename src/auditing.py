"""Audit saved packet identities, ACK departures, reception draws and energy."""
import json
from dataclasses import replace
from types import SimpleNamespace
from math import fsum

import numpy as np
import pandas as pd

from .radio import reception_uniform
from .scheduling import Config, capacity
from .forecasting import ARRIVAL_MODEL
from .channel import CHANNEL_MODEL_VERSION
from .course_data import SOURCE_INTERVALS
from .packet_audit import audit_packet_ledger,audit_packet_outputs
from .packets import DELAY_MODEL


def saved_config(settings):
    if settings.get('radio_model') != 'gain-probe-ack-v3':
        raise ValueError('Saved results predate numerical gain feedback; regenerate them before auditing')
    if settings.get('arrival_model') != ARRIVAL_MODEL:
        raise ValueError('Saved arrival model differs from uniform 0..10; regenerate results before auditing')
    if settings.get('channel_model',{}).get('version') != CHANNEL_MODEL_VERSION:
        raise ValueError('Saved channel model differs from correlated lognormal; regenerate results')
    if settings.get('phase_timing_model') != 'fixed-phases-v1':
        raise ValueError('Saved results predate phased timing; regenerate results before auditing')
    if settings.get('packet_delay_model')!=DELAY_MODEL:
        raise ValueError('Saved results predate packet delay measurements; regenerate results before auditing')
    cfg=Config(**settings['config'])
    if settings['channel_model']!=cfg.channel_model.settings():raise ValueError('channel metadata/config mismatch')
    for key,name in (('rho','channel_rho'),('mean_normalize','channel_mean_normalize')):
        if key in settings and settings[key]!=getattr(cfg,name):raise ValueError(f'channel metadata/config mismatch: {key}')
    return cfg


def trajectory_config(settings, dataset=None,channel_sigma=None):
    cfg=saved_config(settings)
    intervals=settings.get('dataset_slot_seconds',SOURCE_INTERVALS)
    if dataset in intervals:cfg=replace(cfg,slot_seconds=intervals[dataset])
    return replace(cfg,channel_sigma=float(channel_sigma)) if channel_sigma is not None else cfg


def audit_metrics(frame, row, cfg):
    """Recalculate published trajectory metrics without calling their producer."""
    g=frame.sort_values('t')
    for name in ('queue','drop_ratio','energy','throughput','terminal_queue','realized_cost'):
        assert name in row.index, f'missing aggregate metric: {name}'
    total_energy=fsum(float(x) for x in g.energy)
    expected=dict(queue=float(np.mean(g.b)),drop_ratio=float(g['drop'].sum()/max(1.,g.arrivals.sum())),
                  energy=total_energy,data_energy=float(g.data_energy.sum()),control_energy=float(g.control_energy.sum()),
                  attempted=float(g.attempted.sum()),received=float(g.received.sum()),
                  acknowledged=float(g.acknowledged.sum()),delivered=float(g.delivered.sum()),
                  throughput=float(np.mean(g.delivered)*cfg.packet_bits/cfg.slot_seconds),
                  terminal_queue=float(g.b_next.iloc[-1]),
                  realized_cost=float(g.b.sum()+cfg.drop_weight*g['drop'].sum()
                                      +cfg.energy_weight*total_energy+cfg.terminal_weight*g.b_next.iloc[-1]),
                  max_violation=float(g.plan_violation.max()),
                  inaccurate=int((g.solver_status=='optimal_inaccurate').sum()),
                  mean_solve_ms=float(g.solve_ms.mean()),solve_ms=float(g.solve_ms.mean()))
    expected.update(mean_decision_ms=float(g.decision_runtime_s.mean()*1000),
                    max_solver_runtime_s=float(g.solver_runtime_s.max()),
                    max_decision_runtime_s=float(g.decision_runtime_s.max()),
                    solver_budget_exceedances=int(g.solver_budget_exceeded.sum()),
                    decision_budget_exceedances=int(g.decision_budget_exceeded.sum()))
    for source,target in (('covered_gain','gain'),('covered_arrival','arrival'),('covered_harvest','harvest')):
        expected['covered_'+target]=expected['coverage_'+target]=float(g[source].mean())
        expected['forecast_mae_'+target]=float(g['raw_error_'+target].abs().mean())
    for name,value in expected.items():
        if name in row.index:
            np.testing.assert_allclose(row[name],value,rtol=1e-8,atol=1e-7,equal_nan=True,
                                       err_msg=f'aggregate {name}')
    return True


def audit_timing(r, cfg):
    """Independently reconstruct phase/event times and host deadline checks."""
    start = r.t*cfg.slot_seconds
    elapsed = []
    np.testing.assert_allclose(r.interval_start_s,start,rtol=0,atol=1e-9)
    for phase,duration in (('probe',cfg.probe_seconds),('channel_report',cfg.channel_report_seconds),
                           ('decision',cfg.decision_seconds),('data',cfg.tau),
                           ('ack',cfg.ack_seconds),('update',cfg.update_seconds)):
        np.testing.assert_allclose(getattr(r,phase+'_start_s'),start+fsum(elapsed),rtol=0,atol=1e-9)
        elapsed.append(duration)
        np.testing.assert_allclose(getattr(r,phase+'_end_s'),start+fsum(elapsed),rtol=0,atol=1e-9)
    end = (r.t+1)*cfg.slot_seconds
    np.testing.assert_allclose([r.guard_start_s,r.guard_end_s,r.interval_end_s,r.guard_seconds],
                              [start+fsum(elapsed),end,end,cfg.slot_seconds-fsum(elapsed)],rtol=0,atol=1e-9)
    assert r.channel_report_end_s==r.decision_start_s
    assert r.decision_end_s==r.data_start_s and r.data_end_s==r.ack_start_s
    for name,value in (('channel_feedback_available_at_s',r.channel_report_end_s if r.probe_available else np.nan),
                       ('reception_completed_at_s',r.data_end_s if r.attempted else np.nan),
                       ('ack_processed_at_s',r.ack_end_s if r.exchange_available else np.nan),
                       ('next_state_available_at_s',end),('arrivals_available_at_s',end),
                       ('harvest_available_at_s',end),('history_available_at_s',end)):
        np.testing.assert_allclose(getattr(r,name),value,rtol=0,atol=1e-9,equal_nan=True,
                                   err_msg=name)
    assert np.isfinite(r.solver_runtime_s) and np.isfinite(r.decision_runtime_s)
    assert 0<=r.solver_runtime_s<=r.decision_runtime_s
    assert r.decision_budget_s==cfg.decision_seconds
    assert r.solver_budget_exceeded==(r.solver_runtime_s>cfg.decision_seconds)
    assert r.decision_budget_exceeded==(r.decision_runtime_s>cfg.decision_seconds)
    if hasattr(r,'solve_ms'):
        np.testing.assert_allclose(r.solve_ms,1000*r.solver_runtime_s,rtol=0,atol=1e-9)
    if hasattr(r,'solve_s'):
        np.testing.assert_allclose(r.solve_s,r.solver_runtime_s,rtol=0,atol=1e-12)


def audit_packets(frame, cfg, *, expected_seed=None, initial_state=None, channel_forecast_multipliers=None):
    """Replay logs, independently of PacketQueue/PacketRadio state updates."""
    frame = frame.sort_values('t')
    assert len(frame)>0, 'empty trajectory'
    np.testing.assert_array_equal(frame.t, np.arange(len(frame)))
    delivered = set()
    retries = {}
    next_id = None
    previous = None
    initial = None
    arrivals_total = drops_total = departures_total = 0
    channel_observation=None;channel_time=-1;previous_forecast=None;previous_margin=0.
    for r in frame.itertuples(index=False):
        c = cfg
        assert r.slot_seconds==c.slot_seconds, 'logged interval differs from model settings'
        audit_timing(r,c)
        assert np.isfinite(r.E) and 0<=r.E<=c.energy_max
        assert np.isfinite(r.harvest) and r.harvest>=0
        if expected_seed is None:expected_seed=r.reception_seed
        assert r.reception_seed==expected_seed, 'unmatched reception seed'
        names = ('queue_ids','queue_next_ids','attempted_ids','retry_numbers','received_ids',
                 'ack_ids','acknowledged_ids','delivered_ids','arrival_ids','overflow_ids','proactive_ids')
        ids = {name: json.loads(getattr(r, name)) for name in names}
        q, qn, att = ids['queue_ids'], ids['queue_next_ids'], ids['attempted_ids']
        for name in names:
            assert all(isinstance(i, int) and i >= 0 for i in ids[name]), name
        for values in (q, qn, att, ids['acknowledged_ids'], ids['delivered_ids']):
            assert len(values) == len(set(values))
        if previous is None:
            initial = len(q)
            if initial_state is not None:
                assert initial==initial_state['queue_packets']
                np.testing.assert_allclose(r.E,initial_state['energy_joules'],atol=1e-10)
            assert q == list(range(initial))
            next_id = initial
        else:
            assert q == previous.queue
            np.testing.assert_allclose(r.E, previous.energy, atol=1e-8)
        assert att == q[:len(att)]
        expected_retries = [retries.get(i, 0) for i in att]
        assert ids['retry_numbers'] == expected_retries
        for i, retry in zip(att, expected_retries):
            retries[i] = retry+1
        probe = r.E >= c.probe_energy
        report = probe and r.E >= fsum((c.probe_energy,c.channel_report_energy))
        exchange = report and r.E >= c.control_energy
        assert np.isfinite(r.gain) and r.gain>0 and r.actual_gain==r.gain
        assert r.probe_executed == probe and r.probe_available == report
        assert r.exchange_available == exchange
        if report:
            assert r.reported_gain==r.looked_up_gain==r.channel_estimate==r.gain
            channel_observation=r.reported_gain;channel_time=r.t
        else:
            assert np.isnan(r.reported_gain) and np.isnan(r.looked_up_gain) and np.isnan(r.channel_estimate)
        if hasattr(r,'forecast_current_gain'):
            # Independent Gaussian recursion; observations, never hidden gains,
            # initialize forecasts. Prior time -1 is before the first innovation.
            rho=c.channel_rho;variance=c.channel_sigma**2/(1-rho**2)
            center=variance/2 if c.channel_mean_normalize else 0.
            def forecast(target):
                if channel_observation is None:
                    return 1. if c.channel_mean_normalize else np.exp(.5*variance*(1-rho**(2*(target+1))))
                steps=target-channel_time;mean=np.log(channel_observation)+center;v=0.
                for _ in range(steps):mean=rho*mean;v=rho*rho*v+c.channel_sigma**2
                return channel_observation if not steps else np.exp(mean+v/2-center)
            assert r.channel_forecast_anchor_t==channel_time
            np.testing.assert_allclose(r.forecast_current_gain,forecast(r.t),rtol=1e-12)
            if r.t<len(frame)-1 and c.horizon>1:
                multiplier=1. if channel_forecast_multipliers is None else channel_forecast_multipliers[(r.t,1)]
                np.testing.assert_allclose(r.forecast_next_gain,forecast(r.t+1)*multiplier,rtol=1e-12)
            else:assert np.isnan(r.forecast_next_gain)
            if previous_forecast is not None:
                assert r.forecast_origin_t==r.t-1 and r.forecast_target_t==r.t
                assert r.forecast_channel_lead==r.t-previous_forecast[1]
                expected_error=previous_forecast[0]-r.reported_gain if report else np.nan
                np.testing.assert_allclose(r.raw_error_gain,expected_error,rtol=1e-12,equal_nan=True)
                if hasattr(r,'covered_gain'):
                    expected_covered=float(r.reported_gain>=max(1e-9,previous_forecast[0]-previous_margin)-1e-12) if report else np.nan
                    np.testing.assert_allclose(r.covered_gain,expected_covered,equal_nan=True)
            else:
                assert np.isnan(r.forecast_origin_t) and np.isnan(r.forecast_target_t) and np.isnan(r.forecast_channel_lead)
                assert np.isnan(r.raw_error_gain)
            previous_forecast=(r.forecast_next_gain,channel_time) if np.isfinite(r.forecast_next_gain) else None
            previous_margin=getattr(r,'margin_gain',0.)
        assert 0 <= r.p <= c.power_max+1e-8
        assert r.d == r.attempted == len(att) <= min(r.b, c.data_max)
        assert len(att) <= capacity(r.p, r.gain, c)+1e-8
        expected = [i for i, retry in zip(att, expected_retries)
                    if reception_uniform(r.reception_seed, i, retry) < c.success_probability]
        assert ids['received_ids'] == expected
        assert ids['ack_ids'] == expected  # reliable same-slot feedback
        ack = [i for i in q if i in set(ids['ack_ids'])]
        novel = list(dict.fromkeys(i for i in expected if i not in delivered))
        assert ids['acknowledged_ids'] == ack
        assert ids['delivered_ids'] == novel
        delivered.update(novel)
        assert r.received == len(expected) and r.acknowledged == len(ack)
        assert r.delivered == len(novel) and r.cumulative_delivered == len(delivered)
        assert ids['arrival_ids'] == list(range(next_id, next_id+int(r.arrivals)))
        next_id += int(r.arrivals)
        survivors = [i for i in q if i not in set(ack)]
        forced = max(0, len(survivors)+int(r.arrivals)-int(c.buffer_max))
        planned = int(getattr(r, 'planned_drop', 0))
        drop = max(forced, planned)
        arrivals = ids['arrival_ids']
        admitted = arrivals[:len(arrivals)-drop]
        assert ids['overflow_ids'] == (arrivals[len(arrivals)-forced:] if forced else [])
        assert ids['proactive_ids'] == arrivals[len(admitted):len(arrivals)-forced]
        assert qn == survivors+admitted
        assert r.b == len(q) <= c.buffer_max and r.b_next == len(qn) <= c.buffer_max
        assert r.drop == drop <= r.arrivals
        assert r.forced_drop == forced and r.proactive == drop-forced
        for count in (r.arrivals,r.b,r.b_next,r.d,r.received,r.acknowledged,r.delivered,r.drop):
            assert count >= 0 and count == int(count)
        components = [c.probe_energy if probe else 0.,c.channel_report_energy if report else 0.,
                      c.ack_energy if exchange else 0.]
        control = sum(components)
        np.testing.assert_allclose([r.probe_energy,r.channel_report_energy,r.ack_energy],
                                  components)
        np.testing.assert_allclose(r.other_control_energy,components[1]+components[2])
        np.testing.assert_allclose([r.data_energy,r.control_energy,r.energy],
                                  [r.p*c.tau,control,r.p*c.tau+control],atol=1e-9)
        assert r.energy <= r.E+1e-8
        if not exchange:
            assert not att and r.p == 0
        if not att:
            assert r.p == 0
        assert r.control_seconds == ((c.probe_seconds if probe else 0.)
                                    +(c.channel_report_seconds if report else 0.)+(c.ack_seconds if exchange else 0.))
        assert r.data_seconds == (c.tau if att else 0.)
        assert r.control_seconds+r.data_seconds <= c.slot_seconds+1e-12
        assert r.packet_bits == c.packet_bits
        np.testing.assert_allclose(r.throughput_bps,len(novel)*c.packet_bits/c.slot_seconds)
        pre = r.E-r.energy+r.harvest
        np.testing.assert_allclose([r.E_next,r.spill], [min(c.energy_max,pre),max(0.,pre-c.energy_max)],atol=1e-8)
        assert 0 <= r.E_next <= c.energy_max+1e-8
        arrivals_total += int(r.arrivals)
        drops_total += drop
        departures_total += len(ack)
        assert len(qn) == initial+arrivals_total-drops_total-departures_total
        previous = SimpleNamespace(queue=qn, energy=r.E_next)
    return True
