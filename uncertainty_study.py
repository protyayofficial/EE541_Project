"""EE541: causal calibrated prediction + reliability-first MPC ablation.

Put alongside reliability_study.py. No future information is used to generate predictions.
"""
import argparse
from dataclasses import replace
from pathlib import Path
import time
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from src.scheduling import Config, capacity, solve_lp, verify_plan
from src.experiment import make_trace
from research_experiments import causal_forecasts
from reliability_study import solve_lex

METHODS = ('ema_nominal', 'ar_nominal', 'ar_calibrated', 'ar_gated')


def forecasts_at(t, trace, cfg, method, history, errors):
    """Produce a horizon forecast from observed past and current channel only."""
    n = min(cfg.horizon, len(trace['gain']) - t)
    gain = float(trace['gain'][t])  # observed before sending
    if method == 'ema_nominal':
        return (np.r_[gain, trace['forecast_gain'][t, 1:n]].astype(float),
                trace['forecast_arrival'][t, :n].copy(),
                trace['forecast_harvest'][t, :n].copy())

    past_g = np.asarray(history['gain'], dtype=float)
    past_l = np.asarray(history['arrival'], dtype=float)
    past_H = np.asarray(history['harvest'], dtype=float)
    z = np.log(max(gain, 1e-8))
    # Online shrinkage estimate; no access to future synthetic AR parameter.
    if len(past_g) >= 12:
        logs = np.log(np.maximum(past_g[-80:], 1e-8))
        x, y = logs[:-1], logs[1:]
        rho = float(np.clip(np.dot(x, y) / (np.dot(x, x) + 3.0), 0.0, 0.95))
        innovations = y - rho * x
        sigma = float(np.sqrt(np.mean(innovations**2)))
    else:
        rho, sigma = 0.0, 0.45

    g = np.ones(n)
    g[0] = gain
    for k in range(1, n):
        # Predict conditional MEDIAN of the lognormal channel.
        g[k] = float(np.exp((rho ** k) * z))

    # Simple causal estimates with shrinkage priors for initially short history.
    l_mean = (2.5 * 8 + past_l.sum()) / (8 + len(past_l))
    H_mean = (1.1 * 8 + past_H.sum()) / (8 + len(past_H))
    l = np.full(n, l_mean)
    H = np.full(n, H_mean)
    if method == 'ar_nominal' or len(errors) < 12:
        return g, l, H

    errs = np.asarray(errors[-50:], dtype=float)
    # Nonconformity scores: overpredicted gain, underpredicted arrivals,
    # and overpredicted harvesting, all measured AFTER actual observation.
    upper = np.quantile(errs, 0.8, axis=0)
    strength = 0.5
    if method == 'ar_gated':
        # High congestion or critically low stored energy: do not reserve
        # additional resources for an uncertain future.
        congestion = float(history['b'][-1] / cfg.buffer_max)
        battery = float(history['E'][-1] / cfg.energy_max)
        strength = 0.0 if congestion > 0.65 or battery < 0.25 else 0.5

    for k in range(1, n):
        sigma_k = sigma * np.sqrt(sum(rho**(2*j) for j in range(k)))
        g[k] = max(0.01, g[k] * np.exp(-strength * min(upper[0], 2*sigma_k)))
    l += strength * upper[1]
    H = np.maximum(0.0, H - strength * upper[2])
    return g, l, H


