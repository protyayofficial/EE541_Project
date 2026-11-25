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
Each invocation creates a new directory. The [experiment protocol](docs/experiments_1000.md)
describes the study design. Run `python final_evaluation.py --help` or
`python final_solar_evaluation.py --help` for individual study options.

The full design uses 1,000-slot episodes. It includes two 300-run synthetic
sweeps, 300 solar runs, 120 runs per supplementary study, 90 offline references,
and 12 solver checks.

### Regenerate the report figures

Use the bundled analysis inputs to rebuild the published figures and tables
without rerunning the simulations:

```bash
python prepare_report_figures.py \
  --input report_results/report_figures/inputs \
  --out runs/report_figures \
  --zip runs/report_figures.zip
```

To plot a new full experiment, use its completed run directory as `--input`.

## Included results

| Output | Contents |
| --- | --- |
| [Production results](report_results) | Run matrices, settings, tables, audit records and plots for the 1,000-slot experiment design |
| [Report figures and tables](report_results/report_figures/INDEX.md) | PDF and PNG figures, captions, plotted data and analysis tables |
| [Verification runs](results/submission_verification) | Audited short workflow and a separate two-seed, 1,000-slot comparison |
| [Earlier evaluation](results/final_evaluation) | Saved comparisons from the earlier simulator |

In the normalized synthetic sweep, adaptive margins on all forecasts lowered
weighted cost relative to nominal MPC in the 0.6 J harvest regime at channel
volatilities 0.45 and 0.80. At 1.2 J and volatility 0.80, the same policy
increased cost. Each comparison uses ten matched seeds. See the
[synthetic comparisons](report_results/report_figures/main/01_normalized_cost_rejection.pdf)
and the [results notes](report_results/report_figures/FINDINGS.md) for
differences, paired intervals and interpretation.

The submitted production results include the saved run-level data. The full
launcher additionally generates per-slot and per-packet records and offline
plans, which are much larger. The verification runs include their raw records
for auditing examples.

A generated study directory contains `settings.json`, a run matrix,
`per_seed.csv` or `per_window.csv`, aggregate and paired comparison tables, and
plots. Full runs also save per-slot and per-packet records for auditing. The
offline reference uses perfect future inputs and continuous expected goodput.
Its cost comparison with realized online execution is descriptive.

## Model and data notes

- The current simulator uses correlated lognormal channel gains, uniform
  arrivals from 0 to 10 packets, a 32-packet buffer, and up to five transmission
  attempts per slot. The [proposal](docs/submitted_proposal.tex) records the
  original assumptions and division of work. The supplementary studies use
  fixed penalty weights and vary the energy penalty or forecast noise.
- ARCO and UMass provide solar-panel current at one-minute resolution after
  aggregation. NREL provides hourly TMY3 irradiance. Each is converted to
  simulated harvest with an assumed scale. Channel and traffic inputs are
  synthetic. Solar windows can share observations, and throughput comparisons
  need to account for the different slot durations.
- Review queue, rejection, energy and delay together when interpreting policy
  comparisons. Packet delay statistics use completed observations and report
  the associated cohort counts. Empirical margin coverage is scenario-specific.

Further details appear in the [radio model](docs/receiver_feedback.md),
[packet-delay definitions](docs/packet_delays.md),
[supplementary studies](docs/supplementary_studies.md) and
[solver regression notes](docs/solver_recovery.md).
