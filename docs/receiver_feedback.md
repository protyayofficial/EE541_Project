# Probe, receiver feedback and retransmission model

This implementation supersedes the execution assumptions behind all saved
experiments. No saved results were regenerated during this implementation stage.
The submitted proposal remains a historical document.

## Arrivals and attempted actions

New synthetic traffic, including traffic paired with solar harvest traces, uses
IID discrete uniform integer arrivals on `{0,1,...,10}` packets per interval.
Each of the eleven counts has probability `1/11`, so the mean is `5`. `make_trace` generates
the shared seeded arrival trace; all policies receive that same trace, and solar
callers replace only harvested energy. Arrival generation has no tunable Poisson
mean. The generator uses `rng.integers(0,11,size=n)` and returns integer arrays.
Custom deterministic traces remain supported; fractional actual counts are rejected.

`Config.data_max = 5.0` sets the attempted-service bound in both planners and
every policy in both simulators. Execution attempts only `0`, `1`, `2`, `3`, `4`, or `5`
packets, further limited by backlog, channel capacity and available battery.
The convex planner remains continuous, with `0 <= d <= 5` and expected service
`success_probability*d`. No packets are removed merely because they were
attempted; the existing ACK and retry rules below still apply.

The arrival predictor starts with mean `5` and prior weight `8` (prior total
`40`), then uses `(40 + sum(observed arrivals))/(8 + number observed)`. Raw arrival forecasts and
uncertainty-adjusted arrival estimates are clipped to `[0,10]`; the same clipped
bound is used for coverage reporting. Legacy oracle forecast arrays are also
bounded, although controllers do not use them. Custom deterministic traces may
still contain other nonnegative whole counts (for example bursts above ten
in conservation tests). These actual inputs are never clipped or resampled;
only predictions use the declared stochastic support. Direct planning fixtures
may also supply deterministic inputs outside the generated distribution.

Obsolete assumptions removed from active experiment code were the Poisson
generator and `arrival_mean=2.5` callers, the forecast prior of `2.5`, clipping
Poisson arrivals at `10` in synthetic/solar/offline/solver paths, the varying Poisson means
in solver fixtures, the corresponding source-audit reconstruction and settings,
and the default `data_max=10.0`. Historical saved results and the submitted
proposal retain their original assumptions; they do not describe the current
arrival and action model.

This is a **high-load scenario**. Mean offered traffic is 5 packets per interval,
while at most 5 packets can be attempted. With the default reception probability,
maximum expected successful service is approximately `4.98735675` packets per
interval. The excess is at least `0.01264325` packets per interval before energy
shortages, so persistent congestion and overflow are expected. This loading is
intentional; actions remain 0–5, and queue departures still require ACKs. Forced
overflow uses the actual queue after ACK departures and new arrivals:
`max(0, outstanding_before - acknowledged + arrivals - buffer_capacity)`.

The earlier uniform 1–5 / mean-3 scenario is obsolete for current experiments.
Settings and audits distinguish it from this uniform 0–10 scenario; existing
saved results must be regenerated before being used to describe the new load.

## Correlated continuous channel and numerical feedback

`src/channel.py` defines `ChannelModel` (version `correlated-lognormal-v1`).
Each interval updates a latent log-channel as
`x[t] = rho*x[t-1] + Normal(0,sigma)`, then holds its gain through probe/data.
`rho=0.68`; synthetic innovations are `sigma=0.20,0.45,0.80`. There is no gain
quantization or upper cap. The original variant starts `x[-1]=0` and uses
`gain=exp(x)`. The normalized variant starts `x[-1]~Normal(0,sqrt(v))`, where
`v=sigma^2/(1-rho^2)`, and uses `gain=exp(x-v/2)`. Only the theoretical stationary
mean is normalized; the episode's realized mean is never used. Invalid/nonpositive
or nonfinite gains, including exponential under/overflow, raise explicit errors.

The existing separate channel stream `default_rng(SeedSequence([seed,42017]))`
is retained, independent of traffic/harvest and policy actions. Saved historical
settings verify the model variants and seed ranges; the empty `.git` directory
provides no old source/draw ordering. Exact historical channel samples are not
claimed. New settings make the stream and initialization reproducible.

