# Suggested figure captions

## supporting/sweep/realized_cost

Original, non-mean-normalized channel; each point averages ten matched seed runs, each 1000 five-second intervals. Error bars are unadjusted 95% seed-level t intervals for means, not paired-effect tests. Paired contrasts are in the performance tables. Original σ changes average gain as well as higher moments; normalization fixes theoretical mean only.

Plotted data: `plotted_data/supporting__sweep__realized_cost.csv`.

## supporting/sweep/drop_ratio

Original, non-mean-normalized channel; each point averages ten matched seed runs, each 1000 five-second intervals. Error bars are unadjusted 95% seed-level t intervals for means, not paired-effect tests. Paired contrasts are in the performance tables. Original σ changes average gain as well as higher moments; normalization fixes theoretical mean only.

Plotted data: `plotted_data/supporting__sweep__drop_ratio.csv`.

## supporting/sweep/queue

Original, non-mean-normalized channel; each point averages ten matched seed runs, each 1000 five-second intervals. Error bars are unadjusted 95% seed-level t intervals for means, not paired-effect tests. Paired contrasts are in the performance tables. Original σ changes average gain as well as higher moments; normalization fixes theoretical mean only.

Plotted data: `plotted_data/supporting__sweep__queue.csv`.

## supporting/sweep/energy

Original, non-mean-normalized channel; each point averages ten matched seed runs, each 1000 five-second intervals. Error bars are unadjusted 95% seed-level t intervals for means, not paired-effect tests. Paired contrasts are in the performance tables. Original σ changes average gain as well as higher moments; normalization fixes theoretical mean only.

Plotted data: `plotted_data/supporting__sweep__energy.csv`.

## supporting/sweep/coverage_gain

Original, non-mean-normalized channel; each point averages ten matched seed runs, each 1000 five-second intervals. Error bars are unadjusted 95% seed-level t intervals for means, not paired-effect tests. Coverage is empirical, not a guarantee. Paired contrasts are in the performance tables. Original σ changes average gain as well as higher moments; normalization fixes theoretical mean only.

Plotted data: `plotted_data/supporting__sweep__coverage_gain.csv`.

## supporting/sweep_normalized/realized_cost

Stationary mean-normalized channel; each point averages ten matched seed runs, each 1000 five-second intervals. Error bars are unadjusted 95% seed-level t intervals for means, not paired-effect tests. Paired contrasts are in the performance tables. Original σ changes average gain as well as higher moments; normalization fixes theoretical mean only.

Plotted data: `plotted_data/supporting__sweep_normalized__realized_cost.csv`.

## supporting/sweep_normalized/drop_ratio

Stationary mean-normalized channel; each point averages ten matched seed runs, each 1000 five-second intervals. Error bars are unadjusted 95% seed-level t intervals for means, not paired-effect tests. Paired contrasts are in the performance tables. Original σ changes average gain as well as higher moments; normalization fixes theoretical mean only.

Plotted data: `plotted_data/supporting__sweep_normalized__drop_ratio.csv`.

## supporting/sweep_normalized/queue

Stationary mean-normalized channel; each point averages ten matched seed runs, each 1000 five-second intervals. Error bars are unadjusted 95% seed-level t intervals for means, not paired-effect tests. Paired contrasts are in the performance tables. Original σ changes average gain as well as higher moments; normalization fixes theoretical mean only.

Plotted data: `plotted_data/supporting__sweep_normalized__queue.csv`.

## supporting/sweep_normalized/energy

Stationary mean-normalized channel; each point averages ten matched seed runs, each 1000 five-second intervals. Error bars are unadjusted 95% seed-level t intervals for means, not paired-effect tests. Paired contrasts are in the performance tables. Original σ changes average gain as well as higher moments; normalization fixes theoretical mean only.

Plotted data: `plotted_data/supporting__sweep_normalized__energy.csv`.

## supporting/sweep_normalized/coverage_gain

Stationary mean-normalized channel; each point averages ten matched seed runs, each 1000 five-second intervals. Error bars are unadjusted 95% seed-level t intervals for means, not paired-effect tests. Coverage is empirical, not a guarantee. Paired contrasts are in the performance tables. Original σ changes average gain as well as higher moments; normalization fixes theoretical mean only.

Plotted data: `plotted_data/supporting__sweep_normalized__coverage_gain.csv`.

## supporting/solar/realized_cost

Ten matched scenarios per source, 1000 intervals each. Points are run-level means. Intervals are descriptive paired-scenario t intervals for differences (or descriptive scenario intervals for means), not independent-record confidence intervals. Shared source/site/season dependence remains; nine NREL window pairs overlap. ARCO/UMass intervals are 60 s, NREL 3600 s; physical delays/throughput are compared within a source.

