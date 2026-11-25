# Final experiment results

The [production tables](production) contain the saved run matrices, settings,
run-level metrics, summaries, paired comparisons and numerical audits. The
[completion record](completion_verification.json) covers 900 main runs,
240 supplementary runs, 90 offline references and 12 solver checks.

## Figures

| Figure | Comparison |
| --- | --- |
| [Cost and rejection](report_figures/main/01_normalized_cost_rejection.pdf) | Nominal and adaptive MPC against greedy in the normalized synthetic sweep |
| [Solar cost](report_figures/main/02_solar_paired_cost.pdf) | Paired cost differences relative to nominal MPC across the three solar sources |
| [Energy and packet delay](report_figures/main/03_energy_ack_delay.pdf) | Energy use and delay among acknowledged packets under different energy penalties |
| [Forecast sensitivity](report_figures/main/04_forecast_noise_paired.pdf) | Changes in weighted cost and rejection under added channel forecast noise |
| [Empirical forecast coverage](report_figures/main/05_empirical_coverage.pdf) | Observed one-step coverage for channel, arrival and harvest margins |

The [reproduction commands](../README.md#reproduce-the-experiments) regenerate
the full ledgers and recreate the analysis tables and figures.
