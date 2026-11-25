# Fixed supplementary protocols and final readiness

The supplementary studies vary the energy penalty and channel forecast
noise on fixed grids. Both compare nominal MPC and MPC with adaptive forecast
margins. The penalty weights are fixed within each run.

## Design and overlap

Both studies use stationary mean-normalized lognormal channels, rho 0.68 and
sigma 0.45; harvest means 0.6/1.2 J; seeds 6000–6009; policies `nominal` and
`adaptive_all`; 1,000 slots; online horizon 10. All other physical parameters,
initial conditions, uniform 0–10 arrivals and packet/ACK/retry rules are unchanged.
The existing generator supplies matched actual traces. There is no load sweep.

| Study | Fixed settings | Executions |
|---|---|---:|
| `delay_energy` | energy weights 0.15, 15.0, 150.0 | 2 × 10 × 2 × 3 = 120 |
| `forecast_sensitivity` | future-channel noise amplitudes 0, 0.25, 0.50; energy weight 0.15 | 2 × 10 × 2 × 3 = 120 |

Each full study repeats 40 baseline cases already present in the main normalized
sigma-0.45 sweep. These same 40 cases also overlap between the supplementary
studies. The 240 executions are not 240 additional independent repetitions.
There are still ten paired scenario seeds per harvest/setting, not one repetition
per packet or slot. The main matrix stays 900 online executions; including both
supplements gives 1,140 executions with the stated baseline repetition. Offline
work stays 90 expected-goodput references and 12 short solver checks. There are
no supplementary offline matrices and no offline packet-delay samples.

## Channel-forecast sensitivity only

The controller first computes its existing causal conditional channel forecast
from numerical probe reports and their observation times. At decision origin
`t`, for each future decision lead `k>=1`, use

```
g_perturbed[t,k] = g_base[t,k] * exp(a*z[t,k] - 0.5*a*a)
```

The expected multiplier is one. Current input `k=0` is unchanged, including an
exact observed probe report when available. Perturbation occurs before adaptive
margins and the existing positive future planning floor. The post-margin/floor
forecast need not have the same expectation as the base forecast. The optimizer
still receives fixed forecast coefficients, preserving convexity.

`z[t,k]` is a stateless separate pseudorandom stream: BLAKE2b-128 hashes the JSON
tuple `["channel-forecast-lognormal-v1", scenario, t, k]`. The scenario string is
`normalized:harvest=<mean>:seed=<seed>`. Two 53-bit midpoint-uniform variates from
the digest feed the cosine Box–Muller transform. Policy, amplitude and probe
count are absent from the key. Matching origins/leads reuse the same normal
across policies and amplitudes. Missed probes never shift draws. No existing
traffic, harvest, channel or packet/retry reception RNG is consumed.

Forecasts are issued virtually at channel-feedback end / decision start (0.6 s
within a synthetic interval). Logged origins, targets and leads identify every
vector element. After a missed probe the unchanged base predictor accounts for
the actual elapsed observation gap. A fresh report is never replaced with hidden
truth. The perturbed lead-one base prediction is scored against the next observed
report and enters adaptive error history only after that target interval finishes;
missing reports leave channel scores missing. Arrival/harvest forecasts and their
error methods are unchanged.

Amplitude zero preserves existing decisions, reception outcomes and packet
timestamps exactly, apart from added output fields and host runtimes. The default
main-study call does not activate the hook or add forecast-noise fields. Actual
future channel values are consulted only after execution for evaluation. This
study varies channel-forecast perturbation, not arrival/harvest error or probe
quality. It is not a general correlated forecast-error model or a guarantee that
realized MAE increases monotonically with amplitude.

## Costs, delays and analysis

The configured realized objective is
`sum(b_begin) + 35*sum(overflow) + w_E*sum(total_TX_energy) + 6*b_terminal`.
Each `w_E` remains constant throughout its run. Physical battery consumption
always subtracts full attempted-data and executed-control energy before harvest;
the objective weight never scales battery deductions.

`configured_objective_cost` (also retained as `realized_cost`) uses that run's
weight. `common_reference_cost` always uses `w_E=0.15`, drop weight 35 and
terminal weight 6. Cross-setting comparisons use the common cost; objectives
with different weights are different scoring functions. Policy comparisons
within one weight may also compare their configured objective. Cross-setting
paired tables deliberately omit configured-objective differences.

The existing [delay definitions](packet_delays.md) apply: admission-to-first
burst start and admission-to-first ACK completion are separate metrics. Initial
packets are excluded from primary statistics; rejected packets are not admitted;
unfinished delays remain missing with outstanding ages and cohort counts.
Completed-observation means/medians are conditional on their completed cohorts,
not unconditional population delays. Run summaries retain admissions, attempted,
ACK-completed and unfinished counts, plus `newly_completed_fraction` and
`newly_unfinished_fraction`. Zero-admission fractions are missing.

`delay_energy.png` plots mean run initial waiting/ACK delay against mean run total
energy and labels the fixed settings. Its third row shows unfinished-admission
fractions and completed/admitted totals. These totals describe censoring, not
extra statistical repetitions. Missing completed-delay points remain missing.

`forecast_errors.csv` reports per-run MAE/RMSE and sample counts for **each future
lead from decision origin**, separately for base, perturbed and post-margin
planned forecasts. The evaluation uses post-run actual gains for all targets,
including targets with no affordable probe. This differs from the existing
`forecast_mae_gain` based on scored reports only. `future_channel_*_lead1` adds
all-target lead-one MAE/RMSE/counts to the per-run table. Observation-anchor gaps
and the existing observed-score leads remain explicitly logged. The forecast
plot uses means of run RMSEs; it does not pool all slots as independent samples.

Summaries use run-level mean/std/count. `paired_vs_nominal.csv` compares policies
within each setting; `paired_vs_baseline.csv` compares settings within each
policy, both paired by seed and harvest regime. Missing delay estimates are
excluded pairwise with `n_valid_pairs`; no eligible pairs gives missing estimates,
and one pair gives a missing CI. Paired t intervals are descriptive; multiple
metrics/settings are not a predeclared familywise significance test.

## Outputs and audits

`supplementary_studies.py` provides the two drivers through its study argument.
Each directory contains settings, run matrix, `per_seed.csv`, `per_slot.csv`,
`per_packet.csv`, `forecast_errors.csv`, summary/paired tables and figures.
Complete run identities include study, setting, energy weight, noise amplitude,
scenario, seed, policy, channel/configuration digest, horizon and episode length.
Finished-run rows append once; the slot checkpoint is copied once at completion.
Existing trajectory output is never reused. A matching plan-only directory may
be used for execution. Analysis/plot commands rebuild derived files only.

`audit_supplementary.py` independently reconstructs the full grid, actual traces,
causal base forecasts, keyed normals/multipliers, unchanged current reports,
arrival/harvest forecasts, adaptive histories/margins and phase timing. It also
checks costs, every forecast lead's evaluation, packet/battery/delay conservation,
run-identity binding, missing-aware summaries and valid paired counts. It does
not certify online optimality or formal uncertainty coverage.

## Reproduce the studies

Both studies are included in the [main launcher](../README.md#reproduce-the-experiments).
To run either individually, choose a fresh output directory:

```bash
python supplementary_studies.py delay_energy --out runs/delay_energy
python audit_supplementary.py runs/delay_energy
python supplementary_studies.py forecast_sensitivity --out runs/forecast_sensitivity
python audit_supplementary.py runs/forecast_sensitivity
```
