# Continuous-channel final experiment protocol: 1,000 slots

The current implementation restores the correlated continuous channel within the
latest packet/radio simulator. Historical production results remain untouched.
The full current production completed on 20 November 2026 at 11:09:39 UTC in
`results/final_evaluation_continuous_1000_20261120T075329Z_4_f31b28/`, with all
900 main and 240 supplementary runs, 90 references, 12 solver checks and final
completion audit verified. See the
[completion record](../results/recovery_20261120/completion_verification.json).
Prelaunch verification/command notes below describe the protocol's preparation.
The intermediate five-state model and its 400-run design are superseded.

## Channel definition, provenance and forecasts

For every interval, `x_next = rho*x_previous + Normal(0,sigma)` and the positive
finite gain is held throughout that interval's probe/data burst. `rho=0.68`,
`sigma` is 0.20, 0.45 or 0.80, and `v=sigma^2/(1-rho^2)`.

- Original: initialize latent log-state `x[-1]=0`; use `gain=exp(x_next)`.
- Normalized: initialize `x[-1]~Normal(0,sqrt(v))`; use `gain=exp(x_next-v/2)`.
  The theoretical stationary mean is one. Never divide by the episode's realized
  mean, clip gains into [0.2,1.0], or quantize the gain into conditions.

Gains are effective SNR per watt (1/W), not measured RSSI. Numerical underflow,
overflow, zero, negative and nonfinite actual gains raise explicit errors.
`channel_model.version=correlated-lognormal-v1` and
`radio_model=gain-probe-ack-v3` distinguish new outputs. Settings include rho,
sigma, normalization, log variance, initialization, units and random stream;
synthetic per-run `channel_sigma` and `scenario_channel_models` specialize the
base configuration template.

Historical `results/final_evaluation/sweep/settings.json` and
`sweep_normalized/settings.json` confirm three sigmas, harvest means 0.6/1.2,
and seed ranges 5000–5009 / 6000–6009. The `.git` directory is empty, so no old
source or exact historical RNG draw ordering is recoverable. The latest explicit
independent channel stream is retained:
`default_rng(SeedSequence([scenario_seed,42017]))`. Its normalized variant first
draws the stationary initialization, then one innovation per interval. Arrival
and harvest RNG construction is unchanged; varying sigma/normalization does not
alter their matched traces. Exact historical channel samples are not claimed.

RX returns an ideal accurate numerical gain only after feedback at 0.6 s. TX
never reads the hidden environment gain or true future gains. If probing/report
is unaffordable there is no fresh report; the last report's value/time, not the
hidden current gain, anchors forecasts. With report `g` at time `s`, define
`c=0` (original) or `v/2` (normalized). Then at lead `k=t-s`:

```
E[gain[t] | gain[s]=g] = exp(rho^k*(log(g)+c)
                            + 0.5*v*(1-rho^(2*k)) - c)
```

This follows from a Gaussian conditional log-state with mean
`rho^k*(log(g)+c)` and variance `v*(1-rho^(2*k))`. Lead zero returns `g` exactly.
Without any observations the normalized prior mean is one; the original prior
at interval t has log variance `v*(1-rho^(2*(t+1)))` from its initial zero state.
Report histories include actual interval indices, so missed probes increase the
lead instead of treating separated reports as adjacent observations.

Forecast logs record current/next predictions, observation anchor, forecast
origin/target and actual lead of the scored prediction. Every target prediction
is retained, even after an inactive decision. Channel residuals/coverage are NaN
without a fresh report. Quantiles use the latest finite scores for each component
(50 scores/12 warmup in proposal, 40/8 in the older simulator); scores are pooled
across observed leads, not a lead-specific coverage guarantee. Arrival/harvest
forecast rules and their support bounds remain unchanged. Future uncertainty
margins and nominal future planning inputs use only a numerical floor 1e-9, with no upper bound; the observed current
gain is never modified. Forecast gains are fixed inputs, preserving DCP.

The channel baseline keeps the latest numerical rule: 2.4 W for reported gain
>=0.8 and 0.45 W below 0.8, battery/power clipped. Fixed power remains 1.2 W and
fixed-fraction retains its existing formula. No threshold is tuned to results.
Optional condition labels are descriptive only. `reported_gain` is the payload;
`actual_gain` is the environment value. Legacy `looked_up_gain` remains a numeric
report alias and `reported_condition` is empty; no lookup occurs.

## Preserved packet, energy and timing system

