# Table and measurement notes

`experiment_structure.csv` checks the saved execution matrices: 300 original,
300 normalized, 300 solar, 120 weight-sensitivity and 120 forecast-sensitivity
online runs, plus 90 full-episode relaxed references and 12 short solver checks.
Online episodes contain 1000 intervals, MPC horizon 10. Seed sets are
5000–5009 (original), 6000–6009 (normalized/supplementary), and 7000–7009 (solar).
Supplementary baseline cases repeat main/between-study scenarios; these are
not extra independent repetitions. Each table retains its study/condition/run
identifiers; packet IDs are not pooled across runs.

## Units and cohorts

- `queue` is mean beginning-of-slot backlog in packets.
- `energy` is total TX data-plus-control J per 1000-slot episode; means are across
  episodes. `throughput` is uniquely delivered payload bits/s: 256 times unique
  deliveries divided by episode duration. Synthetic intervals last 5 s; solar
  ARCO/UMass/NREL intervals last 60/60/3600 s. Compare physical delay/throughput
  within the same source. These are virtual times, not host wall-clock time.
- Initial waiting = first burst's data-start time minus admission time. ACK delay
  = first successful ACK-availability/departure time minus admission time. It
  includes transmission, ACK waiting and retries. Packets in a burst share its
  start timestamp; first-attempt timestamps survive retries. Boundary admissions
  become eligible in the following interval. For a 5 s boundary admission,
  first attempt at 6.6 s gives 1.6 s waiting, ACK at 8.6 s gives 3.6 s delay;
  retry ACK at 13.6 s gives 8.6 s delay without changing initial waiting.
- Primary delay cohorts exclude the 12 initial packets per run (bookkeeping
  admission at simulation time zero). Rejected arrivals were never admitted.
  Outstanding packets have no fabricated ACK times; never-attempted packets
  have no completed initial-wait sample. Missing observations remain missing.
- `delay_cohorts.csv` retains all 1140 run-level cohort records and outstanding
  age summaries. `delay_service_summary.csv` puts admissions, attempts,
  completions, unfinished and rejection counts alongside run-averaged delay,
  rejection, throughput, energy and queue. Count totals sum run records; they
  are not a count of independent experimental repetitions or distinct packets
  across repeated matched policies. `median_*_run_mean` averages per-run medians;
  it is not the median of a pooled packet population.
- Rejection = rejected/offered arrivals. Unfinished admitted fraction =
  (new admissions − new ACK completions)/new admissions. Offered completion =
  new ACK completions/offered arrivals. `_pct` columns use 0–100 scaling;
  raw `_fraction`/`drop_ratio` columns use 0–1. Plotted-data `scale` records any
  conversion; paired percentage differences are percentage points. Initial
  outstanding packets are included in `outstanding_packets` but excluded from
  `newly_outstanding_packets` and primary unfinished fractions.

## Statistics and scores

All primary means/contrasts use run-level observations. Within each synthetic
condition, matched seed differences use unadjusted 95% Student t intervals:
mean(d) ± t(0.975,n−1) sd(d)/sqrt(n). `n_valid_pairs` counts finite paired run
observations for that metric; missing delay observations are not filled with
zero. Absolute mean intervals use seed-level observations. Coverage averages
all six normalized conditions within each seed before its ten-seed interval.
Solar intervals are descriptive paired-scenario intervals with shared-source
dependence, including nine overlapping NREL pairs; they are not independent
solar-record confidence intervals. No slots or packets are used as independent
replicates. No multiplicity correction or population normality guarantee is made.

`performance_paired.csv` retains all conditions and comparisons against greedy,
nominal and (where present) fixed-margin. Supplementary greedy comparisons reuse
the exactly matched normalized-main greedy reference and are explicitly labeled;
greedy was not executed again in those supplementary matrices.
`energy_weight_comparisons.csv` and `forecast_noise_baseline_comparisons.csv` pair each setting
with its own policy's predeclared baseline. Estimates/intervals/counts for every
figure are independently recomputed from the saved rows, not from rounded labels.

`common_score` aliases saved `common_reference_cost` in supplementary tables
and saved `realized_cost` in the main study (whose weights are fixed).
Common-reference score = 1000 × mean backlog + 35 × rejected arrivals +
0.15 × total TX energy + 6 × terminal backlog. It is a weighted score, not J.
`configured_and_common_scores.csv` keeps configured objectives separate: their
energy coefficients differ, so configured objectives at different weights are
not compared as the same scoring function. Trade-off coordinates are empirical,
not a certified Pareto frontier. Lower completed-only delay requires the cohort,
rejection and throughput context before making an overall-service comparison.

Forecast tables distinguish `base`, `perturbed` (pre-margin), and `planned`
(margin-adjusted) errors. Only perturbed pre-margin RMSE is drawn in the revised
forecast-error panels, in effective SNR per watt (1/W). Each run's MAE/RMSE is
scored against saved post-run truth at the labeled decision lead, then averaged
over seeds; it is not pooled across different forecast quantities. Noise changes
future channel forecasts only. Zero added noise still has process error; current
probe reports remain ideal. Arrival/harvest errors were not independently varied.
The dimensionless amplitude a multiplies future forecasts by exp(a z − a²/2).
The independent standard-normal stream is keyed by scenario seed, decision
origin and lead; policies and amplitude levels share those underlying draws.

## Solver and offline evidence

`solver_runtime_by_run.csv` and `solver_runtime_summary.csv` distinguish host
solver runtime per interval from runtime per actual optimization call. Inactive
intervals/baselines have no optimization call. Runtime/status metadata were
streamed now from saved slot tables; this was not a packet/battery audit replay.
Maximum residuals are the saved per-run plan-verification maxima. Budget fields
retain the 1 s solver/scheduling budget checks. `solver_checks.csv` retains the
12 separate short solver statuses/residuals/runtimes.

`offline_reference_differences.csv` describes online weighted score minus the
continuous perfect-input expected-goodput reference. It is not a pathwise lower
bound on stochastic realized costs, and it has no identifiable packet-delay
samples or optimal packet-delay interpretation.

## Reproducibility and omissions

`inputs/` copies only saved small tables/settings/audit reports/status records
and a newly extracted runtime capsule. Large raw slot/packet/offline-plan ledgers,
solar downloads, historical runs and the environment are omitted. Previously
passed raw-ledger/source audits are retained as evidence, not claimed as replayed.
No experiments/model/policy parameters were changed. Adaptive forecast margins
remain included; adaptive penalty updates remain excluded.