RX returns the exact numerical gain after its feedback phase. TX uses that report
for power, forecasts and history; physical reception keeps the held hidden gain.
Gains remain effective SNR per watt, not RSSI. Optional `condition` labels are
purely descriptive; `reported_condition` is retired (empty). No lookup table is in
the active path. Arbitrary positive deterministic gain traces remain supported.

For a report `g` observed at time `s`, the conditional mean at `s+k` is
`exp(rho^k*(log(g)+c) + 0.5*v*(1-rho^(2*k)) - c)`, with `c=0` for original and
`c=v/2` for normalized channels. Lead zero preserves the exact report. Missed
probes leave the current report missing; forecasts use the last report's actual
time gap, never the hidden current gain. Before any report, normalized forecasts
are one; original forecasts at interval `t` use transient variance
`v*(1-rho^(2*(t+1)))` from the zero initial log-state at `t=-1`.

Future planning gains (including nominal) use only a numerical floor `1e-9`; no
five-state clipping remains. The observed current gain is not adjusted. Error logs identify
origin, target, observation anchor and actual lead. Missing report errors are NaN;
rolling quantiles use the latest finite scores per component (50/12 warmup in the
proposal simulator, 40/8 in the older one). Scores may have different observation
leads after gaps and remain pooled empirical margins, not coverage guarantees.
Arrival/harvest predictors and their bounds are unchanged. See the
[current experiment protocol](experiments_1000.md) for matrices, benchmarks and commands.

## Virtual phase timing

`Config.phase_boundaries(start_s)` is the shared source of reserved phase windows
for both simulators and every policy. `tau` remains the data-burst duration;
`probe_seconds`, `channel_report_seconds`, `decision_seconds`, `ack_seconds` and
`update_seconds` configure the other phases. Guard/idle is derived as
`slot_seconds - (probe_seconds + channel_report_seconds + decision_seconds + tau + ack_seconds + update_seconds)`.
All durations must be finite and nonnegative (data duration and interval strictly
positive), and the sum must fit the interval. Zero guard is supported.

| Phase | Default duration (s) | Default synthetic window (s) | Modeled TX energy |
|---|---:|---|---|
| Probe transmission | 0.30 | 0.00–0.30 | `probe_energy = 0.2 J` if executed |
| Numerical channel feedback | 0.30 | 0.30–0.60 | `channel_report_energy = 0 J` if received |
| Scheduling decision | 1.00 | 0.60–1.60 | 0 J abstraction |
| Data burst | 1.00 (`tau`) | 1.60–2.60 | applied power × `tau`, including failures |
| ACK reception | 1.00 | 2.60–3.60 | `ack_energy = 0 J` if received, including empty ACKs |
| State/history update | 1.00 | 3.60–4.60 | 0 J abstraction |
| Guard/idle | 0.40 (derived) | 4.60–5.00 | 0 J abstraction |

These are **virtual times**, advanced computationally without sleeping. Reserved
windows advance even for A0, an empty queue or an energy-starved interval.
The environment holds the selected gain throughout probe and data.
RX's numerical gain becomes available only at the end of the feedback window,
before any forecast or decision. Reception outcomes are obtained at data end;
successful IDs remove outstanding packets only at ACK end. The update window
prepares the next queue/battery and history. Arrival admission, harvest credit
and prepared history are committed at interval end, after guard, for use by the
following decision. No arrivals or harvest from this interval fund its data action.
There is no second action in the update or guard window.

Solar sources retain their source intervals: ARCO and UMass use 60 seconds;
NREL TMY3 uses 3,600 seconds. The same 4.6 seconds of configured phases leave
55.4 and 3,595.4 seconds of guard respectively. Settings record source interval
lengths separately from the synthetic default; per-slot phase timestamps use
the actual source interval. Packet arrivals and channel draws occur once per
source interval. Throughput continues to divide by that full interval.

Durations do not determine energy. Probe/report/ACK costs are independent
configuration fields. TX computation during decision/update and idle hardware
consumption are abstracted as zero, irrespective of their duration. Receiver-side
energy is outside the TX battery model. Data energy uses the configured `tau`,
which remains one second; it never uses the full interval or guard duration.