def rollout(trace, cfg, method, backend):
    b, E = 12.0, 7.0
    history = {'gain': [], 'arrival': [], 'harvest': [], 'b': [b], 'E': [E]}
    errors = []
    rows = []
    for t in range(len(trace['gain'])):
        g, l, H = forecasts_at(t, trace, cfg, method, history, errors)
        gain = float(trace['gain'][t]); arrival = float(trace['arrival'][t]); harvest = float(trace['harvest'][t])
        start = time.perf_counter()
        if backend == 'cvxpy':
            sol = solve_lex(b, E, g, l, H, cfg)
        else:
            # LP smoke checks use a large rejection weight, NOT exact lexicographic MPC.
            sol = solve_lp(b, E, g, l, H, replace(cfg, drop_weight=10000.0))
        elapsed = time.perf_counter() - start
        p = float(np.clip(sol['p'][0], 0.0, min(cfg.power_max, E / cfg.tau)))
        d = float(np.clip(sol['d'][0], 0.0, min(b, cfg.data_max, capacity(p, gain, cfg))))
        # Real arrivals occur after transmission. No proactive dropping.
        drop = min(arrival, max(0.0, b - d + arrival - cfg.buffer_max))
        b_next = b - d + arrival - drop
        pre_E = E - p * cfg.tau + harvest
        spill = max(0.0, pre_E - cfg.energy_max)
        E_next = pre_E - spill
        assert -1e-6 <= b_next <= cfg.buffer_max + 1e-6
        assert -1e-6 <= E_next <= cfg.energy_max + 1e-6
        violation = max(verify_plan(sol, b, E, g, l, H, cfg).values())
        rows.append(dict(t=t, mode=method, b=b, E=E, p=p, d=d, drop=drop,
                         arrivals=arrival, throughput_bps=d*cfg.packet_bits/cfg.slot_seconds,
                         energy=p*cfg.tau, solve_ms=elapsed*1000, violation=violation,
                         solver_status=sol.get('status','unknown'),
                         stage2_fallback=sol.get('stage2_fallback', False),
                         stage2_error=sol.get('stage2_error', '')))
        # Score the PREVIOUS one-step forecast only after observing its outcome.
        if t > 0 and 'forecast' in history:
            prev = history['forecast']
            errors.append((max(0.0, np.log(max(prev[0],1e-8)) - np.log(max(gain,1e-8))),
                           max(0.0, arrival-prev[1]), max(0.0, prev[2]-harvest)))
        # Save the actual forecast used for this decision, scored next slot.
        if t + 1 < len(trace['gain']) and len(g) > 1:
            history['forecast'] = (g[1], l[1], H[1])
        history['gain'].append(gain);history['arrival'].append(arrival);history['harvest'].append(harvest)
        history['b'].append(b_next);history['E'].append(E_next)
        b, E = b_next, E_next
    return pd.DataFrame(rows)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--backend',choices=['lp','cvxpy'],default='cvxpy')
    ap.add_argument('--seeds',type=int,default=3)
    ap.add_argument('--seed-start',type=int,default=100)
    ap.add_argument('--slots',type=int,default=50)
    ap.add_argument('--horizon',type=int,default=10)
    ap.add_argument('--out',default='results/uncertainty_v1')
    args=ap.parse_args()
    if args.seeds < 2 or args.slots < 2 or args.horizon < 1:
        ap.error("Use at least 2 seeds, 2 slots, and horizon >= 1")
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    cfg=replace(Config(),horizon=args.horizon)
    summaries=[];traces=[]
    for scenario,a,h in [('moderate',2.5,1.1),('scarce',3.0,0.6)]:
        for seed in range(args.seed_start,args.seed_start+args.seeds):
            trace=causal_forecasts(make_trace(args.slots,seed=seed,arrival_mean=a,harvest_mean=h),max(21,args.horizon))
            for method in METHODS:
                print(scenario,seed,method,flush=True)
                df=rollout(trace,cfg,method,args.backend)
                df['scenario']=scenario;df['seed']=seed
                traces.append(df)
                summaries.append(dict(scenario=scenario,seed=seed,mode=method,
                    queue=df.b.mean(),drop_ratio=df['drop'].sum()/max(1,df.arrivals.sum()),
                    throughput=df.throughput_bps.mean(),energy=df.energy.sum(),
                    solve_ms=df.solve_ms.mean(),max_violation=df.violation.max(),
                    inaccurate_fraction=(df.solver_status=='optimal_inaccurate').mean(),
                    stage2_fallbacks=int(df.stage2_fallback.sum())))
                # Persist completed runs so a later failure does not erase them.
                pd.DataFrame(summaries).to_csv(out/'per_seed_partial.csv', index=False)
                pd.concat(traces, ignore_index=True).to_csv(out/'per_slot_partial.csv', index=False)
    raw=pd.DataFrame(summaries);raw.to_csv(out/'per_seed.csv',index=False)
    pd.concat(traces,ignore_index=True).to_csv(out/'per_slot.csv',index=False)
    means=raw.groupby(['scenario','mode']).agg(queue=('queue','mean'),drop=('drop_ratio','mean'),
        energy=('energy','mean'),throughput=('throughput','mean'),max_violation=('max_violation','max'),
        solve_ms=('solve_ms','mean'), fallback_count=('stage2_fallbacks','sum')).reset_index()
    means.to_csv(out/'summary.csv',index=False)
    print(means.to_string(index=False))
    # Paired differences allow fair matched-trace comparison.
    pairs=[]
    for scenario,group in raw.groupby('scenario'):
        base=group[group['mode']=='ema_nominal'].set_index('seed')
        for method in METHODS[1:]:
            comp=group[group['mode']==method].set_index('seed')
            for metric in ['queue','drop_ratio','energy','throughput']:
                dif=(comp[metric]-base[metric]).dropna()
                pairs.append(dict(scenario=scenario,method=method,metric=metric,
                                  mean_delta=dif.mean(),ci_low=dif.mean()-1.96*dif.std(ddof=1)/np.sqrt(len(dif)),
                                  ci_high=dif.mean()+1.96*dif.std(ddof=1)/np.sqrt(len(dif))))
    pd.DataFrame(pairs).to_csv(out/'paired.csv',index=False)
    for metric in ['queue','drop_ratio','energy','throughput']:
        fig,axes=plt.subplots(1,2,figsize=(10,4),sharey=True)
        for ax,(scenario,group) in zip(axes,raw.groupby('scenario')):
            values=group.groupby('mode')[metric].mean().reindex(METHODS)
            ax.bar(range(len(METHODS)),values.to_numpy());ax.set_xticks(range(len(METHODS)),METHODS,rotation=25,ha='right')
            ax.set_title(scenario);ax.set_ylabel(metric)
        fig.tight_layout();fig.savefig(out/f'{metric}.png',dpi=180);plt.close(fig)

if __name__=='__main__':main()
