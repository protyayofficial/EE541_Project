> **Current handoff:** Start with [README_HANDOFF.md](README_HANDOFF.md) for the latest validated workflow, results, and Argha’s checklist.

# EE 541: Prediction-Aware Robust Convex Scheduling

**Protyay Dey & Arghadeep Saha — research prototype, not final numerical results.**

## Setup (local machine)
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
python -m unittest discover -s tests -v
python run_experiments.py --slots 160 --backend cvxpy
```

For a dependency-light demonstration, `--backend lp` uses SciPy HiGHS, a **conservative piecewise-linear inner approximation** of Shannon capacity (12 segments), not the exact CVXPY solution. The LP can be run with `python run_experiments.py --slots 160 --backend lp` and is still feasible for the physical logarithmic rate constraint. Do not relabel LP results as CVXPY experiments.

## System and timing
- Slot length Delta = 5 s; active duration tau = 1 s.
- At time t, observe actual channel and current buffer and battery, plan over a horizon, apply first action. Only beginning-of-slot backlog may be served.
- Arrivals and harvest occur at end of slot. Rejected new arrivals may be proactive or forced overflow. Harvest is usable in the next slot.
- Gain in the code is **effective gain** `g=h/(N0*B)` (SNR/W); physical h can be recovered with `h=g*N0*B`. Capacity in packet equivalents is `(B*tau/L)*log2(1+g*p)`.
- Initial battery and backlog: 7 J and 12 packet equivalents. Cap 12 J, buffer 32, max power 3 W, max packets/slot 10.
- The proposal uses *linear* rejection penalty `eta*o`, not quadratic.

## Controller arms
- `fixed`: equal 1.2 W when energy permits
- `greedy`: use maximum feasible power and clear available backlog
- `channel`: 2.4 W in good state and 0.45 W otherwise (battery limits apply)
- `nominal`: unmodified predicted arrivals, gains, harvest
- `robust`: fixed additive channel margin 0.38 (effective gain), arrival upper margin 1 packet, harvest lower margin 0.25 J
- `adaptive`: online rolling 80th-percentile *one-step forecast error* margins for channel overprediction, arrival underprediction and harvest overprediction; uses warm-up fixed margins. This is an **adaptive heuristic candidate**, not certified calibration or established research novelty.

## Novelty/technical ownership
Protyay: prediction uncertainty, conservative and adaptive margins, mathematical tests, robustness-vs-efficiency analysis. Arghadeep: simulator, wireless model refinements, baseline fairness, scenarios and final visualizations. Both should inspect and own all code/results before submission.

Current adaptive method is a starting algorithmic hypothesis. A robust conference-level contribution would require rigorous novelty comparison to related literature, calibration/robustness theory, and multi-seed studies on nonstationary traces. Do not claim formal uncertainty coverage or general online optimality from this implementation.

## Important limits
1. The synthetic *forecast generator perturbs actual future observations* solely to control error magnitude. This is an **oracle-aided synthetic benchmark**, not a deployment-ready forecasting model. Replace it with a **causal** predictor trained only on past data before treating outcomes as realistic.
2. The robust controller protects the **predicted optimization model**, not every possible real-world trajectory. It is not a full multistage min-max robust MPC policy.
3. Observed channel is known at decision time. Current arrivals and harvested energy are not known. The first-stage planned rejection is capped by actual arrival on execution. All policies execute through the identical physical simulator.
4. For the EE 541 project, add multiple seeds, meaningful traffic/harvest regimes, forecast degradation, exact CVXPY checks, and runtime and constraint audits. Compare average and spread, not only one representative trace.
5. `average_queue` is NOT equivalent to per-delivered-packet delay when rejection is allowed. Accurate waiting-time computation requires packet age tracking or a careful Little's-law treatment.
6. Low-influence numerical clipping is included after optimization to handle tolerances; log any clipping events when doing the final correctness study.

## Files
- `src/scheduling.py`: exact CVXPY model, LP fallback, feasibility verifier
- `src/experiment.py`: deterministic trace generation, receding-horizon simulation, policies, metrics
- `run_experiments.py`: figures and CSV reports in `results/`
- `tests/test_model.py`: linear-approximation physical feasibility and state tests

## Next experiment matrix
3 arrival rates x 3 harvesting regimes x 3 forecast errors x >=10 seeds. Report mean ± std, feasibility residual, objective components, and solver runtime. A clean ablation compares nominal / fixed robust / adaptive robust on the same trace and same horizon, ideally with a causal autoregressive predictor.

## Research evaluation runner (Nov 2026 update)

Run from the top-level project folder, after installing requirements in the
`ee541` Conda environment. **First validate the exact CVXPY backend locally**:

```bash
conda activate ee541
python -m unittest discover -s tests -v
python research_experiments.py --study multiseed --backend cvxpy --seeds 3 --slots 30 --horizon 5
```

For more demanding experiments, increase one dimension at a time:

```bash
# Paired results, causal forecasts, 10 independent seeds
python research_experiments.py --study multiseed --backend cvxpy --seeds 10 --slots 120 --horizon 10

# Forecast noise sensitivity. Uses an oracle-aided synthetic forecaster ONLY
# for controlled error sweeps. Do not label this a causal predictor.
python research_experiments.py --study forecast --backend cvxpy --seeds 10 --slots 120

# Controller horizon sensitivity (not solver convergence)
python research_experiments.py --study horizon --backend cvxpy --seeds 8 --slots 120

# One-shot horizon, solver runtime, and primal feasibility diagnostics
python research_experiments.py --study diagnostics --backend cvxpy --seeds 2 --slots 20

# Actual numerical solver accuracy/tolerance plots
python solver_accuracy.py --horizon 12
```

Outputs appear in `results/research`. CSV includes per-seed metrics, means,
standard deviations and paired approximate 95% intervals (differences vs
nominal on identical seeds). Bars represent normal-approximation **intervals
for means**, not theoretical guarantees; do not interpret overlap as proof.

Method `adaptive_risk` is an exploratory **queue-pressure-aware uncertainty
margin**: it reduces its rolling quantile safety margin as the buffer fills.
This is an engineering heuristic, not demonstrated conference novelty.
All research-runner comparisons disable proactive dropping during execution,
so recorded drops are capacity-forced; the optimizer may still plan rejection
internally. This is an evaluation policy mismatch that needs to be reported,
not concealed. The original baseline runner remains unchanged by default.

The causal predictor uses an exponential moving average of **past** channel,
arrival, and harvest values, although the controller observes the current
channel before selecting transmission power. This is a simple benchmark,
not a calibrated predictive model.

**Important validity caveat:** `solver_accuracy.py` reports SCS numerical
accuracy against a CLARABEL reference, and `horizon` tests controller horizon
sensitivity. Neither establishes a new regret or online convergence theorem.
Avoid calling these the same thing. Check solver residuals, seed variability,
and whether improvements survive congestion and energy scarcity.

For a complete final project, still add a carefully justified offline oracle,
explicit traffic/harvest stress tests, terminal energy value sensitivity,
measured packet delay (with packet age tracking), and rigorous comparison
against prior robust MPC methods. This package cannot guarantee full marks.

```bash
# 3 traffic loads × 3 harvest regimes × seeds × 4 controllers
python research_experiments.py --study stress --backend cvxpy --seeds 10 --slots 120
```
The stress study generates mean-queue and rejection figures with error bars
for each traffic/harvest regime. Use a small smoke test first:
`python research_experiments.py --study stress --backend lp --seeds 2 --slots 20 --horizon 5`.
