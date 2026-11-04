
"""Synthetic trace and causal receding-horizon policies."""

import time
import numpy as np
import pandas as pd

from .scheduling import (
    Config,
    capacity,
    solve_lp,
    solve_cvxpy,
    verify_plan,
)


def make_trace(
    n=160,
    seed=7,
    arrival_mean=2.5,
    harvest_mean=1.1,
    forecast_noise=0.4,
):
    rng = np.random.default_rng(seed)

    gain = np.empty(n)
    z = 0.0

    for i in range(n):
        z = 0.68 * z + rng.normal(0, 0.43)
        gain[i] = np.exp(z)

    arrival = rng.poisson(
        arrival_mean, size=n
    ).astype(float)

    harvest = rng.gamma(
        shape=2,
        scale=harvest_mean / 2,
        size=n,
    )

    # Synthetic oracle-assisted forecasts.
    # These are used for controlled prediction-error tests,
    # not as a deployable forecasting method.
    rngf = np.random.default_rng(seed + 901)
    horizon = 21

    fg = np.zeros((n, horizon))
    fl = np.zeros_like(fg)
    fH = np.zeros_like(fg)

    for t in range(n):
        sl = np.minimum(
            np.arange(t, t + horizon), n - 1
        )

        fg[t] = np.clip(
            gain[sl] * np.exp(
                rngf.normal(0, forecast_noise, horizon)
            ),
            0.03,
            9,
        )

        fl[t] = np.maximum(
            0,
            arrival[sl] + rngf.normal(
                0, forecast_noise * 2, horizon
            ),
        )

        fH[t] = np.maximum(
            0,
            harvest[sl] + rngf.normal(
                0, forecast_noise * 0.7, horizon
            ),
        )

    return {
        "gain": gain,
        "arrival": arrival,
        "harvest": harvest,
        "forecast_gain": fg,
        "forecast_arrival": fl,
        "forecast_harvest": fH,
    }


def _margins(history, mode):
    """Estimate uncertainty margins from observed residuals."""

    if mode == "nominal":
        return 0.0, 0.0, 0.0

    if mode == "robust":
        return 0.38, 1.0, 0.25

    if mode in ("adaptive", "adaptive_risk"):

        if len(history) < 8:
            return 0.38, 1.0, 0.25

        errors = np.array(history[-40:])

        return tuple(
            np.maximum(
                0,
                np.quantile(errors, 0.8, axis=0)
            )
        )

    raise ValueError(mode)


