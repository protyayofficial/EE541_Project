"""Focused EE541 study: lexicographic reliability-first convex MPC.

Runs alongside the existing project, without editing any legacy files.
The stage-1 guarantee concerns PLANNED rejection under fixed forecasts,
not realized drop rates or global online optimality.
"""
import argparse
import json
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from src.scheduling import Config, capacity, verify_plan
from src.experiment import make_trace, run_policy, summarize
from research_experiments import causal_forecasts

METHODS = ("nominal", "adaptive_risk", "lex_nominal", "lex_adaptive")


def solve_lex(b0, e0, gain, arrivals, harvest, cfg, epsilon=1e-2):
    """Two sequential convex programs: lowest forecast drops, then lowest cost.

    Both phases have the same feasible set. A conservative uncertainty forecast
    is supplied by the caller. The second phase uses the first phase's achieved
    feasible rejection (not just its potentially inaccurate objective value).
    """
    import cvxpy as cp

    g = np.asarray(gain, float)
    l = np.asarray(arrivals, float)
    H = np.asarray(harvest, float)
    n = len(g)
    p = cp.Variable(n, nonneg=True)
    d = cp.Variable(n, nonneg=True)
    b = cp.Variable(n + 1)
    E = cp.Variable(n + 1)
    o = cp.Variable(n, nonneg=True)
    w = cp.Variable(n, nonneg=True)
    constraints = [
        b[0] == b0, E[0] == e0,
        b >= 0, b <= cfg.buffer_max,
        E >= 0, E <= cfg.energy_max,
        p <= cfg.power_max, d <= cfg.data_max,
        d <= b[:-1], o <= l,
        p * cfg.tau <= E[:-1],
        b[1:] == b[:-1] - d + l - o,
        E[1:] == E[:-1] - p * cfg.tau + H - w,
        d <= cfg.rate_scale * cp.log1p(cp.multiply(g, p)) / np.log(2),
    ]
    variables = {"p": p, "d": d, "b": b, "E": E, "o": o, "w": w}

    def solve_checked(problem, phase, extra_check=None):
        failures = []
        fallback = None
        configs = [
            ("CLARABEL", {"max_iter": 1000, "tol_feas": 1e-8,
                          "tol_gap_abs": 1e-8}),
            ("SCS", {"eps": 1e-5, "max_iters": 30000}),
            ("SCS", {"eps": 1e-7, "max_iters": 100000,
                     "acceleration_lookback": 0}),
        ]
        for solver, opts in configs:
            if solver not in cp.installed_solvers():
                continue
            try:
                problem.solve(solver=solver, verbose=False, **opts)
            except cp.error.SolverError as exc:
                failures.append(f"{solver}: {exc}")
                continue
            if problem.status not in (cp.OPTIMAL, cp.OPTIMAL_INACCURATE):
                failures.append(f"{solver}: status={problem.status}")
                continue
            if any(v.value is None or not np.isfinite(v.value).all()
                   for v in variables.values()):
                failures.append(f"{solver}: missing/nonfinite primal variables")
                continue
            result = {k: np.asarray(v.value, float).copy()
                      for k, v in variables.items()}
            feasibility = max(verify_plan(result, b0, e0, g, l, H, cfg).values())
            extra = 0.0 if extra_check is None else max(0.0, extra_check(result))
            violation = max(feasibility, extra)
            if violation > 1e-4:
                failures.append(f"{solver}: constraint violation={violation:.3g}")
                continue
            result.update(status=str(problem.status), solver=solver,
                          violation=violation)
            if problem.status == cp.OPTIMAL:
                return result
            if fallback is None or violation < fallback["violation"]:
                fallback = result
        if fallback is not None:
            return fallback
        raise RuntimeError(f"{phase} solver failure: {' | '.join(failures)}")

    stage1 = cp.Problem(cp.Minimize(cp.sum(o)), constraints)
    assert stage1.is_dcp()
    first = solve_checked(stage1, "min-rejection")
    d_star = max(0.0, float(np.sum(first["o"])))
    loss_limit = d_star + epsilon

    stage2 = cp.Problem(
        cp.Minimize(cp.sum(b[:-1]) + cfg.energy_weight * cfg.tau * cp.sum(p)
                    + cfg.terminal_weight * b[-1]),
        constraints + [cp.sum(o) <= loss_limit],
    )
    assert stage2.is_dcp()
    try:
        second = solve_checked(
            stage2, "cost-under-reliability-budget",
            extra_check=lambda r: float(np.sum(r["o"]) - loss_limit),
        )
        second["stage2_fallback"] = False
    except RuntimeError as exc:
        # The verified first-stage plan remains physically feasible; preserve it
        # and record the failed cost refinement instead of relaxing tolerances.
        second = first.copy()
        second["stage2_fallback"] = True
        second["stage2_error"] = str(exc)
    second["planned_loss_opt"] = d_star
    second["planned_loss_budget"] = loss_limit
    second["planned_loss"] = float(np.sum(second["o"]))
    second["stage1_status"] = first["status"]
    return second


