# Solver scaling and regression check

## Reproduction and diagnosis

Before editing solver logic, the original/non-normalized scenario was rerun with
harvest mean 0.6, sigma 0.8, rho 0.68, seed 5003, adaptive_all, 1,000 slots and
horizon 10. The failure reproduced exactly at **zero-based slot 171** (interval
starting at virtual time 855 s): queue 32, battery 2.156548932564143 J. The [regression fixture](../tests/fixtures/cvxpy_slot171_original_5003.json)
captures the optimization inputs and configuration.

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
2152.96053.

## Correction and verification

CVXPY minimizes `C / max(1, drop_weight, energy_weight, terminal_weight)`, where
`C` is the unchanged configured objective. This positive constant leaves every
constraint and the mathematical minimizers unchanged. Returned objectives remain
`C` in original model units. No feasibility threshold, channel distribution,
weight ratio, policy, radio rule or experiment setting was changed. There is no
heuristic fallback and no resume system.

Run the regression check from the activated environment:

```bash
python -m unittest discover -s tests -p 'test_solver_recovery.py' -v
```
