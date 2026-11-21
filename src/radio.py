"""Probe/report, identifiable FIFO packets, reliable ACKs and matched retries.

IDs are metadata: the 256 payload bits exclude IDs and feedback framing.
Control costs describe TX energy (including RX electronics for reports/ACKs).
"""
import hashlib
import json
from dataclasses import asdict

import numpy as np

from .scheduling import INITIAL_QUEUE,INITIAL_ENERGY,capacity,control_budget,execute_packets,validate_packet_inputs
from .forecasting import ARRIVAL_MODEL,ARRIVAL_MEAN
from .channel import valid_gain,gain_at,condition_at,CHANNEL_THRESHOLD
from .packets import PacketLedger,DELAY_MODEL


def reception_uniform(seed, packet_id, retry):
    """One policy/order-independent pseudorandom draw per packet attempt."""
    key = f'{int(seed)}:{int(packet_id)}:{int(retry)}'.encode('ascii')
    value = int.from_bytes(hashlib.blake2b(key, digest_size=8).digest(), 'big')
    return (value >> 11) / 2**53


def timing_metrics(frame):
    """Host runtimes/deadline flags, separate from simulated phase timestamps."""
    return dict(mean_decision_ms=float(frame.decision_runtime_s.mean()*1000),
                max_solver_runtime_s=float(frame.solver_runtime_s.max()),
                max_decision_runtime_s=float(frame.decision_runtime_s.max()),
                solver_budget_exceedances=int(frame.solver_budget_exceeded.sum()),
                decision_budget_exceedances=int(frame.decision_budget_exceeded.sum()))


def simulation_settings(cfg):
    return dict(config=asdict(cfg), radio_model='gain-probe-ack-v3',
                packet_delay_model=DELAY_MODEL,
                packet_timestamps='virtual seconds: initial admission 0 (prehistory unknown); new offers/admissions at interval end; first burst start; first ACK at ACK end; no within-burst serialization',
                delay_statistics='completed initial-wait/ACK-delay observations among newly admitted packets only; initial packets counted separately; unfinished delays missing, outstanding ages at episode end',
                phase_timing_model='fixed-phases-v1',
                phase_boundaries_seconds=cfg.phase_boundaries(),
                timing='virtual seconds; reserved windows also advance for A0/inactive slots; next queue, arrivals, harvest and history commit at interval end; no sleeping',
                decision_deadline='log-only: measure solver call and full decision separately against decision_seconds; flag overruns without changing action or simulated time',
                phase_energy_costs=dict(probe_joules=cfg.probe_energy,
                    channel_report_joules=cfg.channel_report_energy,ack_receive_joules=cfg.ack_energy,
                    data='applied power * tau; attempted packets including failures',
                    decision_joules=0.,update_joules=0.,guard_joules=0.,
                    assumption='durations do not imply hardware energy; decision/update/idle energy abstracted'),
                initial_state=dict(queue_packets=INITIAL_QUEUE,energy_joules=INITIAL_ENERGY),
                objective='sum(beginning backlog + drop_weight*rejected arrivals + energy_weight*total TX energy) + terminal_weight*final backlog',
                forecast='channel: conditional lognormal mean with actual observation gaps; arrivals: prior weight 8 at mean 5 (prior total 40); harvest: prior weight 8 at mean 1.1 until 3 samples, then last-12 mean',
                margins=dict(fixed=[.38,1.,.25],proposal_quantile=.8,proposal_window=50,
                             proposal_warmup=12,legacy_window=40,legacy_warmup=8,
                             timing='residuals from the current interval become available to the following decision'),
                arrival_model=ARRIVAL_MODEL, channel_model=cfg.channel_model.settings(),
                actions=f'whole attempted packets 0..{int(np.floor(cfg.data_max))}; continuous planner bound {cfg.data_max}',
                arrival_forecast='prior mean 5 with weight 8 (total 40); raw and adjusted estimates clipped to [0,10]; custom actual traces preserved',
                traffic_scenario='high_load',
                maximum_expected_service=int(np.floor(cfg.data_max))*cfg.success_probability,
                mean_arrival_excess=ARRIVAL_MEAN-int(np.floor(cfg.data_max))*cfg.success_probability,
                battery_accounting='subtract full data energy plus control energy before harvest; energy_weight scales objective penalty only',
                packet_success_probability=cfg.success_probability,
                channel_feedback='reliable exact numerical gain at channel_report_end_s, before decision_start_s; effective SNR per watt',
                ack_feedback='reliable at ack_end_s, including empty ACKs; only then remove acknowledged IDs',
                packet_accounting='IDs and timestamps are simulation metadata excluded from payload and control costs; delay bookkeeping adds no modeled energy',
                reception='independent bit errors, packet success (1-BER)^packet_bits; added to Shannon capacity',
                randomness='BLAKE2b(seed:packet_id:retry), retry 0 is first attempt; missing trace seed defaults to 0',
                control='affordable probe always charged; then affordable report and ACK stages; reserve ACK before data; harvest afterward',
                planning='continuous attempted service and expected goodput; future full controls relaxed to [0,1]; actual first-slot partial controls fixed',
                channel_baseline=f'2.4 W if reported gain >= {CHANNEL_THRESHOLD}, 0.45 W otherwise; latest numerical threshold preserved, battery clipped')


