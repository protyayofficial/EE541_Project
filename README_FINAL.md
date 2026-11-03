# EE541 final reproducible runner

Activate your existing conda environment (`conda activate ee541`), install `python -m pip install -r requirements.txt`, and execute from the extracted project folder:

```bash
python run_all.py --mode smoke --clean
python run_all.py --mode full --clean
```

The second command removes the earlier smoke results and starts the full study from scratch. **For a quick verification first**, run `python run_all.py --mode full --clean --seeds 2 --slots 30` before full scale. Every stage writes a log under `results/<study>/run.log`; all plots and CSVs are saved in corresponding study directories. The runner creates `EE541_results_for_review.zip` even if a stage fails; upload that results archive for diagnosis.

**Caution:** `--clean` deletes the entire generated results directory, so omit it when preserving earlier runs. The source code is never deleted.

`CVXPY` solves the exponential-cone formulation; fallback between CLARABEL and SCS is validated against primal constraint residuals (1e-4 default acceptance). An `optimal_inaccurate` result is tracked and is not proof of optimality. The solver accuracy script reports unavailable references rather than fabricating convergence comparisons.

**Research limitations:** Forecast-error sweep intentionally uses future-perturbed signals (oracle-assisted diagnostic). Other studies use causal historical smoothing. The scheduling optimizer may plan rejection but the evaluation disables proactive dropping. The adaptive queue-aware method is heuristic, not proven novel. Average backlog is not measured packet waiting time. An offline clairvoyant benchmark is not implemented. Do not claim otherwise in the course report.
