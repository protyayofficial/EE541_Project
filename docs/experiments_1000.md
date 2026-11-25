# Continuous-channel final experiment protocol: 1,000 slots

This protocol defines the full experiment matrix for the current continuous
channel, packet and radio simulator. The experiments compare policies on
matched inputs. For the results bundled with this repository, see the
[README](../README.md#included-results).

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

The implementation uses a dedicated, reproducible channel stream:
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

The launcher checks the three input hashes and selects 30 windows of 1,000
finite consecutive observations at each source's native interval.

| Real source | Loaded grid samples | Finite samples | Selected windows | Overlapping selected pairs |
|---|---:|---:|---:|---:|
| ARCO | 93,577 | 93,437 | 10 | 0 |
| UMass Home C | 135,360 | 129,172 | 10 | 0 |
| NREL TMY3 | 8,760 | 8,760 | 10 | 9 |

The NREL pairs share 1,240 samples summed across pairs, with a maximum pairwise
overlap of 138 samples (13.8% of a window). Their observations are shared, not
independent solar records. Even disjoint windows retain common source/season
dependence. No padding, tiling, interpolation or source-interval changes were used.

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

## Reproduction and outputs

Run the full design with `bash scripts/run_experiments.sh --run` from the
activated environment. The launcher validates the input hashes and all 30
solar windows before running the studies. It creates a fresh output directory
and audits each study. It writes run matrices, settings, per-run summaries,
slot and packet ledgers, paired comparisons and figures. The full design takes
several hours and produces millions of packet rows. See the
[README](../README.md#reproduce-the-experiments) for the short verification run
and output directory conventions.
