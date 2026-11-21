# Five-packet actions and actual virtual-time packet delays

This stage changes only the attempted-service cap and measurement/output logic.
No production experiments or historical results were overwritten. The continuous
channel, numerical reports, forecasts, 256-bit payload, uniform 0–10 arrivals,
ACK/retry rules, buffer/battery, objective, 1,000-slot episodes, horizon 10 and
900-run design remain as documented in [experiments_1000.md](experiments_1000.md).

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

## Verification and benchmark

Focused tests cover A5 success/partial ACKs/failures, energy/action reduction,
power limits, integer roundoff, overflow after actual departures, the timing
example, duplicate/retry timestamps, initial exclusion, rejection/censoring,
empty observations, native solar seconds, complete output identities and audit
corruption. A no-ledger counterfactual produces identical scheduling/reception,
queue and battery results. Ledger operations draw no randomness.

The refreshed 1,000-slot nominal benchmark uses horizon 10, seed 6000, normalized
sigma 0.45, rho 0.68, harvest mean 0.6 J and cap five. Execution took **13.4600 s**,
with 994 optimization calls averaging **13.1270 ms** and no deadline overruns.
All accepted solver results were optimal; an intermediate inaccuracy warning was
handled by existing solver/verification rules. Maximum residual was 3.66235e-5.
All packet, battery, aggregate and delay-ledger/file audits passed.

Of 4,369 newly admitted packets, 4,360 were attempted/acknowledged and nine
remained never attempted. Completed-observation mean/median initial waits were
20.5541/21.6 s; ACK delays were 22.5667/23.6 s. Initial 12 packets were excluded.
These are benchmark diagnostics, not regenerated production-study findings.
Artifacts: `/tmp/ee541_a5_delay_benchmark_maxmm690/` contains `benchmark.json`,
`per_slot.csv`, `per_run.csv`, and `per_packet.csv`.

The full test command is:

```bash
MPLCONFIGDIR=/tmp/ee541-matplotlib .venv/bin/python -B -m unittest discover -s tests -v
```

The complete suite passed **92 tests in 59.714 seconds**; all **34 Python files**
passed syntax parsing. The temporary multi-policy CLI workflow checked both
synthetic sweeps, ten-policy solar, per-packet output identities, missing-aware
paired counts, analysis, physical/source/delay audits and offline reconstruction.
CSV chunk-boundary and corrupted-summary checks passed. The benchmark packet
file contains 4,882 records (12 initial plus 4,870 offered arrivals), independently
reconciled against slots and run summaries. Final file re-auditing also passed.

### Resumed verification, 20 November 2026

The saved 92-test log and benchmark records were inspected rather than assuming
their reported values. No simulator behavior needed changing. Two remaining
output/audit gaps were fixed:

- Packet-file auditing now checks every run-metadata field for consistency and
  independently recomputes the full `run_id` digest. Previously, changing the
  packet table's horizon to 999 could pass the audit. Metadata are also checked
  against matching slot and summary columns. Float metadata are parsed with
  round-trip precision so the digest preserves their original values.
- The older consistency-study summary now includes valid-run `count` alongside
  mean/std, including missing-aware delay statistics.

Focused tests now include separate scenarios with the same policy/seed and
overlapping packet IDs, one-row CSV chunks/runs, full metadata corruption and
high-precision metadata, plus a temporary artificial consistency workflow with
an empty delay cohort. Existing tests cover a run spanning multiple chunks,
end-of-file flushing, corrupted packet events/summaries and no completed packets.

The final complete suite passed **94 tests in 49.342 seconds**. The focused delay
suite passed **14 tests**; all **34 Python files** passed syntax parsing. The full
suite exercised the temporary synthetic/ten-policy solar CLI workflows, analysis,
physical/source/packet audits, offline reconstruction and figures. Artificial
solar fixtures remain test inputs only, with no real-window validation claimed.

The original benchmark was reused because only auditing, summary counts and
tests changed during the resumed work. Current packet/battery, aggregate,
delay-ledger and streaming identity audits all passed on its saved outputs:
`12 + 4,870 = 4,372 acknowledged + 501 rejected + 9 outstanding`.
Its original measured runtime remains 13.4600 s / 13.1270 ms per optimization
call, with zero decision-budget overruns; no new benchmark timing is implied.

Verification records are `/tmp/ee541_delay_resume_tests.log`,
`/tmp/ee541_delay_resume_focused.log` and
`/tmp/ee541_delay_resume_verification.json` (including benchmark file checksums).
The preceding full-suite record remains `/tmp/ee541_delay_tests.log`; benchmark
artifacts remain in `/tmp/ee541_a5_delay_benchmark_maxmm690/`.

The 300/300/300 run matrices, 1,000-slot defaults, horizon 10 and seed ranges were
rechecked. Production experiments were not launched and historical results were
not overwritten. At that checkpoint, before the subsequent downloads, the three
real inputs were missing:
`data/arco/dataset.csv`, `data/umass/homeC-generation.tar.gz`, and
`data/nrel/723170TYA.CSV`. This dependency has since been resolved by the real-input
verification below. Adaptive penalty-weight updates are excluded. The subsequent
[supplementary studies](supplementary_studies.md) prepare the two fixed
sensitivities separately from these completed packet-delay measurements.

