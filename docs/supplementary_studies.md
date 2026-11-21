# Fixed supplementary protocols and final readiness

These protocols add sensitivity measurements to the completed packet simulator.
Adaptive **penalty-weight updates are excluded**. Existing adaptive forecast
margins remain. The fixed grids below must not be retuned to improve a ranking.
Flat or unfavorable outcomes are valid study outcomes. Neither full study has
been executed during implementation; both were subsequently completed in the
audited production ending 20 November 2026 at 11:09:39 UTC. The
[completion record](../results/recovery_20261120/completion_verification.json)
confirms 120 executions per study. Earlier preflight descriptions below retain
their historical meaning. No further production launch is pending.

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

## Commands (full studies not launched)

Run from the project root. Main, offline, solver and main-figure commands remain
in the [main protocol](experiments_1000.md#fresh-output-commands-not-executed-as-a-production-study).
All three real solar inputs and all 30 native windows are already validated;
the original records are in `results/solar_input_check_1000/`. No data dependency
remains missing. The main source conversions, overlap qualifications and solar
policy matrix are unchanged.

```bash
export MPLCONFIGDIR=/tmp/ee541-matplotlib
EE541_OUT=results/final_evaluation_continuous_1000

# Plans only: 120 runs each, no policy execution.
.venv/bin/python -B supplementary_studies.py delay_energy --plan-only --out "$EE541_OUT/supplementary/delay_energy"
.venv/bin/python -B supplementary_studies.py forecast_sensitivity --plan-only --out "$EE541_OUT/supplementary/forecast_sensitivity"

# Full studies, only when production is authorized. Drivers also analyze/plot.
.venv/bin/python -B supplementary_studies.py delay_energy --out "$EE541_OUT/supplementary/delay_energy"
.venv/bin/python -B supplementary_studies.py forecast_sensitivity --out "$EE541_OUT/supplementary/forecast_sensitivity"

# Rebuild analysis/plots and audit each output directory.
.venv/bin/python -B analyze_supplementary.py "$EE541_OUT/supplementary/delay_energy"
.venv/bin/python -B audit_supplementary.py "$EE541_OUT/supplementary/delay_energy"
.venv/bin/python -B analyze_supplementary.py "$EE541_OUT/supplementary/forecast_sensitivity"
.venv/bin/python -B audit_supplementary.py "$EE541_OUT/supplementary/forecast_sensitivity"
```

For short smoke runs use `--seeds 2 --slots 4 --horizon 3 --out <fresh-temp-dir>`.
`--benchmark-case --out <fresh-benchmark-dir>` selects exactly one nominal,
seed-6000, harvest-0.6 case at weight 15 or amplitude 0.25; default episode length
and horizon stay 1,000/10. It cannot silently use the production default folder.

## Verification, benchmarks and readiness (20 November 2026)

The final complete suite passed **101 tests in 73.673 seconds**. All **39 Python files**
passed syntax parsing. Seven focused supplementary tests passed, including exact
zero-noise/default equivalence for both policies, matched traces/normal keys,
missed probes, future-truth causality, mature adaptive scoring, constant weights,
common-reference scoring, missing delay cohorts and corruption rejection.

Temporary CLI workflows executed **24 four-slot runs per study** with two seeds
and horizon three, through plan-only generation, execution, analysis, independent
audits and figures. The full 120-row plans were separately checked without
execution. These small studies establish interface/accounting correctness, not
performance findings. Persistent full plans are under
`results/supplementary_verification/plans/`.

Exactly one 1,000-slot nominal case per study was benchmarked, both with horizon
10, seed 6000 and mean harvest 0.6 J:

| Benchmark | Setting | Policy execution | Mean optimization call | Calls | Command including startup/analysis/plots |
|---|---|---:|---:|---:|---:|
| Delay–energy | weight 15 | 13.1787 s | 12.7430 ms | 994 | 24.6427 s |
| Channel-forecast sensitivity | amplitude 0.25 | 13.0524 s | 12.7013 ms | 987 | 24.3576 s |

Both independent audits passed, with no solver/decision budget overruns and
maximum recorded planning residuals 5.53208e-5 / 6.62825e-7. Existing solver
fallback/verification handles intermediate numerical-accuracy warnings. The
benchmarks were collected during implementation verification on the current
host; they are runtime diagnostics, not supplementary experimental findings.
Audit command time is additional to the command timings in the table.

Extrapolating policy-execution measurements gives approximately **26.36 minutes**
for delay–energy and **26.10 minutes** for forecast sensitivity, **52.46 minutes**
combined. These extrapolate nominal runs to adaptive runs and other settings;
actual solver behavior and I/O may differ. The earlier main benchmark implies
about 2.47 hours for its 660 MPC executions. Together these imply about **3.34
hours of MPC execution**, before 240 heuristic runs, CSV output, analysis, audits,
the 90 offline references and 12 short solver checks. This is not a measured
full-study runtime. Single-case startup/plot overhead should not be multiplied
as though every run launches a new process. Current full-episode offline timing
was not refreshed in this task.

The original 1,000-slot main benchmark and 60-run real-solar smoke outputs were
re-audited read-only using the updated code. All three input checksums and the
30 real solar windows reconstructed successfully again. The main 300/300/300
matrix, 90 references and source intervals/conversions remain unchanged.
No missing-data or implementation blocker was found under the documented model.
Adaptive penalty updates are excluded; no further adaptive-penalty implementation
is pending. Final authorization to execute production remains separate.

Evidence is under [`results/supplementary_verification/`](../results/supplementary_verification/readiness.json):
`readiness.json`, `tests.log`, `focused_tests.log`, `benchmarks.json`, full plans,
and each benchmark's settings, slot/packet/run tables, forecast metrics, figures
and `audit.json`. Default production output remains absent. No full main,
supplementary or offline study was launched and historical results were preserved.

Changed files: new `src/forecast_noise.py`, `supplementary_studies.py`,
`analyze_supplementary.py`, `audit_supplementary.py` and
`tests/test_supplementary.py`; small opt-in changes in `proposal_study.py` and
`src/auditing.py`; documentation in `README.md`, `FINAL_HANDOFF.md`,
`docs/experiments_1000.md`, `docs/packet_delays.md` and this protocol.