`solver_runtime_s` measures elapsed host time around the solver function call,
including formulation, compilation, solving/fallback and its internal checks.
`decision_runtime_s` additionally includes forecasting, uncertainty adjustment,
external plan checks and action selection; it excludes radio execution, ACK
processing and state/history bookkeeping. The previous aliases `solve_ms`
(proposal) and `solve_s` (older simulator) now refer to this solver-call runtime;
heuristics record zero solver time. Both measurements are checked against
`decision_seconds` (default one second). Equality meets the budget; a greater
runtime sets the corresponding `*_budget_exceeded` flag. Aggregate metrics report
exceedance counts, mean decision time and maximum runtimes. This is a **log-only
deadline model**: overruns retain the computed action and reserved virtual times,
so host speed cannot change policy outcomes. It does not simulate real-time
deadline fallback or guarantee that every solve finishes in one second.

## One scheduling interval

1. If beginning-slot energy is below the configured probe cost (default
   **0.2 J**), mark the interval inactive: no probe, no report, no data, and zero
   control/data expenditure. Retain outstanding IDs; process arrivals and harvest.
   A previous channel report is never reused as a fresh current observation.
2. If the probe is affordable, execute it and charge its configured cost exactly
   once, even if the eventual data action is A0 or the queue is empty. RX reports
   the numerical gain reliably after the channel-feedback phase if TX can afford the
   configured report receive cost. Reserve the ACK receive cost before allowing data;
   it is accounted for once with the ACK stage. Costs of
   these two feedback stages default to zero. With nonzero configured feedback
   costs, an unaffordable later stage does not undo the executed probe: pay only
   the affordable prefix of probe/report/ACK stages and skip data. If a report
   was received, keep it logged even if the ACK reserve is unaffordable.
3. Convert the continuous recommendation into a feasible whole-packet attempt
   count, using the numerical report and energy remaining after control reserves.
   Attempt the first outstanding IDs once each. MPC and greedy recompute minimum
   Shannon power for the whole count; A0 uses zero data power. Solver actions
   within `1e-6` packets of an integer are normalized only if its required power
   is within `1e-6` W of the recommendation and the actual post-control energy,
   power, backlog and action bounds support it. This prevents `3-epsilon` solver
   outputs from consistently executing A2. Genuine fractions still floor, and
   an unaffordable rounded action never executes. Fixed-power
   baselines retain their selected power, clipped to the remaining battery. The
   fixed baseline selects 1.2 W. The channel-aware baseline selects 2.4 W for
   reported gain >= 0.8 and 0.45 W otherwise. The latest numerical
   threshold 0.8 is preserved without tuning; historical threshold 1.1 is not restored. Fixed-fraction uses the remaining energy.
4. RX applies independent packet outcomes. Packet success probability is
   `s = (1 - bit_error_probability)^packet_bits`. Default BER `9.89e-6` and
   `packet_bits = 256.0` imply approximately 0.253% packet loss. Conditional on
   the attempt count, received count is binomial. This error process remains a
   simulation assumption added to Shannon capacity, without a BER-versus-SNR
   curve or additional modulation/coding assumptions.
5. RX returns received packet IDs reliably at the end of ACK reception. TX removes only
   acknowledged outstanding IDs, once each. Failed IDs remain at the front for
   retransmission. RX can acknowledge duplicate receptions again without counting
   duplicate delivered payload. Reliable same-slot ACKs normally prevent duplicates;
   the receiver and queue primitives preserve idempotence.
6. Prepare the next state during the update window and commit at interval end.
   Assign IDs to every arrival, including rejected arrivals. Append admitted
   arrivals and reject the newest arrivals to enforce buffer capacity. The older
   simulator optionally applies its whole-packet planned total rejection target:
   total rejection is the maximum of that target and forced overflow. Additional
   rejection is logged separately as proactive rejection.
7. Debit total data and control energy, add harvested energy, and spill any excess
   above battery capacity. Same-slot harvest cannot fund the current exchange.

Physical consumption is `energy = data_energy + probe_energy + other_control_energy`,
where `data_energy = tau*p` charges all attempts, including failures, and
`other_control_energy = channel_report_energy + ack_energy` records executed
feedback stages. Total expenditure cannot exceed beginning-slot energy. The end
battery is `min(energy_max, E - energy + harvest)`. `energy_weight` scales the
objective penalty only; it never discounts the physical joules debited.

Initial IDs are `0..b0-1`, with monotonically increasing arrival IDs regardless
of overflow. IDs are metadata, excluded from the 256 payload bits and control
framing costs. Receiver-side energy is outside the TX battery model. Probe cost
is configurable with default 0.2 J; report and ACK costs default to zero.
Affordable empty ACK feedback is charged under the same stage rules as
data-bearing feedback. All seven timing windows follow the separate duration
configuration above, including when a physical exchange is skipped.

