# EE 541 Project: Prediction-Aware Packet Scheduling

**Team:** Protyay Dey and Arghadeep Saha

**Project:** Convex optimization for scheduling transmissions from an energy-harvesting wireless sensor with a finite battery and packet buffer.

The project develops and evaluates a prediction-aware scheduling method for an energy-harvesting sensor. The submitted [project proposal](docs/submitted_proposal.tex) describes the formulation and planned work.

The current simulators use correlated continuous lognormal channel gains and
accurate numerical probe feedback, identifiable 32-byte packets, independent
BER-based reception, reliable ACK departures and retransmissions. Channel gains
are effective SNR per watt, held for one interval, with rho 0.68. The original
zero-log-state and stationary mean-normalized variants use sigma 0.20/0.45/0.80;
solar defaults to sigma 0.45, normalized. There is no five-state mapping, gain cap
or full-episode sample normalization. Forecasts use causal conditional means and
timestamped reports, including observation gaps after missed probes.

Every executed probe costs 0.2 J, including A0; an unaffordable probe yields no
fresh report or data. Packet payload remains 256 bits, arrivals uniform 0–10,
attempts 0–5, buffer 32, and online horizon 10. The five-second virtual interval
still reserves probe/report/decision/data/ACK/update/guard durations of
0.3/0.3/1/1/1/1/0.4 seconds. Reports arrive at 0.6 s, ACKs are processed at 3.6 s,
and arrivals/harvest commit at interval end. Other modeled control energy defaults
to zero; physical energy is never discounted by objective weights. No real-time
sleeping occurs. See [the receiver model](docs/receiver_feedback.md).

Final episodes default to 1,000 slots. The original synthetic sweep uses seeds
5000–5009 and the normalized sweep 6000–6009: each is two harvest means × three
sigmas × ten seeds × five policies = 300 runs. Solar retains three sources × ten
window/seed scenarios × ten policies = 300 runs. The active online total is now
**900 runs**. Offline references use 60 normalized synthetic plus 30 solar
scenarios. Solar selection, native intervals, missing-data checks and overlap
records are preserved; its intervals remain approximate/descriptive summaries of
dependent windows. All three real solar inputs now match their recorded SHA-256
checksums. [Input validation](results/solar_input_check_1000/input_verification.json)
confirmed 30 consecutive 1,000-sample windows and the 300-run solar matrix.
**Production completed on 20 November 2026 at 11:09:39 UTC.** The
[completed timestamped root](results/final_evaluation_continuous_1000_20261120T075329Z_4_f31b28/status.json)
passed all 21 stages and final completion audit. It contains 900 main runs,
240 supplementary runs, 90 references and 12 solver checks. See the
[completion reconciliation](results/recovery_20261120/completion_verification.json)
and [current protocol](docs/experiments_1000.md). Future reruns require a fresh root.
Historical results and their original assumptions remain preserved.

The shared attempted-service cap is now **5**, with actions 0–5 in both simulators.
Actual virtual-time packet ledgers are exported to `per_packet.csv`. Initial
waiting measures admission to first data-burst start; ACK-completion delay measures
admission to successful ACK/departure and includes retries. Primary completed-
observation statistics exclude initial packets; rejected and unfinished packets
retain missing delays and explicit cohort/censoring fields. See
[packet timing, fields and audit definitions](docs/packet_delays.md).
Real-input checks passed on 60 short final-policy runs and 21 short older-simulator
runs, preserving native solar intervals. The complete suite passed 94 tests in
50.470 seconds. [Verification records](results/solar_packet_delay_smoke_real/verification.json)
cover source reconstruction, packet/delay and battery audits, and run-level summaries.

Two [fixed supplementary studies](docs/supplementary_studies.md) are completed:
120 delay–energy executions and 120 channel-forecast-sensitivity executions.
They preserve the main 900-run matrix and repeat its baseline cases as documented;
the repeats are not additional independent repetitions. Adaptive penalty-weight
updates are explicitly excluded. Full main and supplementary production runs
passed their audits; earlier implementation verification used smoke runs and benchmarks.
Final checks passed **101 tests** and both 1,000-slot supplementary benchmark
audits. [Readiness evidence](results/supplementary_verification/readiness.json)
records the preserved main behavior, real-input checks and runtime estimates.

## Implemented work

- A CVXPY implementation of the proposal's weighted finite-horizon objective and its channel-rate, queue, battery, service and energy constraints.
- Causal receding-horizon scheduling with nominal forecasts, fixed uncertainty margins, adaptive margins, and separate channel, arrival and harvest ablations.
- Matched comparisons with greedy, fixed-power, channel-aware and fixed-fraction heuristics; the final solar study also includes separate channel and arrival margin ablations.
- The two active correlated-channel volatility sweeps and comparisons on ten windows from each of three solar-data sources, plus a full-horizon expected-goodput reference. Historical saved results use the earlier model; the completed timestamped production above uses the current model.
- A CLARABEL-versus-SCS comparison on six optimization instances, unit tests, and audits of the saved physical actions and offline plans. The audits check stated conditions; they do not prove global online optimality or guaranteed uncertainty coverage.

