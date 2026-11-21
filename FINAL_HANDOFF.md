# EE 541 course project — final evaluation handoff

**Current production status — completed 20 November 2026, 11:09:39 UTC.**
The fresh batch in
[`results/final_evaluation_continuous_1000_20261120T075329Z_4_f31b28/`](results/final_evaluation_continuous_1000_20261120T075329Z_4_f31b28/status.json)
passed all 21 stages and its final completion audit. Independent reconciliation
confirmed 300 original, 300 normalized, 300 solar, 120 delay–energy and 120
forecast-sensitivity runs: 1,140,000 actual online slot records, each episode
1,000 slots with horizon 10, plus 90 offline references and 12 solver checks.
All packet/battery/aggregate/delay/source/solver audits and 20 plots are present.
The launcher exited 0 and its production lock is free; no restart is needed.

The first attempt failed in stage 05 after 119 completed run checkpoints and
remains preserved/incomplete. Its slot-171 numerical failure was reproduced and
corrected with positive constant objective normalization; the model and 1e-4
residual threshold are unchanged. The 102-test recovery suite passed before
launch. [Recovery details](docs/solver_recovery.md) and the
[completion verification](results/recovery_20261120/completion_verification.json)
record provenance and output checks. The prelaunch notes below retain their
historical scope; the actual completed production is the timestamped root above.

**Historical evaluation:** the saved results and numerical findings below predate
the whole-packet probe/ACK/retransmission model. The current implementation and
its assumptions are described in [receiver_feedback.md](docs/receiver_feedback.md).
Regenerate experiments before reporting current-model results. In particular,
the current offline expected-goodput reference is not a bound on realized
stochastic online costs; the lower-bound discussion below describes the earlier
deterministic model only.

Current final defaults are 1,000 slots with online horizon 10 and the restored
correlated lognormal channel (rho 0.68; sigma 0.20/0.45/0.80). Original and
stationary mean-normalized sweeps have 300 policy-runs each, with historical seed
ranges 5000–5009 and 6000–6009. Solar has 300 runs and defaults to normalized
sigma 0.45. The online total is 900; normalized-synthetic/solar references contain
90 full-episode problems. Use the [current protocol](docs/experiments_1000.md)
and fresh `results/final_evaluation_continuous_1000/` root.

Numerical gain feedback replaces five-state condition feedback, available at
0.6 s. ACK departures occur at 3.6 s. The 0.3/0.3/1/1/1/1/0.4-second virtual
phases, 0.2 J probes, packet IDs/retries, BER outcomes, uniform 0–10 arrivals,
0–5 attempts and next-interval harvest/arrival availability remain intact.
The channel-aware baseline preserves the latest numerical threshold 0.8.
Solar windows retain native intervals, real missing values and overlap records.
All three real inputs are now present and match their recorded SHA-256 checksums.
The [input validation records](results/solar_input_check_1000/input_verification.json)
confirm 30 valid 1,000-sample windows and 300 planned solar policy-runs. ARCO and
UMass selections are disjoint; NREL has nine overlapping pairs. No new production
results were generated.

Packet timestamps are now recorded by persistent ID. The initial queue has
bookkeeping admission time zero and is excluded from primary delay statistics.
New completed initial-wait and ACK-completion metrics, censoring counts and
outstanding ages are described in [packet_delays.md](docs/packet_delays.md).
Historical statements below that packet ages were untracked refer to old results.