## Shannon energy verification examples

With `packet_bits=256`, `bandwidth_hz=3000`, and `tau=1` second, minimum-power
execution for `k` attempted packets and reported gain `g` calculates
`p = (2**(k*packet_bits/(bandwidth_hz*tau)) - 1)/g`, with `p=0` for A0.
Energy is `tau*p + 0.2` when the other feedback costs are zero.

| Numerical gain/action | Total TX energy (J), rounded |
|---|---:|
| Any gain, A0 | 0.2000000 |
| Gain 0.2, A3 | 1.1708159 |
| Gain 0.8, A3 | 0.4427040 |
| Gain 1.0, A3 | 0.3941632 |

These are calculated model checks for MPC/greedy execution, not hard-coded energy
prices. Fixed-power baselines pay their actual selected-power data cost plus the
same executed probe and feedback charges.

## Reproducibility and causality

Each reception draw hashes `(scenario seed, packet ID, retry number)` with BLAKE2b;
retry 0 is the first attempt. It uses no shared random-generator state and never
depends on policy name, execution order, or future data. Policies share the draw
for a given ID and retry, even if they attempt it in different intervals. Both
trace generators preserve the scenario `seed`; a hand-built trace without one
uses documented seed 0. `reception_seed` is logged for replay.

Both simulators use current numerical probe reports and the conditional means
above. Observation times survive missed probes. One-step target forecasts are
created every interval, including inactive intervals, and scored only against
fresh reports at their exact target. True future gains and historical oracle
forecast arrays are never controller inputs. Arrival and harvest histories become
available only at the next interval boundary.

## Continuous planning

The planner's `d` is attempted service. The queue balance is
`b[t+1] = b[t] - s*d[t] + arrival[t] - rejection[t]`. CVXPY, the conservative
Shannon LP approximation, and independent plan verification use the same balance.
Data availability constrains attempts by beginning-slot backlog. The optional
first-slot rejection cap also uses expected successful service.

Control activation `u` is continuous in `[0,1]` for future planned slots, with
`p <= power_max*u`, `d <= data_max*u`, and energy expenditure
`tau*p + control_energy*u`. First-slot activation is fixed by actual beginning
battery availability for the full exchange. If only a prefix of the configured
control stages is affordable, that fixed first-slot cost is included as an
additional constant in the energy balance and objective, with no data permitted.
Both CVXPY and the LP approximation include the same constant; `planned_energy`
and plan verification reconstruct it. Current-slot probe activity thus follows
actual affordability even when later feedback is unaffordable.

Future fractional control activation remains a relaxation. At default 0.2 J
probe overhead it can understate future full-probe costs; physical execution
always charges complete executed stages. Planning is not an exact stochastic
control model. CVXPY checks DCP compliance before solving; the LP uses affine
constraints and a conservative piecewise-linear capacity approximation. Actual
queues contain identifiable whole packets.

The full-horizon offline reference uses deterministic expected goodput with
perfect future exogenous inputs, continuous states/attempts, optional proactive
rejection, and relaxed future control activation. Its objective is not the
expected objective of the stochastic queue, nor a pathwise lower bound on realized
online costs. Online-minus-reference values are descriptive differences; tests
and audits do not impose a sign on them. The numerical primal solution also
does not certify optimality.

## Packet delays

[The packet-delay specification](packet_delays.md) defines the event ledger,
initial-packet exclusion, rejected/unfinished cohorts, completed-observation
means/medians, run-level paired counts and independent replay audits. These
measurements add no simulated energy or random draws and are not objective terms.

## Log and metric meanings