Historical results and diagnostic outputs are under [`results/final_evaluation`](results/final_evaluation). New runs use the fresh `results/final_evaluation_continuous_1000/` root. The [technical documentation](FINAL_HANDOFF.md) describes the assumptions, evaluation settings and limitations in more detail.

### Historical findings

The uncertainty-aware approach improves the proposal's weighted cost in some tested conditions but not all. For example, on a mean-normalized synthetic scenario with scarce harvest, adaptive harvest margins reduced average cost against nominal MPC; in a higher-harvest scenario they increased it. Solar-source results also vary, and the 10 windows per source can be correlated. **The results do not support saying that our method is better than every baseline or in every scenario.**

The final analysis should explain when uncertainty margins help and when conservatism can hurt. Consider queue occupancy, rejected arrivals, transmission energy, throughput and final backlog together. Report measured differences and their uncertainty without treating a small number of runs as a universal guarantee.

## Remaining tasks for the course project

1. **Review the full formulation and implementation.** Check the variables, weighted objective, Shannon-rate constraint, energy causality, queue and battery dynamics, terminal constraints, and why the resulting finite-horizon model is convex. Be prepared to explain the receding-horizon decisions and the uncertainty-aware extension in the presentation and Q&A.
2. **Validate the simulation and results.** Review the saved solver statuses, feasibility residuals, CLARABEL/SCS comparison, physical-state audits and offline-reference audit. Confirm that the nominal, fixed-margin and adaptive comparisons use matched traces and that conclusions reflect the recorded evidence. Investigate numerical warnings rather than suppressing them.
3. **Resolve the model assumptions before finalizing the report.** The optimizer can plan rejection while the current simulator rejects only actual forced overflow; the older simulator optionally also rejects arrivals proactively. The optional first-slot consistency constraint is an experiment, not a proven performance improvement. Current synthetic and solar traffic is uniform on 0–10; saved results used earlier arrival settings. Planning uses continuous expected goodput with attempted service capped at 5, while execution uses whole packets and ACK departures. Use the measured initial waiting and ACK-completion delays with their completed-observation cohorts, censoring and counts; average queue occupancy remains a separate metric in packets.
4. **Review the real-data scenarios and their physical interpretation.** ARCO panel current, UMass household panel current and NREL TMY3 irradiance are used as solar-shaped inputs with **assumed**, uncalibrated conversions to harvested energy. Their slot lengths differ, and channel and traffic are synthetic. Verify the dataset provenance and hashes, describe the conversions and timing clearly, and avoid interpreting these as three directly measured IoT harvesting systems. Add a conversion or operating-condition sensitivity check if the professor expects stronger physical validation.
5. **Interpret the baselines and uncertainty-aware extension.** Distinguish nominal, fixed-margin and adaptive MPC; explain the one-step error margins, warm-up period and empirical coverage. Identify which margins help or hurt and why. The full-horizon reference now uses deterministic expected goodput and perfect future inputs. Its differences against realized stochastic online costs are descriptive and imply no pathwise bound.
6. **Choose the final evidence and figures.** Select two to four clear figures or tables showing the main question, performance trade-offs, empirical forecast-bound behavior and numerical correctness. Use the saved sample sizes and paired comparisons, label units and different slot lengths, and make clear that correlated solar windows limit statistical interpretation. A starting set is linked below.
7. **Finish the course deliverables.** Prepare the final technical report and presentation, including the system model, methodology, evidence, limitations, references and each team member's actual contribution. Review the professor's requirements, any permitted-tool disclosure, and citation obligations. Both team members must be ready to explain the entire project, not only their individual component.

## Results and supporting material

- [Mean-normalized synthetic comparison](results/final_evaluation/sweep_normalized/realized_cost.png) and [rejection comparison](results/final_evaluation/sweep_normalized/drop_ratio.png).
- [Empirical one-step uncertainty-bound coverage](results/final_evaluation/figures/one_step_coverage.png).
- [Paired solar-source cost differences](results/final_evaluation/figures/solar_paired_cost.png).
- [Solver comparison](results/final_evaluation/solver/solver_comparison.csv), [solar results](results/final_evaluation/solar/per_window.csv), and [clairvoyant-reference audit](results/final_evaluation/offline/audit.json).
- [Dataset provenance and attribution](data/arco/README.md), [UMass](data/umass/README.md), and [NREL](data/nrel/README.md). Raw datasets are not included; the recorded checksums are in the relevant experiment settings.

The final report, presentation, joint review and any necessary final validation remain to be completed. The instructor's project brief is not included in this repository; follow its requirements for citations and tool disclosure.
