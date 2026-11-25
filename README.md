# Prediction-Aware Packet Scheduling for Energy-Harvesting Sensors

**EE 541 · University at Buffalo · Fall 2026**

**Protyay Dey and Arghadeep Saha**

Can forecast uncertainty margins help an energy-harvesting wireless sensor
reduce packet rejection and queue buildup without using more transmission
energy? We compare receding-horizon convex scheduling policies and simple
heuristics on matched synthetic and solar-driven scenarios.

At each interval, the scheduler uses the current queue, battery and any
available channel probe to plan over a ten-slot horizon. The CVXPY model balances
queue occupancy, rejected arrivals, energy use and terminal backlog. It plans
with expected goodput, then executes the first action in a packet simulator
with whole-packet transmissions, reception errors, acknowledgments and retries.
The uncertainty-aware policies adjust channel, arrival or harvest forecasts
with fixed or adaptive margins.

## Set up with Conda

On macOS or Linux, install [Miniconda](https://www.anaconda.com/docs/getting-started/miniconda/main)
or [Miniforge](https://github.com/conda-forge/miniforge), then run:

```bash
git clone --branch master https://github.com/protyayofficial/EE541_Project.git
cd EE541_Project
conda env create -f environment.yml
conda activate ee541
```

The environment uses Python 3.11 and pins NumPy, SciPy, pandas, Matplotlib,
CVXPY, CLARABEL and SCS. Run the following commands from the repository root.
All three input files are under [`data/`](data), with source attribution and
SHA-256 checksums.

## Reproduce the experiments

Start with the unit tests and a short run through the full workflow:

```bash
python -m unittest discover -s tests -v
bash scripts/run_experiments.sh --run --smoke --output-parent runs
```

The smoke run uses four slots per episode and exercises both synthetic sweeps,
all three solar sources, both supplementary studies, the offline reference,
the solver comparison, and the corresponding audits. It is a workflow check.
Use the full run below for the ten-seed and ten-window comparisons.

```bash
# Inspect the full plan and verify the input checksums and window selections.
bash scripts/run_experiments.sh --plan-only

# Run the full study. Allow several hours and multiple GB of disk space.
bash scripts/run_experiments.sh --run --output-parent runs
```

The launcher prints the output directory. In it, `status.json` and `logs/`
record stage progress, and `COMPLETED` marks a run that passed the final audit.
Each invocation creates a new directory. Run `python final_evaluation.py --help`
or `python final_solar_evaluation.py --help` for individual study options.

The full design uses 1,000-slot episodes. It includes two 300-run synthetic
sweeps, 300 solar runs, 120 runs per supplementary study, 90 offline references,
and 12 solver checks.

### Regenerate the report figures

Use the bundled analysis inputs to rebuild the published figures and tables
without rerunning the simulations:

```bash
python prepare_report_figures.py \
  --input report_results/production \
  --out runs/report_figures \
  --zip runs/report_figures.zip
```

To plot a new full experiment, use its completed run directory as `--input`.

## Included results

| Output | Contents |
| --- | --- |
| [Production results](report_results/production) | Run matrices, settings, metrics, paired comparison tables, solver checks and audits |
| [Report figures](report_results#figures) | Five figures covering the main comparisons and sensitivity analyses |
| [Completion record](report_results/completion_verification.json) | Run counts, residuals and audit scope |

In the normalized synthetic sweep, adaptive margins on all forecasts lowered
weighted cost relative to nominal MPC at 0.6 J mean harvest and channel
volatilities 0.45 and 0.80. At 1.2 J and volatility 0.80, the same policy
increased cost. Each comparison uses ten matched seeds. See the
[synthetic cost and rejection figure](report_results/report_figures/main/01_normalized_cost_rejection.pdf)
and the [paired comparison table](report_results/production/sweep_normalized/paired_vs_nominal.csv).

A full run also generates per-slot and per-packet ledgers and offline plans.
The offline reference uses perfect future inputs and continuous expected
goodput. Its difference from realized online cost is descriptive.

## Model and data notes

- The current simulator uses correlated lognormal channel gains, uniform
  arrivals from 0 to 10 packets, a 32-packet buffer, and up to five transmission
  attempts per slot. The supplementary studies vary the energy penalty
  or channel forecast noise across runs.
- ARCO and UMass provide solar-panel current at one-minute resolution after
  aggregation. NREL provides hourly TMY3 irradiance. Each is converted to
  simulated harvest with an assumed scale. Channel and traffic inputs are
  synthetic. Solar windows can share observations, and throughput comparisons
  need to account for the different slot durations.
- Review queue, rejection, energy and delay together when interpreting policy
  comparisons. Packet delay statistics use completed observations and report
  the associated cohort counts. Empirical margin coverage is scenario-specific.
