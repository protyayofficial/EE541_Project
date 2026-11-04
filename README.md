# EE 541 Project: Prediction-Aware Packet Scheduling

**Team:** Protyay Dey and Arghadeep Saha

**Project:** Convex optimization for scheduling transmissions from an energy-harvesting wireless sensor with a finite battery and packet buffer.

## Handoff for Argha

Protyay's initial uncertainty-aware implementation and comparative evaluation are available in this repository. Your remaining work is to review and complete the shared project for the course submission. The submitted [project proposal](docs/submitted_proposal.tex) is the reference for the formulation and intended division of work.

### What has been completed

- A CVXPY implementation of the proposal's weighted finite-horizon objective and its channel-rate, queue, battery, service and energy constraints.
- Causal receding-horizon scheduling with nominal forecasts, fixed uncertainty margins, adaptive margins, and separate channel, arrival and harvest ablations.
- Matched comparisons with greedy scheduling and, in the solar-source evaluation, fixed-power and channel-aware heuristics. An adapted fixed-fraction baseline is included in the earlier proposal study.
- Two synthetic channel/harvest sweeps with ten paired seeds per condition; additional comparisons on ten windows from each of three solar-data sources; and a full-horizon clairvoyant reference.
- A CLARABEL-versus-SCS comparison on six optimization instances, unit tests, and audits of the saved physical actions and offline plans. The audits check stated conditions; they do not prove global online optimality or guaranteed uncertainty coverage.

The experiment results and diagnostic outputs are under [`results/final_evaluation`](results/final_evaluation). The [full technical handoff](FINAL_HANDOFF.md) documents the assumptions, evaluation settings and limitations in more detail.

### Current finding

The uncertainty-aware approach improves the proposal's weighted cost in some tested conditions but not all. For example, on a mean-normalized synthetic scenario with scarce harvest, adaptive harvest margins reduced average cost against nominal MPC; in a higher-harvest scenario they increased it. Solar-source results also vary, and the 10 windows per source can be correlated. **The results do not support saying that our method is better than every baseline or in every scenario.**

The final analysis should explain when uncertainty margins help and when conservatism can hurt. Consider queue occupancy, rejected arrivals, transmission energy, throughput and final backlog together. Report measured differences and their uncertainty without treating a small number of runs as a universal guarantee.

## Argha: tasks remaining under the proposal

1. **Review the full formulation and implementation with Protyay.** Check the variables, weighted objective, Shannon-rate constraint, energy causality, queue and battery dynamics, terminal constraints, and why the resulting finite-horizon model is convex. Be prepared to explain the receding-horizon decisions and the uncertainty-aware extension in the presentation and Q&A.
2. **Validate the simulation and results.** Review the saved solver statuses, feasibility residuals, CLARABEL/SCS comparison, physical-state audits and offline-reference audit. Confirm that the nominal, fixed-margin and adaptive comparisons use matched traces and that conclusions reflect the recorded evidence. Investigate numerical warnings rather than suppressing them.
3. **Resolve the model assumptions before finalizing the report.** The optimizer can plan rejection while the physical simulator rejects only actual forced overflow. The optional first-slot consistency constraint is an experiment, not a proven performance improvement. The final evaluation clips Poisson arrivals to the proposal's 0–10 range; older results do not. Packet quantities are continuous equivalents. If the report claims packet waiting time, implement and verify packet-age tracking; otherwise report average queue occupancy.
4. **Review the real-data scenarios and their physical interpretation.** ARCO panel current, UMass household panel current and NREL TMY3 irradiance are used as solar-shaped inputs with **assumed**, uncalibrated conversions to harvested energy. Their slot lengths differ, and channel and traffic are synthetic. Verify the dataset provenance and hashes, describe the conversions and timing clearly, and avoid interpreting these as three directly measured IoT harvesting systems. Add a conversion or operating-condition sensitivity check if the professor expects stronger physical validation.
5. **Interpret the baselines and uncertainty-aware extension.** Distinguish nominal, fixed-margin and adaptive MPC; explain the one-step error margins, warm-up period and empirical coverage. Identify which margins help or hurt and why. The full-horizon reference has perfect future information and can proactively reject, so it is a more permissive numerical reference—not a deployable method or a certified numerical lower bound.
6. **Choose the final evidence and figures.** Select two to four clear figures or tables showing the main question, performance trade-offs, empirical forecast-bound behavior and numerical correctness. Use the saved sample sizes and paired comparisons, label units and different slot lengths, and make clear that correlated solar windows limit statistical interpretation. A starting set is linked below.
7. **Finish the course deliverables with Protyay.** Prepare the final technical report and presentation, including the system model, methodology, evidence, limitations, references and each team member's actual contribution. Review the professor's requirements, any permitted-tool disclosure, and citation obligations. Both team members must be ready to explain the entire project, not only their individual component.

## Suggested evidence to review

- [Mean-normalized synthetic comparison](results/final_evaluation/sweep_normalized/realized_cost.png) and [rejection comparison](results/final_evaluation/sweep_normalized/drop_ratio.png).
- [Empirical one-step uncertainty-bound coverage](results/final_evaluation/figures/one_step_coverage.png).
- [Paired solar-source cost differences](results/final_evaluation/figures/solar_paired_cost.png).
- [Solver comparison](results/final_evaluation/solver/solver_comparison.csv), [solar results](results/final_evaluation/solar/per_window.csv), and [clairvoyant-reference audit](results/final_evaluation/offline/audit.json).
- [Dataset provenance and attribution](data/arco/README.md), [UMass](data/umass/README.md), and [NREL](data/nrel/README.md). Raw datasets are not included; the recorded checksums are in the relevant experiment settings.

**Current scope:** The evaluation and your uncertainty-aware contribution are ready for handoff. The final report, presentation, joint review and any necessary final validation remain team tasks. The instructor's project brief is not included in this repository; follow its rules on permission, citations and tool disclosure.