Payload stays 32 bytes/256 bits; IDs are metadata. Arrivals are IID integer
uniform 0–10, mean five, with no load sweep. Attempts remain whole actions 0–5.
ACK IDs alone remove outstanding packets, failures keep retry priority, and RX
deduplicates unique delivery. Independent BER 9.89e-6 gives success
`(1-BER)^256`. Buffer 32, initial queue 12, initial energy 7 J, battery 12 J,
power cap 3 W, bandwidth 3000 Hz, objective weights 35/0.15/6 and online MPC
horizon 10 are preserved. Planning remains continuous expected goodput followed
by whole-packet execution. Energy weight never scales physical battery debit.

Each executed probe costs 0.2 J including A0. Report/ACK energy defaults to zero;
decision/update/idle hardware energy remains abstracted as zero. Data uses the
one-second Shannon burst and charges all attempts including failures. Harvest
cannot fund earlier actions. Arrivals/harvest/history commit at interval end.
Synthetic phase windows remain 0–0.3 probe, 0.3–0.6 report, 0.6–1.6 decision,
1.6–2.6 data, 2.6–3.6 ACK, 3.6–4.6 update preparation, 4.6–5 guard. A0/inactive
slots advance fully without sleeping. Runtime overruns remain logged, not used
to alter actions. Solar retains its native source interval and longer guard.

## Final matrices

| Group | Scenario definition | Policy-runs |
|---|---|---:|
| `sweep` | 2 harvest means × 3 sigmas × seeds 5000–5009 × 5 policies | 300 |
| `sweep_normalized` | 2 harvest means × 3 sigmas × seeds 6000–6009 × 5 policies | 300 |
| `solar` | 3 sources × 10 windows/seeds 7000–7009 × 10 policies | 300 |
| Online total | 900 episodes × 1,000 intervals | **900** |

The two separately prepared [supplementary studies](supplementary_studies.md)
contain 120 executions each. Their baseline cases overlap the main normalized
sweep and each other. They do not change this main matrix or add independent
seed repetitions. Adaptive penalty-weight updates are excluded. Offline and
solver matrices remain 90 and 12 respectively.

The five synthetic policies remain `greedy`, `nominal`, `fixed_margin`,
`adaptive_harvest`, `adaptive_all`; harvest means stay 0.6 and 1.2 J. Solar uses
`fixed`, `channel`, `greedy`, `nominal`, `fixed_margin`, `adaptive_harvest`,
`adaptive_all`, `fixed_fraction`, `adaptive_channel`, `adaptive_arrival`.
Its fixed channel default is rho 0.68, sigma 0.45, stationary mean-normalized;
there is no solar volatility or traffic-load sweep.

The original sweep's stationary mean `exp(v/2)` changes with sigma. The normalized
sweep fixes that mean and is the cleaner volatility comparison, although variance,
higher moments and predictability still change. Neither is a controlled change
in forecast error alone. Each scenario resets queue/battery/receiver/retries and
forecast history per policy, with matched exogenous traces and policy-independent
packet/retry reception randomness. Explicit short CLI overrides remain supported.

The offline reference uses only **60 normalized synthetic + 30 solar scenarios =
90 full-episode problems**, with 600 matched online comparisons. It shares online
seeds, sigmas, normalization, source hashes, exact windows and episode lengths.
Online horizon remains 10; offline horizon is the full 1,000. The reference stays
continuous deterministic expected goodput with perfect future inputs, proactive
rejection and relaxed future controls. It is neither the expected stochastic
online objective nor a pathwise lower bound on realized costs. Six short instances
× two solvers remain 12 separate solver checks.

## Solar inputs and selection

Use the real files and documented downloads in [ARCO](../data/arco/README.md),
[UMass](../data/umass/README.md) and [NREL](../data/nrel/README.md). Settings store
the actual SHA-256, recorded historical reference checksum and whether they
match. Audits/offline reconstruction require the original online input hashes
and exact regenerated window manifest. A different checksum must be investigated
as a different input version; recording a hash is not proof of data provenance.

At implementation time all three raw files were absent and download attempts
failed with DNS resolution errors. This dependency was resolved on 20 November
2026: all three downloaded files match their recorded reference SHA-256 checksums.
The saved `--validate-only` settings and 300-run matrix in
[`results/solar_input_check_1000/`](../results/solar_input_check_1000/settings.json)
were reconstructed successfully against the actual files. All 30 selected windows
contain exactly 1,000 finite consecutive samples at their native interval.
The user's settings/matrix were preserved; independent checksum, matrix and
overlap checks are saved in
[`input_verification.json`](../results/solar_input_check_1000/input_verification.json).

| Real source | Loaded grid samples | Finite samples | Selected windows | Overlapping selected pairs |
|---|---:|---:|---:|---:|
| ARCO | 93,577 | 93,437 | 10 | 0 |
| UMass Home C | 135,360 | 129,172 | 10 | 0 |
| NREL TMY3 | 8,760 | 8,760 | 10 | 9 |

