# EE 541 project handoff: prediction-aware packet scheduling

**For Arghadeep Saha and Protyay Dey.** This is a research prototype and a documented starting point for the final simulations, report, and presentation. The working directory is the directory containing this README. Python 3.11 and the CVXPY backend were used on macOS.

## Start here

```bash
conda activate ee541                 # or create a fresh Python 3.11 environment
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python uncertainty_study.py --backend cvxpy --seeds 2 --seed-start 400 --slots 20 --horizon 5 --out results/my_smoke
```

All commands should be run from this project directory. Output directories are created automatically; **use a new `--out` path for each run** because identically named output files are overwritten. Do not use `run_all.py --clean` unless you deliberately want to delete the entire results directory. `results/handoff_environment.txt` records the environment used for the checks; the requirements file specifies minimum versions rather than a lockfile.

## Model and methods

A single energy-harvesting transmitter serves a finite buffer using continuous packet equivalents. Service happens before arrivals; harvested energy becomes available next slot. The current channel and state are observed before transmission. The CVXPY model minimizes predicted drops in stage 1 and then backlog plus energy and terminal backlog in stage 2, subject to a small stage-1 rejection budget. Only the first action is used, then the system replans. The exact details and `epsilon=0.01` are in `reliability_study.py`.

`uncertainty_study.py` compares EMA nominal, AR nominal, AR calibrated, and gated AR calibrated on identical seeded traces. AR calibrated uses past forecast errors to adjust future channel, arrival, and harvest forecasts conservatively. It is a heuristic; the name calibrated does not imply verified statistical coverage or a formal robust-control guarantee. `uncertainty_stress.py` compares AR nominal and AR calibrated over a 3-by-3 traffic/harvest grid.

The simulator uses Poisson arrivals, which are not bounded by 10 as written in the submitted proposal; `D_max=10` limits service per slot. Decide with the team whether to change the distribution or document this deviation. Queue occupancy is not measured packet waiting time. All rates are fluid packet equivalents; this is not an integer-packet scheduler.

## Existing results and how to reproduce

Two original uncertainty runs: 10 seeds, 120 slots, horizon 10, with seeds 100–109 and 200–209. In the scarce scenario mean rejection was 18.44% versus 17.59%, and 18.47% versus 17.74%, for AR nominal versus AR calibrated respectively. In moderate conditions both had zero observed rejection. These are synthetic, preliminary results; see per-seed data and paired intervals. The original results were generated before the verifier explicitly checked planned power and service caps. Both were subsequently reproduced with the expanded checks in `results/handoff_repro_100` and `results/handoff_repro_200`; those folders include logs and paired Student-t intervals against AR and EMA nominal. The first rerun recorded two stage-2 fallbacks, and the second recorded none.

```bash
python uncertainty_study.py --backend cvxpy --seeds 10 --seed-start 100 --slots 120 --horizon 10 --out results/repro_100
python uncertainty_study.py --backend cvxpy --seeds 10 --seed-start 200 --slots 120 --horizon 10 --out results/repro_200
python paired_uncertainty.py results/repro_100
python paired_uncertainty.py results/repro_200
python uncertainty_stress.py --seeds 5 --seed-start 300 --slots 80 --horizon 10 --out results/repro_stress
```

Each uncertainty run writes per-slot and per-seed CSVs, a summary, paired comparisons, plots, and partial CSVs during execution. The original paired file uses a normal approximation and compares against EMA nominal; `paired_uncertainty.py` produces `paired_t_intervals.csv` against both AR and EMA nominal with Student-t intervals. `compare_uncertainty.py` is a fixed-settings helper for the original seeds 100–109 and writes matched heuristic comparisons into `results/uncertainty_checked`; do not use it for other settings without modifying it. `uncertainty_stress.py` writes paired Student-t intervals against AR nominal; with five seeds they are exploratory.

The solver accepts plans only within a maximum checked primal violation of `1e-4`. If the second stage cannot pass, a separately checked first-stage plan is used and `stage2_fallback` is saved, but that slot has not completed the cost-refinement stage. `optimal_inaccurate` is not a certificate of optimality. Review fallback counts, statuses, residuals and log warnings; do not silently discard or relabel failed runs. A failure in stage 1 still stops a run. Output is written incrementally per completed trajectory, not per slot.

The exploratory stress grid (`results/uncertainty_stress`) completed 9 traffic/harvest combinations with 5 seeds and 80 slots each. It had zero recorded fallbacks and a maximum checked residual of 2.41e-5. Its rejection differences have intervals spanning zero or are identically zero, so it does not establish a consistent rejection benefit across the grid.

The older `results/reliability_first` study is useful background but predates the latest verifier and fallback instrumentation. `run_experiments.py` and the old forecast-noise study use forecasts perturbed from future realizations, so they are oracle-assisted diagnostics; do not present them as causal forecasts or mix them with the causal ablation as though information access were identical. The older research evaluation executes only overflow rejection even though its optimization may plan proactive rejection. These differences must be disclosed when comparing results.

## Argha: final work checklist

1. **Reproduce and audit.** Run the tests and the two full uncertainty commands above on the final chosen environment. Review every fallback, inaccurate status, cap and physical residual; investigate any solver failures. Add tests for edge cases and saved failed cases. Record code revision, versions, seeds, settings and wall-clock time for each final run.
2. **Finish fair comparisons.** Evaluate fixed-power, greedy, channel-aware, nominal MPC, the calibrated method, and any other proposed algorithms on the same causal traces, initial states, execution rules and seed sets. Include the offline clairvoyant benchmark promised in the proposal, with the same physical constraints and a clearly stated objective; its future information makes it a reference, not a deployable policy.
3. **Broaden experiments.** Extend the exploratory stress grid to more independent seeds, longer traces, varying horizon and forecast error, nonstationary and alternative channel/energy processes. Keep tuning seeds separate from final evaluation seeds. Quantify uncertainty with paired seed-level intervals, show variability, and report when a method loses as well as when it wins.
4. **Check the model against the proposal.** Resolve Poisson arrival support, record the active and full slot durations and units, verify arrival/harvest timing and terminal states, and distinguish forced overflow from planned proactive rejection. Add actual packet-age tracking if reporting waiting time; otherwise label the metric average queue occupancy. Verify end-of-run backlog and explain throughput tradeoffs.
5. **Assess robustness and novelty.** Evaluate forecast errors and empirical coverage by horizon and scenario, check whether adaptive margins help against AR nominal, and compare with published robust/prediction-aware MPC methods. Do not claim formal coverage, universal superiority, or conference novelty without evidence. Compare an out-of-sample ablation and cost/benefit of gated control.
6. **Prepare final deliverables.** Produce readable plots with units, sample sizes, error bars and captions; include solver runtime and feasibility. Save raw data, settings, logs, scripts and environment. Write the mathematical formulation, convexity argument, method, experimental protocol, results and limitations; assemble the final report and presentation together with Protyay.

The earlier `README.md` and `README_FINAL.md` document the prototype and legacy runner; where those differ, follow this handoff and inspect the current code. Never claim that horizon-sensitivity plots are solver convergence proofs.
