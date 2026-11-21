# Production solver recovery — 20 November 2026

The first production attempt,
`results/final_evaluation_continuous_1000_20261120T070447Z_683358_4af923`,
failed during stage 05. It remains preserved, including its FAILED/status records,
logs, 119 completed sweep checkpoints, packet table and pending stages. The
300-run sweep is incomplete: no final per-seed/per-slot table or sweep audit was
produced. The failed policy-run itself was not checkpointed. Do not merge these
partial results into the fresh restart or interpret them as a completed study.

## Reproduction and diagnosis

Before editing solver logic, the original/non-normalized scenario was rerun with
harvest mean 0.6, sigma 0.8, rho 0.68, seed 5003, adaptive_all, 1,000 slots and
horizon 10. The failure reproduced exactly at **zero-based slot 171** (interval
starting at virtual time 855 s): queue 32, battery 2.156548932564143 J. Full
optimization inputs, configuration, histories and exception are saved in
`results/recovery_20261120/failing_instance.json`. The small regression fixture is
`tests/fixtures/cvxpy_slot171_original_5003.json`.

CLARABEL stopped with `InsufficientProgress`. SCS's nominally optimal candidate
violated the original rate constraint by 0.000198938983 packets; its later
inaccurate candidate violated it by 0.00684219463. Both were correctly rejected
by the unchanged 1e-4 physical residual threshold.

The problem is feasible, not a shortage of admissible queue/battery actions.
A constructive witness sets all attempted service and data power to zero, rejects
all forecast arrivals, keeps queue 32, pays the mandatory first control exchange,
and disables relaxed future control activity. Forecast harvest keeps its battery
within [0,12]. Independent `verify_plan` residuals are zero (floating tolerance
below 1e-12). The witness is diagnostic, not a substitute execution policy.

The failure is numerical conic convergence/dual scaling with large linear cost
coefficients, not a change needed to the physical formulation. Controlled trials
on identical inputs showed that rewriting only the rate constraint did not fix
the rejection. Positive constant objective normalization returned an optimal
CLARABEL solution with residual 8.05e-9 and original-unit objective approximately
2152.96053. These trials and the original verbose solver log are saved separately.

## Correction and verification

CVXPY minimizes `C / max(1, drop_weight, energy_weight, terminal_weight)`, where
`C` is the unchanged configured objective. This positive constant leaves every
constraint and the mathematical minimizers unchanged. Returned objectives remain
`C` in original model units. No feasibility threshold, channel distribution,
weight ratio, policy, radio rule or experiment setting was changed. There is no
heuristic fallback and no resume system.

The captured instance is a regression check of feasibility, CLARABEL convergence,
strict residuals and original-unit objective reporting. The entire formerly
failing 1,000-slot run passed: 999 optimal solves, one inactive interval, maximum
residual 7.79574e-6, and zero solver/decision-budget overruns. Packet/battery,
aggregate and independent delay-ledger/output audits passed. Execution took
10.2691 s, averaging 9.7963 ms solver time per slot on this host.

The complete suite passed **102 tests in 72.672 seconds**. All **40 active Python
files** parsed. A 21-stage short real-input launcher workflow passed with the
correction. Tests also verify competing production launches are refused and
failure status/partial preservation remain intact.

The launcher accepts `--readiness-record` so the prior passed readiness evidence
can remain unchanged. The new explicit approval is
`results/recovery_20261120/readiness.json`; it records the changed source hashes,
the prior approval's hash, captured regression and full verification. A cross-
process file lock and existing-running-status check prevent duplicate launches.
The launcher freezes the approval's hash as well as source/input hashes throughout
execution. Changing code during the production run is not allowed.

## Provenance and restart

`results/recovery_20261120/` contains:

- `original_manifest.json`: hashes/sizes of every file in the failed directory.
- `before/`: the original scheduler, policy driver, experiment and launcher;
  hashes were checked against the failed batch's own preflight record.
- `failing_instance.json`, `feasible_witness.json`, `solver_variants.json`,
  original CLARABEL log, regression log and full test log.
- `verified_case/`: the corrected 1,000-slot slot/packet/run outputs and audit
  verification; `INCOMPLETE_ORIGINAL_BATCH.json` marks the earlier sweep's scope.
- `restart_source/`: corrected active source, launcher and regression fixture.
- `readiness.json`, `launcher_smoke.log` and `launcher_guards.log`.
- `production_launch.json` / `production_launcher.log`: fresh authorized restart
  identity and progress. Completion must be checked against its completion audit,
  `status.json` and `COMPLETED` marker, not inferred from launch or solver success.

Restart command (authorized in the recovery request):

```bash
scripts/run_experiments.sh --run --readiness-record results/recovery_20261120/readiness.json
```

Every study starts in a fresh timestamped output root. The 900 main runs, two
120-run supplements, 90 references and 12 solver checks are unchanged. The
recovery is not complete until the new production completion audit passes.

## Verified production completion

The authorized restart completed independently of chat monitoring at
**2026-11-20 11:09:39 UTC**, with launcher exit code 0. It ran from 07:53:29 UTC
for 3 h 16 min 10 s. All 21 stages, including the final completion audit, passed.
The production root is
`results/final_evaluation_continuous_1000_20261120T075329Z_4_f31b28/`;
the launcher log remains `results/recovery_20261120/production_launcher.log`.
PID 4 was namespace-local, not a host PID. The original execution session has
returned exit 0 and the cross-process lock is free. No further launch is needed.

On 20 November at approximately 14:47 UTC, completed files were reconciled again:

| Group | Verified executions | Verified online slot records |
|---|---:|---:|
| Original synthetic | 300 | 300,000 |
| Normalized synthetic | 300 | 300,000 |
| Solar | 300 | 300,000 |
| Delay–energy | 120 | 120,000 |
| Forecast sensitivity | 120 | 120,000 |
| Offline references | 90 | Not online packet episodes |
| Short solver checks | 12 | Separate ten-slot instances |

Every online run has exactly one record for each slot 0–999, matched to its run
ID, with horizon 10 in saved settings. All eight study/source/reference/solver
audit JSONs report success; the completion audit log reports PASS. All 20 PNG
figures and required run-level, paired, forecast and packet outputs exist.
There were zero accepted inaccurate online solves and zero online solver or
decision-budget overruns. Maximum online planned residual was 9.71814e-5,
within the unchanged 1e-4 threshold. Intermediate solver-accuracy warnings remain
in the logs; they were not suppressed or treated as evidence of optimality.

`results/recovery_20261120/completion_verification.json` records these checks,
the per-study residuals/counts, audit contents, unchanged source/input hashes and
the original failed-directory manifest recheck. The original failed directory
still matches its pre-recovery file hashes and is not included in the completed
batch. Earlier readiness files, diagnostics and source snapshots were preserved.
Adaptive forecast margins remain included; adaptive penalty updates are excluded.
