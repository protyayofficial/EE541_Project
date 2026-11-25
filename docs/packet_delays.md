# Five-packet actions and actual virtual-time packet delays

The simulator tracks identifiable 256-bit packets and records delays at
virtual event times. The primary experiment design and input assumptions are
described in the [experiment protocol](experiments_1000.md).

## Actions and energy

`Config.data_max=5.0` is the shared planner/execution bound. Executed actions are
integer 0–5; both planners retain continuous `0 <= d <= data_max*u`. Queue,
capacity, power and post-control battery constraints can reduce an action. Both
simulators/all policies use the shared bound. Explicit custom limits remain valid.
The existing solver-roundoff safeguard also handles 5-epsilon recommendations,
with an independent physical affordability check.

For actual attempted count k and reported gain g, minimum data power is
`expm1(log(2)*k*packet_bits/(bandwidth_hz*tau))/g`. MPC/greedy use that whole-count
power; fixed-power baselines retain their selected power when transmitting.
Energy is applied power × tau plus executed controls. Tau remains one second,
each executed probe costs 0.2 J including A0, and failures consume attempt energy.
Same-slot harvest cannot fund the action. Delay instrumentation adds no penalty;
the separate fixed sensitivity protocols are described in
[supplementary_studies.md](supplementary_studies.md).

With default BER, maximum expected service is `5*(1-BER)^256 = 4.98735675` packets
per interval, slightly below mean arrivals five. Power/energy shortages and
arrival variability can cause additional congestion. No traffic-load sweep changes.

## Timestamp conventions

All times are **virtual seconds from the start of a policy-run**. No host runtime
or random within-slot arrival/serialization timestamps are used. The same burst
start is recorded for every packet in that burst. The reserved five-second phase
schedule is unchanged; source intervals remain 60/60/3,600 seconds for solar.

| Field | Definition |
|---|---|
| `packet_id`, `is_initial` | Persistent ID and initial-queue membership |
| `offered_time_s` | New batch offered at interval end, including rejected arrivals; initial prehistory unknown/missing |
| `admission_time_s` | Interval boundary when admitted; initial packets use bookkeeping time 0; rejected packets missing |
| `first_attempt_time_s` | Data-phase start of the first burst containing the ID, preserved across retries |
| `first_ack_time_s` | ACK-phase end when the ID first departs the TX queue, preserved under duplicate ACKs |
| `attempt_count` | Every executed attempt, including failures; retained after departure |
| `status` | `acknowledged`, `rejected_before_admission`, or `outstanding` at episode end |
| `rejection_reason` | `overflow` or separately modeled `proactive`, otherwise missing |
| `initial_wait_s` | `first_attempt_time_s - admission_time_s`, missing until first attempt |
| `ack_completion_delay_s` | `first_ack_time_s - admission_time_s`, missing until departure |
| `outstanding_age_s` | Episode end minus admission for outstanding packets only |
| `initial_wait_unfinished` | Admitted/outstanding and never attempted |
| `ack_completion_unfinished` | Admitted/outstanding without completed ACK departure |
| `observation_end_s` | Full episode-end boundary, including final guard |

Admission/offer at a batch boundary is an explicit aggregation assumption: the
count trace contains no within-interval arrival times. Initial packets have
unknown prehistory; only admission 0 is assumed for bookkeeping. Their delays
are never included in the primary new-admission statistics. IDs/timestamps are
simulation metadata, adding no payload bits, random draws or modeled energy.

ACK-completion delay includes initial waiting, transmission, ACK reception and
any retry/energy-starvation intervals. It is **not pure queueing time**. Mean
queue occupancy remains a separate metric measured in packets.

| New packet example | Admission | First attempt | First ACK | Initial wait | ACK-completion delay |
|---|---:|---:|---:|---:|---:|
| First attempt succeeds | 5.0 | 6.6 | 8.6 | 1.6 | 3.6 |
| First attempt fails, next succeeds | 5.0 | 6.6 | 13.6 | 1.6 | 8.6 |

Rejected arrivals are never admitted: they have no attempt/ACK times or delays.
Outstanding packets keep missing ACK times and observed ages. Never-attempted
packets also keep missing first-attempt times. Ages are censoring information,
not fabricated completion times. Admissions at the terminal boundary are included
and have age zero with unfinished waiting/ACK events.

## Completed-observation cohorts and run-level summaries

Primary delay statistics use **newly admitted, non-initial packets**:

- `mean_initial_wait_s`, `median_initial_wait_s`: packets that have attempted,
  including attempted packets still awaiting an ACK.
- `mean_ack_completion_delay_s`, `median_ack_completion_delay_s`: acknowledged
  packets only. These are completed-observation means/medians, not unconditional
  means for all admissions. Different policies can have different admitted and
  completed cohorts; the counts and censoring must accompany comparisons.
- No eligible observations gives missing/NaN, never zero. No outstanding packets
  similarly gives missing age summaries.

Counts include `newly_admitted_packets`, `newly_attempted_packets`,
`newly_acknowledged_packets`, `rejected_arrivals`, `outstanding_packets`,
`newly_outstanding_packets`, `admitted_never_attempted_packets`,
`newly_never_attempted_packets`, `initial_wait_samples`,
`ack_completion_delay_samples`, `initial_wait_unfinished_packets` and
`ack_completion_delay_unfinished_packets`. Initial packets have separate total,
attempted, acknowledged, outstanding and never-attempted counts.

`mean/median/max_outstanding_age_s` cover all outstanding admissions;
`mean/median/max_new_outstanding_age_s` cover newly admitted outstanding packets.
Initial ages use the explicit bookkeeping origin, not unknown pre-simulation ages.

## Outputs, analysis and audits

- `per_packet.csv`: one offered/initial ID per completed run, appended once.
  Each row carries a stable `run_id` plus policy, seed, channel parameters,
  interval, horizon, action cap, initial state and configuration digest. Synthetic
  rows include sweep variant/harvest regime; solar rows include dataset/window.
  Packet identity is `(run_id, packet_id)`, never packet ID alone.
- `per_seed.csv` (synthetic), `per_window.csv` (solar/proposal): run IDs, all delay
  statistics and cohort counts alongside existing queue/energy/cost metrics.
- `summary.csv`: mean/std/count **of run-level statistics**, with valid-run count
  for each missing-aware delay metric. It does not pool packet observations.
- `paired_vs_nominal.csv` and older paired tables: four delay measures added;
  `n` and `n_valid_pairs` count matched runs where both estimates exist. With no
  valid pairs all estimates are missing; with one pair the CI is missing.

Both simulator APIs still return slot DataFrames. `src.packets.packet_table(df)`
exposes the event ledger and `run_delay_metrics(df)` returns run statistics.
In-memory ledgers use serializable DataFrame attrs; slot CSVs/concatenated frames
can reconstruct a ledger from their actual logged ID events and phase timestamps.
Separate policy-runs must be grouped before reconstruction.

`src/packet_audit.py` independently replays offered IDs, attempted IDs and ACK
departures from slots, without using the recording ledger. It verifies first
times/counts, duplicate safety, rejection, terminal censoring/ages and summary
means/medians. File audits stream packet CSVs in bounded chunks and bind them to
run IDs and existing physical audits. Current settings have
`packet_delay_model=virtual-packet-delays-v1`; results without measurements are
not silently treated as zero delay. The continuous offline reference has no
identifiable packets and supplies no packet-delay observations.