The NREL pairs share 1,240 samples summed across pairs, with a maximum pairwise
overlap of 138 samples (13.8% of a window). Their observations are shared, not
independent solar records. Even disjoint windows retain common source/season
dependence. No padding, tiling, interpolation or source-interval changes were used.

The action/delay verification also passed short real-input workflows at horizon
10: 60 final-policy runs and 21 older-simulator runs, each 12 slots. These smoke
outputs and audits are in
[`results/solar_packet_delay_smoke_real/`](../results/solar_packet_delay_smoke_real/verification.json).
They verify execution and accounting, not production performance. The complete
suite passed 94 tests in 50.470 seconds. The input prerequisite is resolved;
production remains deferred for the final system/model review. Artificial fixtures
remain test-only inputs; these real-data checks do not change the study design.

ARCO and UMass retain **60-second samples** and conversion factors 0.01 and 0.1
J per current-unit sample respectively. UMass sums all three nonnegative solar
panel currents only when all three readings exist. Daily files are assembled by
UTC timestamp, with sum/count weighted minute averages across file boundaries.
ARCO uses its original local timestamps and minute averaging. Missing minutes or
invalid readings remain missing; measured nighttime zeros remain valid zeros.
No short trace is repeated, padded, interpolated or compressed in time.

NREL retains **3,600-second samples** and factor 0.005 J per irradiance-unit
sample. Its source years are stitched by month; hourly order is validated on a
non-leap TMY calendar template, including hour-ending `24:00`. Missing hours
remain NaN, not a shift that makes nonconsecutive observations appear adjacent.
The template does not assert chronological measurements across source years.
Artificial minimal fixtures may explicitly supply row-ordered hourly values.

For each source `select_windows`:

1. Enumerates starts with exactly the requested count of finite consecutive
   source samples and checks the native timestamp/position spacing.
2. Builds the maximum disjoint set using earliest-finish selection. If it has
   at least ten windows, chooses ten evenly spaced ranks from that set.
3. Otherwise chooses ten evenly spaced ranks from all valid starts, permitting
   overlap. Fewer than ten distinct valid starts is an error before any policy
   executes. The selector never wraps at the file end.

`settings.json:window_manifest` records window IDs, scenario indices/seeds,
source positions (exclusive ends), timestamps for minute data, lengths, source
interval, selection rule, valid-sample/start counts and all 45 pairwise overlap
counts/fractions per source. `run_matrix.csv` maps these windows to policies.
The same deterministic rule and manifest are used by source audits and offline
reconstruction. Earlier-study overlap is disclosed by the source audit rather
than forbidden; no claim of an untouched holdout study is made.

For a **complete, finite 8,760-hour NREL grid**, the ten starts are
`0, 862, 1724, 2586, 3448, 4311, 5173, 6035, 6897, 7760`. Eight disjoint
1,000-hour windows fit, so overlap is necessary. Nine of the 45 pairs overlap,
by 137 or 138 samples each (13.7% or 13.8%); the sum of pairwise shared counts is
1,240. This rule is tested on an artificial full-length grid; actual NREL and
the other sources still require input validation and may have different valid
ranges if measurements are missing.

Within-scenario policy differences remain paired. Across scenarios, shared
solar observations and common sites/seasons limit independence. Existing t
interval formulas are retained and labeled **approximate/descriptive**, with
`n` equal to scenarios, never 1,000 independent slot repetitions. These are not
confidence guarantees or comparisons across independent solar records.

## Outputs, verification and measured runtime

Per-slot and per-run tables retain their packet/energy meanings. Synthetic keys
include harvest mean, channel sigma, seed and policy, so sigma scenarios cannot
collide. Both sweep drivers and solar save run matrices/settings; slot checkpoints
append each completed run once and final CSV is copied once. Existing trajectory
outputs are rejected in favor of a fresh output root. No production results were
overwritten. Audits reconstruct channel traces, timed conditional forecasts,
packet/retry outcomes, ACK queue changes, energy, phase times and aggregate costs.
Offline audits also bind comparison costs to the matching online rows.

The A5/delay-tracking benchmark uses stationary-normalized sigma 0.45,
seed 6000, harvest mean 0.6 J, 1,000 slots and online horizon 10. Policy execution
took **13.4600 s**; 994 solver calls averaged **13.1270 ms**. Six intervals had no
solve. All accepted results were optimal, with maximum primal residual
3.66235e-5 (<1e-4), and no decision-budget overruns. An intermediate solver
issued an inaccuracy warning; the existing fallback/verification rules remained
in place. Packet, battery, aggregate and delay-ledger audits passed. Primary
completed-observation means were 20.5541 s initial wait and 22.5667 s ACK delay,
each over 4,360 newly admitted packets; nine new admissions remained unfinished.
These are benchmark diagnostics, not regenerated study results.

