
"""Synthetic trace and causal receding-horizon policies."""

import time
import numpy as np
import pandas as pd

from .scheduling import (
    Config,
    INITIAL_QUEUE,
    INITIAL_ENERGY,
    capacity,
    solve_lp,
    solve_cvxpy,
    verify_plan,
    planner_action,
    validate_packet_inputs,
)

from .forecasting import ARRIVAL_MIN, ARRIVAL_MAX, bound_arrivals, raw_forecasts
from .radio import PacketRadio,timing_metrics
from .packets import attach_packet_ledger,run_delay_metrics
from .channel import ChannelModel,CHANNEL_THRESHOLD,channel_sequence,bound_gain,validate_trace_model


def make_trace(
    n=160,
    seed=7,
    harvest_mean=1.1,
    forecast_noise=0.4,
    channel_rho=.68,
    channel_sigma=.45,
    mean_normalize=True,
):
    rng = np.random.default_rng(seed)

    model=ChannelModel(channel_rho,channel_sigma,mean_normalize)
    gain=channel_sequence(n,seed,model)
    condition=np.full(n,'continuous')  # Descriptive only.

    # IID whole counts 0..10 inclusive, shared by every policy on this trace.
    arrival = rng.integers(ARRIVAL_MIN, ARRIVAL_MAX + 1, size=n)

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

        fg[t] = bound_gain(gain[sl] * np.exp(rngf.normal(0, forecast_noise, horizon)))

        fl[t] = bound_arrivals(
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
        "seed": int(seed),
        "channel_rho":channel_rho,"channel_sigma":channel_sigma,
        "channel_mean_normalize":mean_normalize,
        "condition": condition,
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

        errors=np.asarray(history,dtype=float).reshape(-1,3)
        return tuple(max(0.,float(np.quantile(v[np.isfinite(v)][-40:],.8))) if np.isfinite(v).sum()>=8 else prior
                     for v,prior in zip(errors.T,(.38,1.,.25)))

    raise ValueError(mode)


def run_policy(
    trace,
    mode,
    cfg=Config(),
    backend="lp",
    b0=INITIAL_QUEUE,
    e0=INITIAL_ENERGY,
    allow_proactive=True,
):
    """Causal scheduling with probe reports, expected planning and ACK departures.

    Generator oracle forecast fields are retained for old data compatibility,
    but are never read by the controller.
    """
    if mode not in ('fixed','channel','greedy','nominal','robust','adaptive','adaptive_risk'):
        raise ValueError(mode)
    if backend not in ('lp','cvxpy'):
        raise ValueError(backend)
    validate_packet_inputs(trace['arrival'], b0, cfg)
    validate_trace_model(trace,cfg)
    radio = PacketRadio(b0, cfg, trace.get('seed', 0), trace=trace)
    E = float(e0)
    records = []
    residual_history = []
    history = {'gain': [], 'gain_times':[], 'arrival': [], 'harvest': []}
    prev = None
    solve = solve_lp if backend == 'lp' else solve_cvxpy
    for t in range(len(trace['gain'])):
        arrival = int(trace['arrival'][t])
        harvest = float(trace['harvest'][t])
        b = len(radio.queue.ids)
        gain, available = radio.probe(E, t=t)
        decision_start = time.perf_counter()
        m = min(cfg.horizon, len(trace['gain'])-t)
        rawg, rawl, rawH = raw_forecasts(history,gain,m,t=t,model=cfg.channel_model)
        anchor=t if radio.controls['report_available'] else (history['gain_times'][-1] if history['gain_times'] else -1)
        p = d_plan = o_plan = solution_time = feas = 0.
        solver_status, solver_name = 'heuristic', 'none'
        if not radio.exchange:
            solver_status = 'no_control_energy'
        elif mode in ('nominal','robust','adaptive','adaptive_risk'):
            mg, ml, mH = _margins(residual_history, mode)
            if mode == 'adaptive_risk':
                factor = max(.30, 1.-.70*b/cfg.buffer_max)
                mg, ml, mH = mg*factor, ml*factor, mH*factor
            ghat, lhat, Hhat = rawg.copy(), rawl.copy(), rawH.copy()
            ghat[1:] = bound_gain(ghat[1:]-mg)
            lhat = bound_arrivals(lhat+ml)
            Hhat = np.maximum(0, Hhat-mH)
            start = time.perf_counter()
            sol = solve(b, E, ghat, lhat, Hhat, cfg)
            solution_time = time.perf_counter()-start
            feas = max(verify_plan(sol, b, E, ghat, lhat, Hhat, cfg).values())
            solver_status = str(sol.get('status', 'unknown'))
            solver_name = str(sol.get('solver', 'lp'))
            d_plan,p = planner_action(sol,b,available,gain,cfg)
            o_plan = float(sol['o'][0])
        else:
            target = (cfg.power_max if mode == 'greedy' else
                      1.2 if mode == 'fixed' else 2.4 if gain >= CHANNEL_THRESHOLD else .45)
            p = min(target, cfg.power_max, available/cfg.tau)
            d_plan = min(cfg.data_max, b, float(capacity(p, gain, cfg)))
        planned_drop = min(int(np.floor(max(0., o_plan))), arrival) if allow_proactive else 0
        decision_runtime = time.perf_counter()-decision_start
        def update_history():
            nonlocal prev
            if prev is not None:
                residual_history.append((max(0.,prev[0]-gain) if radio.controls['report_available'] else np.nan, max(0., arrival-prev[1]),
                                         max(0., prev[2]-harvest)))
            prev = (rawg[1], rawl[1], rawH[1],t,t+1,anchor) if m > 1 else None
            if radio.controls['report_available']:
                history['gain'].append(gain)
                history['gain_times'].append(t)
            history['arrival'].append(arrival)
            history['harvest'].append(harvest)
        error_origin=prev[3] if prev is not None else np.nan
        error_lead=t-prev[5] if prev is not None else np.nan
        error_gain=(prev[0]-gain) if prev is not None and radio.controls['report_available'] else np.nan
        if prev is not None:assert prev[4]==t
        action = radio.execute(d_plan, p, E, arrival, harvest,
                               fixed_power=mode in ('fixed','channel'), planned_drop=planned_drop,
                               on_update=update_history,solver_runtime_s=solution_time,
                               decision_runtime_s=decision_runtime)
        records.append(dict(t=t, mode=mode, **action, planned_drop=planned_drop,
                            channel_forecast_anchor_t=anchor,forecast_origin_t=error_origin,
                            forecast_target_t=t if np.isfinite(error_origin) else np.nan,
                            forecast_channel_lead=error_lead,raw_error_gain=error_gain,
                            forecast_current_gain=rawg[0],forecast_next_gain=rawg[1] if m>1 else np.nan,
                            solve_s=solution_time, plan_feas=feas,
                            solver_status=solver_status, solver_name=solver_name))
        E = action['E_next']
    return attach_packet_ledger(pd.DataFrame.from_records(records),radio)


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
                group["energy"]
            ).sum(),
            "data_energy_J": group["data_energy"].sum(),
            "control_energy_J": group["control_energy"].sum(),
            "attempted_packets": group["attempted"].sum(),
            "received_packets": group["received"].sum(),
            "acknowledged_packets": group["acknowledged"].sum(),
            "delivered_packets": group["delivered"].sum(),
            "terminal_queue": group["b_next"].iloc[-1],
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
            **timing_metrics(group),
            **run_delay_metrics(group),
        })

    return pd.DataFrame(results)