Plotted data: `plotted_data/supporting__solar__realized_cost.csv`.

## supporting/solar/drop_ratio

Ten matched scenarios per source, 1000 intervals each. Points are run-level means. Intervals are descriptive paired-scenario t intervals for differences (or descriptive scenario intervals for means), not independent-record confidence intervals. Shared source/site/season dependence remains; nine NREL window pairs overlap. ARCO/UMass intervals are 60 s, NREL 3600 s; physical delays/throughput are compared within a source.

Plotted data: `plotted_data/supporting__solar__drop_ratio.csv`.

## supporting/solar/queue

Ten matched scenarios per source, 1000 intervals each. Points are run-level means. Intervals are descriptive paired-scenario t intervals for differences (or descriptive scenario intervals for means), not independent-record confidence intervals. Shared source/site/season dependence remains; nine NREL window pairs overlap. ARCO/UMass intervals are 60 s, NREL 3600 s; physical delays/throughput are compared within a source.

Plotted data: `plotted_data/supporting__solar__queue.csv`.

## supporting/solar/energy

Ten matched scenarios per source, 1000 intervals each. Points are run-level means. Intervals are descriptive paired-scenario t intervals for differences (or descriptive scenario intervals for means), not independent-record confidence intervals. Shared source/site/season dependence remains; nine NREL window pairs overlap. ARCO/UMass intervals are 60 s, NREL 3600 s; physical delays/throughput are compared within a source.

Plotted data: `plotted_data/supporting__solar__energy.csv`.

## supporting/figures/solar_paired_cost

Ten matched scenarios per source, 1000 intervals each. Points are paired policy-minus-nominal weighted-score differences; negative is lower. Intervals are descriptive paired-scenario t intervals for differences (or descriptive scenario intervals for means), not independent-record confidence intervals. Shared source/site/season dependence remains; nine NREL window pairs overlap. ARCO/UMass intervals are 60 s, NREL 3600 s; physical delays/throughput are compared within a source.

Plotted data: `plotted_data/supporting__figures__solar_paired_cost.csv`.

## main/02_solar_paired_cost

Ten matched scenarios per source, 1000 intervals each. Two contrasts compare convex MPC with greedy; the third compares the MPC forecast-margin strategies. Negative means lower weighted score. Bars are unadjusted 95% descriptive paired-scenario t intervals, not independent solar-record confidence intervals. Shared source/site/season dependence remains; nine NREL window pairs overlap. ARCO/UMass intervals are 60 s, NREL 3600 s. All ten policies remain in the supporting figures/tables; physical delay and throughput comparisons stay within source.

Plotted data: `plotted_data/main__02_solar_paired_cost.csv`.

## supporting/figures/one_step_coverage

All displayed policies are convex MPC. Normalized conditions are averaged within each seed before averaging across ten seeds; unadjusted 95% t intervals use those ten seed means. Adaptive-all coverage is approximately 79%, not a guaranteed 80%. The dashed 80% line is a reference only. Coverage is one-step empirical report-based coverage, not simultaneous horizon coverage or a chance-constraint guarantee.

Plotted data: `plotted_data/supporting__figures__one_step_coverage.csv`.

## main/05_empirical_coverage

All displayed policies are convex MPC. Normalized conditions are averaged within each seed before averaging across ten seeds; unadjusted 95% t intervals use those ten seed means. Adaptive-all coverage is approximately 79%, not a guaranteed 80%. The dashed 80% line is a reference only. Coverage is one-step empirical report-based coverage, not simultaneous horizon coverage or a chance-constraint guarantee.

Plotted data: `plotted_data/main__05_empirical_coverage.csv`.

## supporting/supplementary/delay_energy/delay_energy

Energy weight is constant at 0.15, 15 or 150 throughout each run. Ten matched synthetic seeds per setting; 1000 five-second intervals. Both axes use run-level means and unadjusted 95% t intervals; they are not a joint confidence region. Shapes encode settings; nested open markers retain coincident points without jitter. Connected points are an empirical trade-off, not a certified Pareto frontier. Initial packets are excluded from primary delay cohorts. Completed-only delays include retries/ACK waiting; rejected arrivals were never admitted. See delay_cohorts.csv for admissions, completions, valid samples, rejection, throughput and unfinished fractions; shorter completed-only delay is not sufficient evidence of better overall service.

Plotted data: `plotted_data/supporting__supplementary__delay_energy__delay_energy.csv`.

## supporting/supplementary/delay_energy/channel_forecast_errors