The prior A3 offline timing is historical; this stage refreshes only the requested
online benchmark. Offline bounds now derive from Config.data_max=5, retaining
90 full-episode references and the expected-goodput interpretation. Short offline
reconstruction/audit tests pass; no full reference study was launched.

There are 660 MPC policy-runs plus 240 heuristic runs. The measured episode rate
extrapolates to about **2.47 hours for MPC execution alone**, before baseline,
packet/slot CSV, source loading, audits and plotting costs. This is not a measured
900-run runtime. Plan additional time, particularly for the approximately 4.5
million offered-packet ledger rows. See [packet_delays.md](packet_delays.md) for
current cohorts, schemas and verification. The existing paired CI formulas remain
run-level; individual packets are not independent experimental repetitions.

## Fresh-output commands (not executed as a production study)

From the project root (real inputs and all 30 windows are already verified):

```bash
export MPLCONFIGDIR=/tmp/ee541-matplotlib
EE541_OUT=results/final_evaluation_continuous_1000

# Validate real windows only, no policy runs.
.venv/bin/python -B final_solar_evaluation.py --validate-only --windows 10 --slots 1000 --horizon 10 --out "$EE541_OUT/solar"

# Original, zero-initialized channel: 300 runs.
.venv/bin/python -B final_evaluation.py --seeds 10 --seed-start 5000 --rho 0.68 --sigma 0.20 0.45 0.80 --slots 1000 --horizon 10 --out "$EE541_OUT/sweep"
.venv/bin/python -B audit_final_evaluation.py "$EE541_OUT/sweep"

# Stationary mean-normalized channel: 300 runs.
.venv/bin/python -B final_evaluation.py --mean-normalize --seeds 10 --seed-start 6000 --rho 0.68 --sigma 0.20 0.45 0.80 --slots 1000 --horizon 10 --out "$EE541_OUT/sweep_normalized"
.venv/bin/python -B audit_final_evaluation.py "$EE541_OUT/sweep_normalized"

# Solar: 300 runs, fixed normalized sigma 0.45.
.venv/bin/python -B final_solar_evaluation.py --windows 10 --slots 1000 --horizon 10 --out "$EE541_OUT/solar"
.venv/bin/python -B audit_comparison.py "$EE541_OUT/solar"
.venv/bin/python -B audit_final_solar.py "$EE541_OUT/solar"

.venv/bin/python -B solver_crosscheck.py --out "$EE541_OUT/solver"
.venv/bin/python -B offline_reference.py --root "$EE541_OUT"
.venv/bin/python -B audit_offline.py "$EE541_OUT/offline"
.venv/bin/python -B plot_final_figures.py --root "$EE541_OUT"
```

Validation-only output can be used for its subsequent full solar run. Once
trajectories exist, use a new root for reruns. The complete test command is:

```bash
MPLCONFIGDIR=/tmp/ee541-matplotlib .venv/bin/python -B -m unittest discover -s tests -v
```

The continuous-channel stage passed **80 tests in 50.780 seconds** before the
A5/delay additions. Current verification is recorded in [packet_delays.md](packet_delays.md). All 31 project/test
Python files passed syntax parsing. Temporary CLI smoke runs covered both
synthetic variants (60 three-slot policy-runs each), ten-policy solar (60
three-slot runs), all physical/source audits, 18 short offline references,
12 solver checks, proposal analysis and plots. Validation-only mode, corrupt
run matrices/manifests, conditional forecasts, missed probes, overflow, battery,
packet IDs/retries and policy execution-order independence were checked. These
fixtures never substitute for production data or validate real solar windows.

Changed implementation files: `src/channel.py`, `src/forecasting.py`,
`src/radio.py`, `src/scheduling.py`, `src/experiment.py`, `src/auditing.py`,
`proposal_study.py`, `final_evaluation.py`, `audit_final_evaluation.py`,
`offline_reference.py`, `audit_offline.py`, `plot_final_figures.py`,
`solver_crosscheck.py`, `tune_proposal.py`. Existing solar drivers/loaders use the
new common channel defaults without changing selection or source accounting.
Changed tests: `test_channel_probe.py`, `test_receiver_feedback.py`,
`test_phase_timing.py`, `test_audit_workflow.py`, `test_final_evaluation.py`.
Documentation: `README.md`, `FINAL_HANDOFF.md`, `docs/receiver_feedback.md` and
this protocol. The current files were edited directly; old source files were
not restored wholesale and production results were not changed.

Final benchmark artifacts are in `/tmp/ee541_continuous_final_benchmark_w3q3g1vn/`
(`benchmark.json`, `online_slots.csv`, `offline_plan.csv`). The complete test log
is `/tmp/ee541_continuous_tests.log`. No production output root was created.