| Fields | Meaning |
|---|---|
| `condition`, `gain`, `actual_gain` | Optional descriptive label and held true numerical gain |
| `reported_gain`, `channel_estimate` | Numerical RX payload, NaN without a fresh report |
| `looked_up_gain`, `reported_condition` | Deprecated CSV compatibility fields: numerical report alias and empty label; no lookup |
| `forecast_current_gain`, `forecast_next_gain`, `channel_forecast_anchor_t` | Causal raw forecasts and last reported observation time (-1 for prior) |
| `forecast_origin_t`, `forecast_target_t`, `forecast_channel_lead` | Scored forecast origin, target and gap from its observation anchor |
| `probe_executed`, `probe_available`, `exchange_available` | Executed probe, report availability (legacy field name), full control-stage availability |
| `d`, `attempted`, `attempted_ids`, `retry_numbers` | Whole attempted transmissions and retry indices; `d` remains an attempt alias |
| `received`, `received_ids` | Successful reception events, including repeat receptions |
| `ack_ids` | Feedback contents; repeated IDs are safe |
| `acknowledged`, `acknowledged_ids` | Unique outstanding IDs actually removed by feedback |
| `delivered`, `delivered_ids`, `cumulative_delivered` | Unique newly delivered payloads and cumulative total |
| `b`, `queue_ids`, `b_next`, `queue_next_ids` | Actual beginning/end queue counts and ordered IDs, including the final state |
| `arrival_ids`, `overflow_ids`, `proactive_ids`, `drop` | All offered arrivals and separately classified rejection IDs |
| `p`, `data_energy`, `control_energy`, `energy` | Data power, data energy, total control energy, and total TX battery expenditure |
| `probe_energy`, `channel_report_energy`, `ack_energy`, `other_control_energy` | Once-only stage charges and sum of report/ACK receive energy |
| `E`, `E_next`, `spill`, `harvest` | Beginning/end battery and end-slot energy inputs/spill |
| `throughput_bps` | Newly delivered unique payload bits divided by scheduling-interval seconds |
| `interval_start_s`, `interval_end_s`, `*_start_s`, `*_end_s`, `guard_seconds` | Reserved phase windows in seconds from simulation origin, including inactive slots |
| `channel_feedback_available_at_s`, `reception_completed_at_s`, `ack_processed_at_s` | Actual report, data reception and ACK events; NaN when their stage did not execute |
| `next_state_available_at_s`, `arrivals_available_at_s`, `harvest_available_at_s`, `history_available_at_s` | Next-interval availability, always the interval end |
| `control_seconds`, `data_seconds` | Actual executed control-stage duration and data-active duration (zero for A0), distinct from reserved windows |
| `solver_runtime_s`, `decision_runtime_s`, `decision_budget_s`, `*_budget_exceeded` | Measured host computation, configured budget and strict exceedance flags, separate from virtual time |

ID and retry columns are JSON arrays so CSV logs retain identities. Queue
departures use `acknowledged`, capacity checks use `attempted`, and delivered
throughput uses `delivered`. Realized cost includes total `energy`, and terminal
backlog uses `b_next` from the final row. Forced overflow occurs after reception
and new arrivals, so `b_next = b - acknowledged + arrivals - drop`.

Experiment settings include the full configuration, default 0.2 J probe cost,
success probability, feedback assumptions, reception indexing, and planning
relaxation, plus the uniform arrival probabilities/support/mean, forecast bounds,
attempted action range, and battery-versus-objective distinction. Per-slot
`slot_seconds` records the differing solar-source intervals.
Audits replay IDs, retries, reception outcomes, ACK departures, energy, overflow,
and final conservation. They reject results lacking the radio-model marker or
the current arrival/channel settings or `fixed-phases-v1` timing marker. They
independently check phase boundaries, feedback/ACK availability, next-interval
state availability and runtime flags. Aggregate audits independently recalculate
costs and terminal backlog and bind reception seeds, initial states and interval
lengths to settings. Non-finite plans are rejected. Settings record initial queue
12, initial energy 7 J, forecasting defaults, and per-source solar intervals
(60/60/3600 seconds) separately from the 5-second synthetic default.
Five-state saved settings are rejected by the new channel/radio model versions.
Audits independently reconstruct conditional forecasts from timed reports.

## Validation and pending experiments

Current continuous-channel verification and benchmark results are recorded in
[experiments_1000.md](experiments_1000.md). All saved production experiments still
require regeneration. The implementation-stage notes below are historical; their
five-state channel descriptions and old commands are superseded.

### Historical implementation-stage notes

The phase-timing implementation passed **68 tests in 23.553 seconds**, including
10 new focused timing tests. The full command below also exercised synthetic,
solar-fixture, proposal, offline-reference, solver, audit and figure entry points
in temporary directories. Tests verify the default boundaries, invalid phase
sums, event ordering, next-interval availability, A0 and starvation, constant
one-second data energy, source-specific guard times, causal history, deadline
flags (including forced overruns), CSV audits, all policies and both planners.
No production experiment outputs were regenerated.