class PacketQueue:
    def __init__(self, initial, cfg):
        validate_packet_inputs([], initial, cfg)
        self.ids = list(range(int(initial)))
        self.next_id = int(initial)
        self.retries = {}
        self.limit = int(cfg.buffer_max)
        self.ledger=PacketLedger(int(initial))

    def attempts(self, count, *, time_s=0.):
        ids = self.ids[:count]
        retries = [self.retries.get(i, 0) for i in ids]
        for i, retry in zip(ids, retries):
            self.retries[i] = retry + 1
        self.ledger.attempts(ids,time_s)
        return ids, retries

    def acknowledge(self, ids, *, time_s=0.):
        ack = set(ids)
        removed = [i for i in self.ids if i in ack]
        self.ledger.acknowledge(removed,time_s)
        self.ids = [i for i in self.ids if i not in ack]
        for i in removed:
            self.retries.pop(i, None)
        return removed

    def arrive(self, count, planned_drop=0, *, time_s=0.):
        if count < 0 or int(count) != count:
            raise ValueError('arrivals must be nonnegative whole packets')
        arrivals = list(range(self.next_id, self.next_id + int(count)))
        self.next_id += int(count)  # IDs also belong to rejected arrivals.
        forced = max(0, len(self.ids) + len(arrivals) - self.limit)
        drop = max(forced, min(int(planned_drop), len(arrivals)))
        admitted = arrivals[:len(arrivals)-drop]
        # Reject the newest arrivals; preserve failed packets at the front.
        proactive_ids = arrivals[len(admitted):len(arrivals)-forced]
        overflow_ids = arrivals[len(arrivals)-forced:] if forced else []
        self.ids.extend(admitted)
        self.ledger.arrive(arrivals,overflow_ids,proactive_ids,time_s)
        return arrivals, overflow_ids, proactive_ids


class Receiver:
    def __init__(self, seed):
        self.seed = int(seed)
        self.delivered = set()

    def probe(self, gain):
        """Ideal numerical estimate from the held physical channel."""
        return valid_gain(gain)

    def receive(self, ids, retries, power, true_gain, cfg):
        # The radio sees truth; controllers see only probe reports.
        feasible = len(ids) <= float(capacity(power, true_gain, cfg)) + 1e-8
        received = [i for i, retry in zip(ids, retries)
                    if feasible and reception_uniform(self.seed, i, retry) < cfg.success_probability]
        new = list(dict.fromkeys(i for i in received if i not in self.delivered))
        self.delivered.update(new)
        return received, new  # Previously delivered packets can be ACKed again.