def run_lex_policy(trace, mode, cfg):
    """Execute power/service; admit arrivals after transmission, reject overflow only.

    The planned loss is forecast slack; actual rejection is post-arrival recourse.
    This avoids deliberately discarding data based on an uncertain forecast.
    """
    b, energy = 12.0, 7.0
    errors = []
    records = []
    for t in range(len(trace["gain"])):
        gain = float(trace["gain"][t])
        arrival = float(trace["arrival"][t])
        harvest = float(trace["harvest"][t])
        horizon = min(cfg.horizon, len(trace["gain"]) - t)
        ghat = np.asarray(trace["forecast_gain"][t, :horizon], float).copy()
        lhat = np.asarray(trace["forecast_arrival"][t, :horizon], float).copy()
        Hhat = np.asarray(trace["forecast_harvest"][t, :horizon], float).copy()

        # Use only errors observed before the current decision.
        if mode == "lex_adaptive":
            if len(errors) >= 8:
                mg, ml, mH = np.quantile(np.asarray(errors[-40:]), .8, axis=0)
            else:
                mg, ml, mH = .38, 1.0, .25
            ghat[1:] = np.maximum(.01, ghat[1:] - mg)
            lhat = np.maximum(0, lhat + ml)
            Hhat = np.maximum(0, Hhat - mH)
        ghat[0] = gain  # observed channel, not oracle future information
        start = time.perf_counter()
        solution = solve_lex(b, energy, ghat, lhat, Hhat, cfg)
        elapsed = time.perf_counter() - start
        power = float(np.clip(solution["p"][0], 0,
                              min(cfg.power_max, energy / cfg.tau)))
        served = max(0.0, min(float(solution["d"][0]), b, cfg.data_max,
                              float(capacity(power, gain, cfg))))
        # Actual post-arrival admission decision: no discretionary rejection.
        rejected = min(arrival, max(0.0, b - served + arrival - cfg.buffer_max))
        new_b = b - served + arrival - rejected
        pre_energy = energy - power * cfg.tau + harvest
        spill = max(0.0, pre_energy - cfg.energy_max)
        new_energy = pre_energy - spill
        if not (-1e-6 <= new_b <= cfg.buffer_max + 1e-6 and
                -1e-6 <= new_energy <= cfg.energy_max + 1e-6):
            raise AssertionError(f"Physical state outside bounds at t={t}")
        records.append(dict(t=t, mode=mode, b=b, E=energy,
                            p=power, d=served, drop=rejected, proactive=0.0,
                            forced_drop=rejected, arrivals=arrival, gain=gain,
                            harvest=harvest, spill=spill,
                            throughput_bps=served * cfg.packet_bits / cfg.slot_seconds,
                            solve_s=elapsed, plan_feas=solution["violation"],
                            solver_status=solution["status"],
                            solver_name=solution["solver"],
                            stage2_fallback=solution["stage2_fallback"],
                            stage2_error=solution.get("stage2_error", ""),
                            planned_loss=solution["planned_loss"],
                            planned_loss_budget=solution["planned_loss_budget"]))
        # The historical predictor is causal: forecast[t,0] is generated
        # using observations before slot t. Evaluate errors after arrivals.
        errors.append((max(0, float(trace["forecast_gain"][t, 0]) - gain),
                       max(0, arrival - float(trace["forecast_arrival"][t, 0])),
                       max(0, float(trace["forecast_harvest"][t, 0]) - harvest)))
        b, energy = new_b, new_energy
    return pd.DataFrame(records)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=3)
    parser.add_argument("--slots", type=int, default=50)
    parser.add_argument("--horizon", type=int, default=10)
    parser.add_argument("--out", default="results/reliability_first")
    args = parser.parse_args()
    if args.seeds < 2 or args.slots < 2 or args.horizon < 1:
        parser.error("Use at least 2 seeds, 2 slots, and horizon >= 1")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cfg = replace(Config(), horizon=args.horizon)
    rows = []
    slot_frames = []
    for scenario, arrival_mean, harvest_mean in [
        ("moderate", 2.5, 1.1), ("scarce", 3.0, 0.6),
    ]:
        for index in range(args.seeds):
            seed = index + 100
            trace = causal_forecasts(
                make_trace(args.slots, seed=seed, arrival_mean=arrival_mean,
                           harvest_mean=harvest_mean),
                max(21, args.horizon),
            )
            for mode in METHODS:
                print(f"scenario={scenario} seed={seed} method={mode}", flush=True)
                if mode.startswith("lex_"):
                    df = run_lex_policy(trace, mode, cfg)
                else:
                    df = run_policy(trace, mode, cfg, backend="cvxpy",
                                    allow_proactive=False)
                row = summarize(df, cfg).iloc[0].to_dict()
                row.update(scenario=scenario, seed=seed,
                           forced_drops=float(df["drop"].sum()),
                           proactive_drops=float(df["proactive"].sum()),
                           total_arrivals=float(df["arrivals"].sum()),
                           stage2_fallbacks=int(df["stage2_fallback"].sum()) if "stage2_fallback" in df else 0)
                rows.append(row)
                df = df.copy()
                df["scenario"] = scenario
                df["seed"] = seed
                slot_frames.append(df)
    raw = pd.DataFrame(rows)
    raw.to_csv(out / "per_seed.csv", index=False)
    pd.concat(slot_frames, ignore_index=True).to_csv(out / "per_slot.csv", index=False)
    summary = raw.groupby(["scenario", "mode"], as_index=False).agg(
        queue_mean=("average_queue", "mean"), queue_sd=("average_queue", "std"),
        drop_mean=("rejection_ratio", "mean"), drop_sd=("rejection_ratio", "std"),
        energy_mean=("energy_J", "mean"),
        throughput_mean=("throughput_bps", "mean"),
        max_feasibility=("max_planned_violation", "max"),
        solve_ms=("mean_solve_ms", "mean"),
        inaccurate_fraction=("inaccurate_fraction", "mean"),
        stage2_fallbacks=("stage2_fallbacks", "sum"),
    )
    summary.to_csv(out / "summary.csv", index=False)
    paired = []
    for scenario, group in raw.groupby("scenario"):
        base = group[group["mode"] == "nominal"].set_index("seed")
        for mode in METHODS[1:]:
            compare = group[group["mode"] == mode].set_index("seed")
            for metric in ["average_queue", "rejection_ratio", "energy_J"]:
                diff = (compare[metric] - base[metric]).dropna().to_numpy()
                se = float(np.std(diff, ddof=1) / np.sqrt(len(diff)))
                paired.append(dict(scenario=scenario, method=mode, metric=metric,
                                   delta_mean=float(np.mean(diff)),
                                   ci_low=float(np.mean(diff) - 1.96 * se),
                                   ci_high=float(np.mean(diff) + 1.96 * se)))
    pd.DataFrame(paired).to_csv(out / "paired_vs_nominal.csv", index=False)
    for metric, label in [("queue_mean", "Average queued packets"),
                          ("drop_mean", "Rejected packet fraction"),
                          ("energy_mean", "Transmission energy (J)"),
                          ("max_feasibility", "Max planned violation")]:
        fig, axes = plt.subplots(1, 2, figsize=(11, 4), layout="constrained")
        for ax, scenario in zip(axes, ["moderate", "scarce"]):
            part = summary[summary.scenario == scenario].set_index("mode").reindex(METHODS)
            ax.bar(range(len(METHODS)), part[metric])
            ax.set_xticks(range(len(METHODS)), METHODS, rotation=22, ha="right")
            ax.set_title(scenario.capitalize())
            ax.set_ylabel(label)
            ax.grid(axis="y", alpha=.2)
        fig.savefig(out / f"{metric}.png", dpi=220)
        plt.close(fig)
    (out / "run_settings.json").write_text(json.dumps(vars(args), indent=2))
    print("\nSUMMARY\n", summary.to_string(index=False))
    print("\nWrote outputs to", out.resolve())


if __name__ == "__main__":
    main()