Files changed for phase timing:

- Shared implementation: `src/scheduling.py`, `src/radio.py`, `src/experiment.py`,
  `src/auditing.py`.
- Policy/experiment consumers: `proposal_study.py`, `final_evaluation.py`,
  `final_solar_evaluation.py`, `tune_proposal.py`.
- Audit entry-point reports: `audit_final_evaluation.py`, `audit_comparison.py`,
  `audit_proposal.py`.
- Focused tests: `tests/test_phase_timing.py`.
- Documentation: `README.md`, `FINAL_HANDOFF.md`, `docs/receiver_feedback.md`.

Older saved settings/logs lack phased timing and the corrected solver-runtime
meaning. Regenerate them together with experiment tables, audits and figures
after the remaining model decisions are settled. The timing change itself does
not add energy costs or change stochastic traces, policies or planner dynamics.

Channel/probe stage changed files:

| Area | Files |
|---|---|
| Canonical mapping and shared implementation | `src/channel.py` (new), `src/radio.py`, `src/scheduling.py`, `src/forecasting.py`, `src/auditing.py` |
| Simulators and settings | `src/experiment.py`, `proposal_study.py`, `final_evaluation.py`, `final_solar_evaluation.py`, `tune_proposal.py` |
| References, reconstruction, figures | `offline_reference.py`, `audit_offline.py`, `audit_final_evaluation.py`, `audit_final_solar.py`, `plot_final_figures.py` |
| Tests | `tests/test_channel_probe.py` (new), `tests/test_arrival_actions.py`, `tests/test_final_evaluation.py`, `tests/test_packet_execution.py`, `tests/test_proposal_study.py`, `tests/test_receiver_feedback.py` |
| Documentation | `README.md`, `FINAL_HANDOFF.md`, `docs/receiver_feedback.md` |

The previous stages passed 42 tests. This stage passed **51 tests**, adding nine
condition/probe tests and adapting regression checks to the defaults, including every policy and both
planning backends. Checks cover condition-only payloads, TX lookup, held radio
state, channel/reception matching, A0 and A3 costs, probe starvation, partial
controls, ACK retries, CSV audits, and convex planning. Test-created audit fixtures
use temporary directories; saved project experiments are not regenerated.
All 28 project Python files also passed syntax parsing.

Run the existing environment (use a writable Matplotlib cache if needed):

```bash
MPLCONFIGDIR=/tmp/ee541-matplotlib .venv/bin/python -B -m unittest discover -s tests -v
```

During the superseded five-state stage, the continuous sweeps were disabled and
replaced by `synthetic/`. The current implementation restores `sweep/` and
`sweep_normalized/` with the packet/energy/timing improvements retained. Current
commands and parameter semantics are in the experiment protocol, not these notes.

After remaining model decisions are settled, regenerate the synthetic evaluation,
solar evaluation, solver comparison, offline expected-goodput reference, and all
associated tables, audits and figures. Earlier proposal/consistency/tuning studies
also require regeneration if used; tuning needs a regenerated matching proposal
reference. Historical saved CSVs, settings, logs and figures retain their old
meaning and have been left untouched.

The logical/mathematical audit subsequently passed **57 tests**, including small
CLI workflows for synthetic, artificial solar-format fixtures, offline reference,
solver comparison, proposal analysis and their audits/figures. Fixtures validate
interfaces and units handling; the three real solar inputs were absent at that
audit. They were subsequently downloaded and checksum-verified, and all 30
1,000-sample windows were validated. Short real-input action/delay checks are
recorded in [packet_delays.md](packet_delays.md#real-solar-input-verification-20-november-2026);
production results remain deferred. The audit also corrected solver-to-integer
precision loss, NaN plan verification, aggregate/seed/interval audit gaps,
row-order-dependent terminal analysis, and fixed sample-count figure labeling.

The subsequent uniform 0–10 arrival update passed **58 tests**, including integer
RNG reproducibility, matched synthetic/solar traffic, the mean-5 prior and [0,10]
forecast bounds, rejection of obsolete arrival settings, and overflow after
partial ACK departures with both zero and ten new packets. Actions, channel
mapping, packet size, probe cost and ACK-based departure rules remain unchanged.