### Real solar input verification, 20 November 2026

All three real inputs are now present and their SHA-256 values match both the
recorded references and the saved validation settings. The settings and run
matrix supplied in `results/solar_input_check_1000/` were preserved. Reconstruction
confirmed all 30 windows contain exactly 1,000 finite consecutive source samples,
all ten policies occur exactly once in each scenario, and the planned solar
matrix contains 300 unique policy-runs. Native intervals remain 60/60/3,600
seconds and energy factors remain 0.01/0.1/0.005. No data were padded or repeated.

ARCO and UMass each have ten disjoint selected windows. NREL's ten selected
windows have nine overlapping pairs: the sum of pairwise shared samples is
1,240 and the maximum pair overlaps by 138 samples (13.8%). These are dependent
source windows, not independent solar records or independent slot repetitions.
All recorded overlap counts/fractions were independently recalculated.
Checksums and reconstruction checks are saved in
[`input_verification.json`](../results/solar_input_check_1000/input_verification.json).

The real-input final-policy smoke command was:

```bash
MPLCONFIGDIR=/tmp/ee541-matplotlib .venv/bin/python -B final_solar_evaluation.py --windows 2 --slots 12 --horizon 10 --out results/solar_packet_delay_smoke_real
MPLCONFIGDIR=/tmp/ee541-matplotlib .venv/bin/python -B audit_comparison.py results/solar_packet_delay_smoke_real
MPLCONFIGDIR=/tmp/ee541-matplotlib .venv/bin/python -B audit_final_solar.py results/solar_packet_delay_smoke_real
```

This executed 60 short runs (three sources × two windows × ten policies), totaling
720 slots and 5,220 packet records. It exercised all integer actions 0–5, 25
failed attempts, 23 packets with retries and 20 intervals without an affordable
probe. Packet/battery conservation, full attempted/control energy, ACK-only
departures, native phase timestamps, delay/cohort reconstruction, complete run
identities and source/matrix audits all passed. Run-level mean/std/count and
missing-aware paired delay estimates/valid-pair counts were recalculated
independently. There were no solver or decision budget overruns.

All seven policies in the older simulator also passed real-input checks: three
sources × seven policies = 21 twelve-slot runs, totaling 252 slots and 1,827
packet records. They use prefixes of the first already validated 1,000-slot
window for each source, with original seeds and native intervals. Physical,
packet-ledger, planning-residual and streaming output audits passed.

The complete suite passed again: **94 tests in 50.470 seconds**; all **34 Python
files** passed syntax parsing. No simulator source or test code needed changing.
The saved synthetic benchmark remains valid and was not rerun. These short
real-input checks complete the action/delay verification and resolve the
missing-solar-input blocker; they are not production performance results.

Persistent evidence:

- [`verification.json`](../results/solar_packet_delay_smoke_real/verification.json),
  [`tests.log`](../results/solar_packet_delay_smoke_real/tests.log), run/analysis
  CSVs and [`per_packet.csv`](../results/solar_packet_delay_smoke_real/per_packet.csv).
- [`audit.json`](../results/solar_packet_delay_smoke_real/audit.json) and
  [`source_audit.json`](../results/solar_packet_delay_smoke_real/source_audit.json).
- [`legacy/verification.json`](../results/solar_packet_delay_smoke_real/legacy/verification.json)
  and its per-run, per-slot and per-packet tables.

The 900-run online production matrix and full offline studies remain unlaunched.
Proceed with the final system/model review before production. Adaptive penalty
updates are excluded; the two fixed supplementary studies are now prepared under
their [separate protocol](supplementary_studies.md).

Changed files:

- Core: `src/scheduling.py`, `src/radio.py`, `src/experiment.py`,
  `src/auditing.py`, new `src/packets.py` and `src/packet_audit.py`.
- Outputs/analysis: `proposal_study.py`, `final_evaluation.py`,
  `final_solar_evaluation.py`, `proposal_analyze.py`, `tune_proposal.py`,
  `consistency_study.py`, `offline_reference.py` (applicability metadata).
- Audit entry points: `audit_final_evaluation.py`, `audit_comparison.py`,
  `audit_proposal.py`.
- Tests: new `tests/test_packet_delays.py`, `tests/test_arrival_actions.py`,
  `tests/test_packet_execution.py`, `tests/test_audit_workflow.py`,
  `tests/test_receiver_feedback.py`, `tests/test_phase_timing.py`.
- Documentation: `README.md`, `FINAL_HANDOFF.md`, `docs/receiver_feedback.md`,
  `docs/experiments_1000.md`, and this specification.

Production remains deferred for the final system/model review. The real solar
inputs, all 30 native-source windows and short real-input execution checks are
now verified. Use the fresh-output commands in the experiment protocol when
production is authorized. Adaptive penalty updates are excluded; supplementary
sensitivities are documented separately and do not redefine delay measurements.