class PacketRadio:
    def __init__(self, initial, cfg, seed=0, trace=None):
        self.queue = PacketQueue(initial, cfg)
        self.receiver = Receiver(seed)
        self.cfg = cfg
        self.trace = trace
        self.now_s = 0.0
        self.interval = 0
        self._interval_open = False

    def _advance(self, timestamp):
        """Advance virtual time without waiting for wall-clock time."""
        if timestamp < self.now_s:
            raise AssertionError('simulation time cannot move backward')
        self.now_s = timestamp

    def probe(self, energy, gain=None, *, t=None):
        if self._interval_open:
            raise RuntimeError('finish the current interval before probing again')
        if not np.isfinite(energy) or not 0 <= energy <= self.cfg.energy_max:
            raise ValueError('beginning-slot energy must lie within battery limits')
        if t is not None and t != self.interval:
            raise ValueError('interval index must advance consecutively from zero')
        # Environment holds the selected true gain for probe and data.
        self.condition = condition_at(self.trace,self.interval) if self.trace is not None else 'continuous'
        true_gain=gain_at(self.trace,self.interval) if self.trace is not None else valid_gain(gain)
        self.phases = self.cfg.phase_boundaries(self.interval*self.cfg.slot_seconds)
        self._interval_open = True
        self.beginning_energy = energy
        self._true_gain = true_gain
        self.reported_condition = None
        self.estimate = np.nan
        self._advance(self.phases['probe_end_s'])
        self.controls = control_budget(energy, self.cfg)
        self.exchange = self.controls['exchange_available']
        self.control_energy = self.controls['control_energy']
        self._advance(self.phases['channel_report_end_s'])
        self.estimate = (valid_gain(self.receiver.probe(self._true_gain))
                         if self.controls['report_available'] else np.nan)
        return self.estimate, max(0., energy-self.control_energy)

    def execute(self, recommended, power, energy, arrival, harvest,
                *, fixed_power=False, planned_drop=0, on_update=None,
                solver_runtime_s=0., decision_runtime_s=0.):
        cfg = self.cfg
        if not self._interval_open:
            raise RuntimeError('probe phase must precede the data decision')
        if energy != self.beginning_energy:
            raise ValueError('data must use the same beginning-interval energy as the probe')
        if not np.isfinite(harvest) or harvest < 0:
            raise ValueError('harvest must be finite and nonnegative')
        if (not np.isfinite(solver_runtime_s) or not np.isfinite(decision_runtime_s)
                or not 0 <= solver_runtime_s <= decision_runtime_s):
            raise ValueError('runtimes must be finite, nonnegative and solver <= decision')
        before = list(self.queue.ids)
        available = max(0., energy-self.control_energy)
        self._advance(self.phases['decision_end_s'])
        attempted, power = (execute_packets(recommended, power, len(before), available,
                                           self.estimate, cfg, fixed_power=fixed_power)
                            if self.exchange else (0, 0.))
        ids, retries = self.queue.attempts(attempted,time_s=self.phases['data_start_s'])
        self._advance(self.phases['data_end_s'])
        received, delivered = self.receiver.receive(ids, retries, power, self._true_gain, cfg)
        self._advance(self.phases['ack_end_s'])
        # Reliable feedback is processed only after ACK reception.
        ack_ids = list(received)
        departed = self.queue.acknowledge(ack_ids,time_s=self.phases['ack_end_s'])
        data_energy = power*cfg.tau
        total = data_energy+self.control_energy
        pre = energy-total+harvest
        spill = max(0., pre-cfg.energy_max)
        after_energy = pre-spill
        if total > energy+1e-9 or not -1e-9 <= after_energy <= cfg.energy_max+1e-9:
            raise AssertionError('battery violation')
        # Prepare the next state during update, then commit at the next interval
        # boundary. New arrivals/harvest/history cannot inform this decision.
        self._advance(self.phases['update_end_s'])
        self._advance(self.phases['interval_end_s'])
        arrivals, overflow, proactive = self.queue.arrive(arrival, planned_drop,time_s=self.now_s)
        if on_update is not None:
            on_update()
        fields = dict(b=len(before), b_next=len(self.queue.ids), E=energy, E_next=after_energy,
                      gain=self._true_gain, condition=self.condition, reported_condition=self.reported_condition,
                      actual_gain=self._true_gain,reported_gain=self.estimate,
                      channel_estimate=self.estimate, looked_up_gain=self.estimate,
                      probe_available=self.controls['report_available'],
                      probe_executed=self.controls['probe_executed'], exchange_available=self.exchange,
                      p=power, d=attempted, attempted=attempted, received=len(received),
                      acknowledged=len(departed), delivered=len(delivered),
                      arrivals=arrival, harvest=harvest, drop=len(overflow)+len(proactive),
                      forced_drop=len(overflow), proactive=len(proactive), spill=spill,
                      data_energy=data_energy, control_energy=self.control_energy, energy=total,
                      probe_energy=self.controls['probe_energy'],
                      channel_report_energy=self.controls['channel_report_energy'],
                      ack_energy=self.controls['ack_energy'],
                      other_control_energy=self.controls['other_control_energy'],
                      control_seconds=self.controls['control_seconds'],
                      data_seconds=cfg.tau if attempted else 0.,
                      throughput_bps=len(delivered)*cfg.packet_bits/cfg.slot_seconds,
                      slot_seconds=cfg.slot_seconds, packet_bits=cfg.packet_bits,
                      cumulative_delivered=len(self.receiver.delivered), reception_seed=self.receiver.seed,
                      **self.phases, guard_seconds=cfg.guard_seconds,
                      channel_feedback_available_at_s=(self.phases['channel_report_end_s']
                                                       if self.controls['report_available'] else np.nan),
                      reception_completed_at_s=self.phases['data_end_s'] if attempted else np.nan,
                      ack_processed_at_s=self.phases['ack_end_s'] if self.exchange else np.nan,
                      next_state_available_at_s=self.now_s,arrivals_available_at_s=self.now_s,
                      harvest_available_at_s=self.now_s,history_available_at_s=self.now_s,
                      solver_runtime_s=solver_runtime_s,decision_runtime_s=decision_runtime_s,
                      decision_budget_s=cfg.decision_seconds,
                      solver_budget_exceeded=solver_runtime_s>cfg.decision_seconds,
                      decision_budget_exceeded=decision_runtime_s>cfg.decision_seconds)
        for name, values in dict(queue_ids=before, queue_next_ids=self.queue.ids,
                                 attempted_ids=ids, retry_numbers=retries, received_ids=received,
                                 ack_ids=ack_ids, acknowledged_ids=departed, delivered_ids=delivered,
                                 arrival_ids=arrivals, overflow_ids=overflow, proactive_ids=proactive).items():
            fields[name] = json.dumps(values)
        self.interval += 1
        self._interval_open = False
        return fields