Resumed verification on 20 November 2026 passed 94 tests and syntax parsing of
all 34 Python files. Final fixes bind every packet-run metadata field to its
run ID during auditing and add valid-run counts to the older consistency summary.
The saved A5 benchmark was re-audited successfully: 13.4600 s execution,
13.1270 ms per optimization call and no decision-budget overruns. Its runtime
was reused, not remeasured. See the [resumed verification
records](docs/packet_delays.md#resumed-verification-20-november-2026).
No production matrix was launched. Adaptive penalty-weight updates are excluded;
the two supplementary studies are now prepared as described below.

Subsequent real-input verification passed 94 tests in 50.470 seconds and syntax
parsing of all 34 Python files. Short runs covered all ten final solar policies
(60 twelve-slot runs) and all seven older-simulator policies (21 twelve-slot runs
using prefixes of validated 1,000-slot windows). Packet/battery conservation,
ACK/retry timing, delay ledgers, full run identifiers, summary/pair counts and
source audits passed. The final-policy workflow exercised every action 0–5,
25 failed attempts and 20 intervals without an affordable probe, with no decision
budget overruns. [Saved evidence](results/solar_packet_delay_smoke_real/verification.json)
completes the action/delay verification and resolves the missing-input blocker.
The production study remains deferred for the final system/model review.

The [supplementary protocol](docs/supplementary_studies.md) fixes two 120-run
studies: energy weights 0.15/15/150 and future-channel forecast amplitudes
0/0.25/0.50. Both use normalized sigma 0.45, rho 0.68, harvest 0.6/1.2, seeds
6000–6009, nominal/adaptive_all, 1,000 slots and horizon 10. Weights remain constant
within a run. Common-reference scores use the main weights. Channel perturbations
are keyed by scenario/origin/lead, preserve current reports, precede margins and
are scored in adaptive history. Main defaults and matched physical random streams
are preserved. Baseline repetitions across studies are documented, not additional
independent observations. No supplementary offline matrix is added. Production
commands, output semantics and final verification are in the linked protocol.

Final readiness checks passed **101 tests in 73.673 seconds** and syntax parsing
of all **39 Python files**. Both temporary supplementary workflows passed their
analysis/audits/plots, and exactly one 1,000-slot benchmark per study passed its
independent audit. Policy execution times were 13.1787 s at energy weight 15
and 13.0524 s at forecast amplitude 0.25; neither overran the decision budget.
All real inputs/windows and previous main/real-solar records were rechecked.
The [readiness record](results/supplementary_verification/readiness.json) finds
no remaining implementation/data blocker under the documented assumptions.
Main and supplementary full experiments remain prepared but unexecuted. No
performance improvement is inferred from smoke runs or these timing benchmarks.

The completed historical 80-slot experiments and reproduction examples below
retain their historical meaning. Their numerical results are not current-model
results. The five-state intermediate stage and its 400-run protocol are superseded.

## Core question and implementation

How do forecast-based uncertainty margins change the backlog, rejection and energy trade-off in finite-horizon energy-harvesting packet scheduling?

`src/scheduling.py` implements the weighted objective in `docs/submitted_proposal.tex`: `sum(b + 35*o + 0.15*tau*p) + 6*b_terminal`. The coefficients are experimental choices; the proposal did not prescribe them. Queue and battery dynamics are affine, and the Shannon capacity constraint is the hypograph of a concave function for fixed nonnegative channel gain. CVXPY checks disciplined convexity. `proposal_study.py` runs receding-horizon MPC: it observes the current queue, energy and channel, forecasts from historical observations, solves, and applies the first action. Current arrivals and harvest are observed only after service. It records one-step forecast errors and empirical bound coverage.

`nominal`, `fixed_margin`, `adaptive_harvest` and `adaptive_all` share the same predictor, horizon, objective, physical execution, seeds and traces. `adaptive_all` uses one-sided rolling 80th-percentile errors to lower predicted future gain/harvest and increase predicted arrivals; `adaptive_harvest` adjusts only harvest. A fixed warm-up is used until 12 scores are available. These are empirical heuristic bounds—not guaranteed 80% coverage, not a simultaneous chance constraint, and not a general robust-MPC theorem. The exact current channel is observed and is not lowered.

The optimizer can plan discretionary rejection, whereas the simulator executes only actual forced overflow rejection after arrivals. This mismatch is documented rather than hidden. `consistency_study.py` examines an optional convex first-slot rejection cap; it improves planning consistency with its own forecast but did not consistently improve realized cost. The report should distinguish planned rejection, actual forced overflow, and forecast mismatch.

## Setup and reproduce

Python 3.11 was used on macOS. Run in the package/project root:

```bash
conda create -n ee541 python=3.11  # omit if already created
conda activate ee541
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

For solar experiments download the three files described in `data/arco/README.md`, `data/umass/README.md`, and `data/nrel/README.md`; then verify their hashes against `results/final_evaluation/solar/settings.json`. Raw datasets are intentionally not included in the handoff ZIP. ARCO's upstream repository did not visibly state redistribution terms when checked, so confirm those terms before redistributing its raw data. The instructor's project brief is also intentionally not included.

```bash
# Independent same-instance solver comparison.
python solver_crosscheck.py --out results/my_solver_check

# Synthetic matched sweep; alternate process has theoretical mean channel gain 1.
python final_evaluation.py --mean-normalize --seeds 10 --seed-start 6000 --slots 80 --horizon 10 --out results/my_normalized
python audit_final_evaluation.py results/my_normalized

# Three solar-proxy sources, 10 disjoint windows per source.
python final_solar_evaluation.py --windows 10 --slots 80 --horizon 10 --out results/my_solar
python audit_comparison.py results/my_solar
python audit_final_solar.py results/my_solar
```

Use fresh output paths to preserve existing results. To reproduce the offline reference and figures, `offline_reference.py` and `plot_final_figures.py` expect a common root containing folders named `sweep_normalized` and `solar`, as in `results/final_evaluation`:

```bash
python offline_reference.py --root results/final_evaluation
python audit_offline.py results/final_evaluation/offline
python plot_final_figures.py --root results/final_evaluation
```

These last commands overwrite files in their target folder; copy the root first to preserve the originals. The solar overlap audit checks against earlier saved project windows *when those files are available*; its `source_audit.json` records its scope. No result should be called prospectively registered or site-independent.

## Completed evaluation

- **Synthetic sweeps:** two fixed-protocol sweeps, each with 2 mean-harvest levels × 3 channel innovation levels × 10 seeds × 5 methods, for 300 paired trajectories per sweep and 80 slots each. One has a stationary, mean-one lognormal channel; the other uses the original nonnormalized process. Arrival counts are Poisson with mean 2.5 clipped to 0–10, matching the proposal's support. Channel volatility changes more than forecast accuracy (it changes higher moments), so it is not a pure forecast-noise intervention. The current channel is observed. See `sweep_normalized/` and `sweep/`.
- **Solar-derived input:** 3 distinct sources × 10 windows × 7 methods, 210 trajectories, 80 slots each. It includes fixed-power, channel-aware and greedy heuristics in addition to the MPC variants. The source and physical-action audits passed, including nonoverlap with available earlier saved windows. Windows remain correlated observations from one site or representative-year source each; they are not 30 independent sites. See `solar/`.
- **Correctness:** on six representative 10-slot instances, CLARABEL and SCS each returned `optimal`; the largest relative objective difference was about `2.63e-6`, and the largest independently checked primal violation was about `1.35e-5`. The action audits passed all 810 sweep and solar trajectories. The maximum recorded planned residuals were below `1e-4`; no returned status was `optimal_inaccurate`. Individual attempts emitted numerical-accuracy warnings (8 original synthetic, 10 normalized synthetic, 5 solar); review the saved run logs. Physical audits do not reconstruct complete predicted plans or prove optimality.
- **Clairvoyant reference:** 90 full-horizon convex problems use actual future channel, arrivals and harvest. The objective is identical, but the offline model can proactively reject and is therefore more permissive than forced-overflow execution. Its theoretical optimum is a lower bound for feasible forced-only online rollouts. The numerical primal solution is an approximate reference, not a certified dual lower bound. All 90 returned `optimal`; saved plans passed the independent trace, constraint and objective audit. The most negative observed online-minus-offline difference was about `-7.9e-7`, numerical tolerance rather than evidence the online policy beats the theoretical optimum. See `offline/`.

## Findings to use carefully

In the mean-normalized synthetic sweep, at mean harvest 0.6 J/slot and channel innovation 0.45, adaptive-harvest cost was **2727.07** versus **2877.55** for nominal; the paired difference was about **−150.48** with an unadjusted approximate 95% interval **[−257.01, −43.95]** across 10 seeds. At mean harvest 1.2 and the same channel innovation, adaptive-harvest cost was **644.42** versus **602.35** for nominal (difference **+42.08**, interval **[+7.91, +76.25]**). Higher volatility also changes the gain distribution and these are multiple exploratory comparisons; do not report these intervals as universal guarantees or corrected significance claims.

The solar-proxy evaluation did not show an unambiguous adaptive benefit over nominal: for ARCO, adaptive-harvest averaged **3383.88** versus **3425.39** and its paired interval included zero; for NREL TMY3, fixed-margin averaged **702.59** versus nominal **768.55**, but the paired interval is only approximate for correlated windows. UMass nominal and adaptive costs were close. Results depend on assumed energy conversion, location, time of day, horizon and model weights. Report cases where conservatism helps and hurts; do not claim universal superiority.

Candidate figures for a concise report:

1. `results/final_evaluation/sweep_normalized/realized_cost.png` — objective across channel volatility and harvest levels, with seed-level intervals.
2. `results/final_evaluation/sweep_normalized/drop_ratio.png` — rejection trade-offs on the same traces.
3. `results/final_evaluation/figures/one_step_coverage.png` — empirical one-step bound coverage, aggregated by seed; dashed line is 0.8, not a guarantee.
4. `results/final_evaluation/figures/solar_paired_cost.png` — paired cost differences versus nominal on the three sources; windows from each source can be correlated.

Tables include `solver/solver_comparison.csv`, `sweep_normalized/paired_vs_nominal.csv`, `solar/paired_vs_nominal.csv` and `offline/paired_reference.csv`.

## Data and limitations

ARCO is measured one-minute solar-panel short-circuit current, converted using an **assumed** 0.01 J/(mA·slot); UMass Home C is household-panel current averaged to one minute, converted using an **assumed** 0.1 J/(mA·slot); NREL TMY3 is hourly global horizontal irradiance from a stitched typical meteorological year, converted using an **assumed** 0.005 J/((W/m²)·slot). These are solar-shaped proxies, not calibrated measurements of energy delivered to this transmitter. Solar channel and arrivals are synthetic. ARCO and UMass slots are 60 s; TMY slots are 3600 s; active transmission is 1 s. Synthetic slots are 5 s. Do not compare throughput in bits/s directly across those timescales.

The initial solar study in `results/proposal_final` used unbounded Poisson arrivals and some dates examined in earlier work; the final sweeps explicitly cap arrivals at 10. Mean queue is not measured packet waiting time; ages are not tracked. Model predictions are held fixed within each convex optimization, while actual future data vary. Numerical residual and coverage checks are empirical, not a proof of recursive feasibility or statistical coverage.

## Argha's remaining handoff tasks

1. Download the data, verify checksums, install dependencies, rerun tests and at least the solver check and a small sweep. Review the logs, statuses, and audits; if results cannot be reproduced, investigate rather than suppress warnings.
2. Review the implementation and proposal together with Protyay. Decide how to explain the optimizer's planned rejection versus forced execution, fluid packets, assumed solar scaling and differing slot lengths. Do not label queue occupancy as measured packet delay. Use the original proposal only as the team's source, and disclose any final deviations.
3. Select two to four figures/tables from the completed outputs, check axis units and captions, and explain both favorable and unfavorable scenarios. Include the numerical solver check and explain the clairvoyant reference's additional information and rejection relaxation.
4. With Protyay, write and review the final report, individual contribution statement, presentation and Q&A. Both members should understand the full model and evidence. Follow the course brief's attribution and permitted-tool disclosure instructions and verify permission before sharing instructor-provided materials externally.
5. Treat optional additional parameter sweeps, packet-age tracking, physically calibrated solar conversion and a stricter online/offline admission model as extensions—not as completed work. Do not present adaptive margins as a proven universal improvement or add an unsupported theorem.
