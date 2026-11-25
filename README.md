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
and 12 solver checks. To build the report figures and tables from a completed
full run, replace the input path with the directory printed by the launcher:

```bash
python prepare_report_figures.py \
  --input runs/COMPLETED_RUN_DIRECTORY \
  --out runs/report_figures \
  --zip runs/report_figures.zip
```

## Included results

| Output | Contents |
| --- | --- |
| [Current-model verification](results/submission_verification) | Saved summaries, figures, settings and audit results from the merged implementation |
| [Earlier evaluation](results/final_evaluation) | Synthetic and solar comparisons, offline reference and solver checks from the earlier simulator |
| [Development studies](results) | Earlier proposal runs and exploratory policy tuning under their original settings |

The included current-model verification covers the short workflow and a
two-seed, 1,000-slot normalized synthetic comparison at channel volatility
`sigma = 0.45`. The original November 20 production output files described in
the branch history were absent from the GitHub branches. A new full run
produces the complete set of outputs for the current model.

In the included 1,000-slot check, the policy with adaptive margins on all
forecasts lowered mean weighted cost by 4.2% relative to nominal MPC at 0.6 J
mean harvest. At 1.2 J, its cost was 0.5% higher. Each comparison uses two
matched seeds, so these differences describe the included runs.

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