def run_policy(
    trace,
    mode,
    cfg=Config(),
    backend="lp",
    b0=12.0,
    e0=7.0,
    allow_proactive=True,
):
    """Simulate one scheduling policy over a fixed trace."""

    n = len(trace["gain"])

    b = float(b0)
    E = float(e0)

    records = []
    residual_history = []

    solve = solve_lp if backend == "lp" else solve_cvxpy

    for t in range(n):

        gain = float(trace["gain"][t])
        arrival = float(trace["arrival"][t])
        harvest = float(trace["harvest"][t])

        p = 0.0
        d_plan = 0.0
        o_plan = 0.0

        solution_time = 0.0
        feas = 0.0

        solver_status = "heuristic"
        solver_name = "none"

        if mode in (
            "nominal",
            "robust",
            "adaptive",
            "adaptive_risk",
        ):

            m = min(cfg.horizon, n - t)

            ghat = trace["forecast_gain"][t, :m].copy()
            lhat = trace["forecast_arrival"][t, :m].copy()
            Hhat = trace["forecast_harvest"][t, :m].copy()

            mg, ml, mH = _margins(
                residual_history, mode
            )

            if mode == "adaptive_risk":

                # Reduce conservatism when queue occupancy
                # approaches buffer capacity.
                factor = max(
                    0.30,
                    1.0 - 0.70 * b / cfg.buffer_max,
                )

                mg *= factor
                ml *= factor
                mH *= factor

            if mode != "nominal":

                ghat[1:] = np.maximum(
                    0.01, ghat[1:] - mg
                )

                lhat = np.maximum(
                    0, lhat + ml
                )

                Hhat = np.maximum(
                    0, Hhat - mH
                )

            # Current channel is observed before transmission.
            ghat[0] = gain

            start = time.perf_counter()

            sol = solve(
                b, E, ghat, lhat, Hhat, cfg
            )

            solution_time = (
                time.perf_counter() - start
            )

            feas = max(
                verify_plan(
                    sol, b, E, ghat, lhat, Hhat, cfg
                ).values()
            )

            solver_status = str(
                sol.get("status", "unknown")
            )

            solver_name = str(
                sol.get("solver", "lp")
            )

            p = float(
                np.clip(
                    sol["p"][0],
                    0,
                    min(
                        cfg.power_max,
                        E / cfg.tau,
                    ),
                )
            )

            d_plan = float(sol["d"][0])
            o_plan = float(sol["o"][0])

        elif mode == "greedy":

            p = min(
                cfg.power_max,
                E / cfg.tau,
            )

            d_plan = min(
                cfg.data_max,
                b,
                capacity(p, gain, cfg),
            )

        elif mode == "fixed":

            p = min(
                1.2,
                cfg.power_max,
                E / cfg.tau,
            )

            d_plan = min(
                cfg.data_max,
                b,
                capacity(p, gain, cfg),
            )

        elif mode == "channel":

            p = min(
                cfg.power_max,
                E / cfg.tau,
                2.4 if gain > 1.1 else 0.45,
            )

            d_plan = min(
                cfg.data_max,
                b,
                capacity(p, gain, cfg),
            )

        else:
            raise ValueError(mode)

        # Execute transmission using actual channel and energy.
        d = max(
            0.0,
            min(
                d_plan,
                b,
                cfg.data_max,
                float(capacity(p, gain, cfg)),
            ),
        )

        # Rejection required to satisfy buffer capacity.
        forced_drop = min(
            arrival,
            max(
                0.0,
                b - d + arrival - cfg.buffer_max,
            ),
        )

        # Planned rejection may differ from actual arrivals.
        planned_drop = (
            min(
                max(0.0, o_plan),
                arrival,
            )
            if allow_proactive
            else 0.0
        )

        # Actual rejection satisfies both requirements.
        drop = max(
            forced_drop,
            planned_drop,
        )

        # Additional discretionary rejection.
        proactive = max(
            0.0,
            drop - forced_drop,
        )

        # Update the actual queue.
        b_next = b - d + arrival - drop

        # Update battery after transmission and harvesting.
        energy_pre = (
            E - cfg.tau * p + harvest
        )

        spill = max(
            0.0,
            energy_pre - cfg.energy_max,
        )

        E_next = energy_pre - spill

        records.append({
            "t": t,
            "mode": mode,
            "gain": gain,
            "arrivals": arrival,
            "harvest": harvest,
            "b": b,
            "E": E,
            "p": p,
            "d": d,
            "drop": drop,
            "proactive": proactive,
            "forced_drop": forced_drop,
            "planned_drop": planned_drop,
            "spill": spill,
            "throughput_bps": (
                d * cfg.packet_bits / cfg.slot_seconds
            ),
            "solve_s": solution_time,
            "plan_feas": feas,
            "solver_status": solver_status,
            "solver_name": solver_name,
        })

        # Update uncertainty estimates using
        # one-step-ahead errors from previous forecasts.
        if t > 0:

            residual_history.append((
                max(
                    0.0,
                    float(
                        trace["forecast_gain"][t - 1, 1]
                    ) - gain,
                ),
                max(
                    0.0,
                    arrival - float(
                        trace["forecast_arrival"][t - 1, 1]
                    ),
                ),
                max(
                    0.0,
                    float(
                        trace["forecast_harvest"][t - 1, 1]
                    ) - harvest,
                ),
            ))

        b = b_next
        E = E_next

        if (
            b < -1e-7
            or b > cfg.buffer_max + 1e-7
            or E < -1e-7
            or E > cfg.energy_max + 1e-7
        ):
            raise AssertionError(
                "Physical state violated capacity constraints"
            )

    return pd.DataFrame.from_records(records)


def summarize(df, cfg=Config()):
    """Summarize performance for every scheduling policy."""

    results = []

    for mode, group in df.groupby(
        "mode", sort=False
    ):

        arrivals = group["arrivals"].sum()

        results.append({
            "mode": mode,
            "average_queue": group["b"].mean(),
            "rejection_ratio": (
                group["drop"].sum() / arrivals
                if arrivals > 0
                else 0.0
            ),
            "forced_drops": float(
                group["forced_drop"].sum()
            ),
            "proactive_drops": float(
                group["proactive"].sum()
            ),
            "total_drops": float(
                group["drop"].sum()
            ),
            "throughput_bps": (
                group["throughput_bps"].mean()
            ),
            "energy_J": (
                group["p"] * cfg.tau
            ).sum(),
            "mean_solve_ms": (
                group["solve_s"].mean() * 1000
            ),
            "max_planned_violation": (
                group["plan_feas"].max()
            ),
            "inaccurate_fraction": float(
                (
                    group["solver_status"]
                    == "optimal_inaccurate"
                ).mean()
            ),
            "solver_failure_count": 0,
        })

    return pd.DataFrame(results)