Quantity shown is the perturbed base channel forecast before uncertainty margins, evaluated against post-run actual gains at the labeled decision lead. Policy panels separate overlapping curves; policies, base forecasts and margin-adjusted forecasts are not pooled. Each line averages ten per-run RMSEs with unadjusted seed-level 95% t bands; slots are not repetitions. Gain/RMSE units are effective SNR per watt (1/W), not RSSI. Zero added noise retains channel-process forecast error; current probe reports remain ideal. All three forecast quantities remain separate in forecast_error_by_lead.csv.

Plotted data: `plotted_data/supporting__supplementary__delay_energy__channel_forecast_errors.csv`.

## supporting/supplementary/forecast_sensitivity/delay_energy

Added future-channel forecast noise amplitudes are 0, 0.25 and 0.50; energy weight stays 0.15. Ten matched synthetic seeds per setting; 1000 five-second intervals. Both axes use run-level means and unadjusted 95% t intervals; they are not a joint confidence region. Shapes encode settings; nested open markers retain coincident points without jitter. Connected points are an empirical trade-off, not a certified Pareto frontier. Initial packets are excluded from primary delay cohorts. Completed-only delays include retries/ACK waiting; rejected arrivals were never admitted. See delay_cohorts.csv for admissions, completions, valid samples, rejection, throughput and unfinished fractions; shorter completed-only delay is not sufficient evidence of better overall service.

Plotted data: `plotted_data/supporting__supplementary__forecast_sensitivity__delay_energy.csv`.

## supporting/supplementary/forecast_sensitivity/channel_forecast_errors

Quantity shown is the perturbed base channel forecast before uncertainty margins, evaluated against post-run actual gains at the labeled decision lead. Policy panels separate overlapping curves; policies, base forecasts and margin-adjusted forecasts are not pooled. Each line averages ten per-run RMSEs with unadjusted seed-level 95% t bands; slots are not repetitions. Gain/RMSE units are effective SNR per watt (1/W), not RSSI. Zero added noise retains channel-process forecast error; current probe reports remain ideal. All three forecast quantities remain separate in forecast_error_by_lead.csv.

Plotted data: `plotted_data/supporting__supplementary__forecast_sensitivity__channel_forecast_errors.csv`.

## main/01_normalized_cost_rejection

Normalized synthetic channel, 1000 five-second intervals per run. Differences pair the same ten seeds within every harvest/σ condition; bars are unadjusted 95% t intervals. Solid curves compare each convex MPC policy with greedy; the dashed contrast compares their forecast-margin strategies. Negative values mean lower cost or rejection. No slots or packets are treated as independent repetitions; higher moments still vary with σ.

Plotted data: `plotted_data/main__01_normalized_cost_rejection.csv`.

## main/03_energy_ack_delay

Energy weight is constant at 0.15, 15 or 150 throughout each run. Ten matched synthetic seeds per setting; 1000 five-second intervals. Both axes use run-level means and unadjusted 95% t intervals; they are not a joint confidence region. Shapes encode settings; nested open markers retain coincident points without jitter. Connected points are an empirical trade-off, not a certified Pareto frontier. Initial packets are excluded from primary delay cohorts. Completed-only delays include retries/ACK waiting; rejected arrivals were never admitted. See delay_cohorts.csv for admissions, completions, valid samples, rejection, throughput and unfinished fractions; shorter completed-only delay is not sufficient evidence of better overall service.

Plotted data: `plotted_data/main__03_energy_ack_delay.csv`.

## main/04_forecast_noise_paired

Paired adaptive-all minus nominal MPC responses; each amplitude uses the same ten scenario seeds and common exogenous traces. Negative means lower score/rejection/completed ACK delay. Error bars are unadjusted 95% seed-level t intervals. Actual channel remains normalized rho=0.68, sigma=0.45; only future channel forecasts are perturbed. No independent arrival/harvest forecast-error intervention occurred. Zero added noise still has process forecast error. ACK delay is completed-only; the companion cohort table retains admissions, completions, rejection, throughput and unfinished fractions. Common-reference score always uses energy weight 0.15.

Plotted data: `plotted_data/main__04_forecast_noise_paired.csv`.

## supporting_extra/forecast_noise_outcomes

Absolute nominal/adaptive-all responses use means across ten seed runs; paired policy differences are shown separately in main figure 04. Error bars are unadjusted 95% seed-level t intervals. Actual channel remains normalized rho=0.68, sigma=0.45; only future channel forecasts are perturbed. No independent arrival/harvest forecast-error intervention occurred. Zero added noise still has process forecast error. ACK delay is completed-only; the companion cohort table retains admissions, completions, rejection, throughput and unfinished fractions. Common-reference score always uses energy weight 0.15.

Plotted data: `plotted_data/supporting_extra__forecast_noise_outcomes.csv`.
