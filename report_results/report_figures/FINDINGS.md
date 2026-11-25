# Findings for a 5–7-page report (evidence notes, not the report)

## Supported numerical descriptions
- Nominal and adaptive-all are both convex MPC policies. Greedy comparisons measure a separate planning-versus-heuristic contrast; adaptive-all minus nominal isolates their forecast-margin strategies within this simulation.
- Adaptive-all is not universally best. Keep all harvest/volatility conditions and the fixed-margin/greedy references, including equal and unfavorable outcomes.
- Normalized harvest 0.6 J, σ=0.2: adaptive-all minus nominal common score = -23.30, unadjusted paired 95% t interval [-76.01, 29.41], 10 valid seed pairs.
- Normalized harvest 0.6 J, σ=0.45: adaptive-all minus nominal common score = -2166.30, unadjusted paired 95% t interval [-2935.09, -1397.52], 10 valid seed pairs.
- Normalized harvest 0.6 J, σ=0.8: adaptive-all minus nominal common score = -4320.47, unadjusted paired 95% t interval [-5137.85, -3503.08], 10 valid seed pairs.
- Normalized harvest 1.2 J, σ=0.2: adaptive-all minus nominal common score = 0.00, unadjusted paired 95% t interval [0.00, 0.00], 10 valid seed pairs.
- Normalized harvest 1.2 J, σ=0.45: adaptive-all minus nominal common score = 154.12, unadjusted paired 95% t interval [-17.12, 325.35], 10 valid seed pairs.
- Normalized harvest 1.2 J, σ=0.8: adaptive-all minus nominal common score = 1738.61, unadjusted paired 95% t interval [1286.88, 2190.34], 10 valid seed pairs.
- Adaptive-all empirical coverage after averaging conditions within each seed: coverage_gain=79.07%, coverage_arrival=78.98%, coverage_harvest=79.32%. This is approximately 79%, not a guaranteed 80%.
- Weight sensitivity, harvest 0.6, Nominal MPC: mean episode energy 606.51 → 572.40 J and completed ACK delay 24.356 → 26.814 s (w=0.15 → 150). These descriptive means require the paired score/cohort/rejection/throughput tables; they do not establish a Pareto frontier.
- Weight sensitivity, harvest 0.6, Adaptive-all MPC: mean episode energy 605.82 → 602.28 J and completed ACK delay 23.757 → 23.594 s (w=0.15 → 150). These descriptive means require the paired score/cohort/rejection/throughput tables; they do not establish a Pareto frontier.
- Weight sensitivity, harvest 1.2, Nominal MPC: mean episode energy 686.23 → 575.67 J and completed ACK delay 18.524 → 26.587 s (w=0.15 → 150). These descriptive means require the paired score/cohort/rejection/throughput tables; they do not establish a Pareto frontier.
- Weight sensitivity, harvest 1.2, Adaptive-all MPC: mean episode energy 685.00 → 632.94 J and completed ACK delay 18.576 → 21.097 s (w=0.15 → 150). These descriptive means require the paired score/cohort/rejection/throughput tables; they do not establish a Pareto frontier.

## Interpretation limits
- All uncertainty intervals here are unadjusted 95% t intervals; ten matched seed pairs within each condition, not 1000 independent slots or individual packets. They are exploratory/descriptive across many conditions; no familywise significance claim or normality certification is made.
- Completed-packet delays condition on admissions and observed completions. Initial packets are excluded; rejected arrivals were not admitted; missing/unfinished delays are not zero. Rejection, offered-completion rate, throughput and unfinished counts must accompany delay interpretations.
- The solar comparisons use dependent windows from shared sources/sites/seasons, including nine overlapping NREL pairs. Their intervals are descriptive rather than independent-record confidence intervals. Delays and bits/s must be compared within each source (60/60/3600 s).
- Added noise affects future channel forecasts only; zero added noise retains process error, and current probe reports remain ideal. Curves distinguish base/perturbed/planned quantities. Arrival/harvest forecast error was not independently intervened on.
- Main normalized σ changes channel higher moments; original σ also changes average gain. Neither main volatility sweep is a controlled forecast-error-only intervention.
- Common-reference cost uses energy weight 0.15 for every comparison. Configured scores at different weights are not the same scoring function.
- The offline reference uses perfect future inputs, continuous expected goodput and relaxed future controls/admission. Score gaps are descriptive, not pathwise bounds or an optimal packet-delay benchmark.
- Online convex planning uses continuous attempted service and expected-success queue dynamics; physical execution uses integer actions 0–5 and ACK-only packet departures. Future control activity is relaxed in planning. These distinctions remain part of the model, not a plotting correction.
- Adaptive forecast margins remain included; adaptive penalty updates are excluded. No claim of real-hardware or universal policy superiority follows from these simulations.

## Validation scope
- Checks performed now: completion/matrices/run-level identities and formulas, runtime-metadata extraction, every plotted estimate/interval/count, metadata/units/missing values, figure exports, and full before/after production-file hashes.
- Previously completed audits: packet events, battery trajectories, ACK/retry/deduplication, delay ledgers, full forecast reconstruction and source/raw offline-plan audits. Reports were checked as passed; these raw audits were not replayed for figure preparation.
