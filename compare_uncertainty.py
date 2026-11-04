"""Compare uncertainty study with heuristics on the same seeded traces."""
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import t
from src.experiment import make_trace, run_policy
from src.scheduling import Config

out = Path('results/uncertainty_checked')
raw = pd.read_csv(out / 'per_seed.csv')
rows = []
for scenario, arrival, harvest in [('moderate', 2.5, 1.1), ('scarce', 3.0, 0.6)]:
    for seed in range(100, 110):
        trace = make_trace(120, seed, arrival_mean=arrival, harvest_mean=harvest)
        for mode in ('fixed', 'greedy', 'channel'):
            df = run_policy(trace, mode, Config(horizon=10), backend='cvxpy', allow_proactive=False)
            rows.append(dict(scenario=scenario, seed=seed, mode=mode, queue=df.b.mean(),
                             drop_ratio=df['drop'].sum()/df.arrivals.sum(),
                             throughput=df.throughput_bps.mean(), energy=(df.p*1.0).sum()))
all_data = pd.concat([raw, pd.DataFrame(rows)], ignore_index=True)
all_data.to_csv(out/'matched_all_per_seed.csv', index=False)
all_data.groupby(['scenario','mode'])[['queue','drop_ratio','throughput','energy']].agg(['mean','std']).to_csv(out/'matched_all_summary.csv')
pairs=[]
for scenario, group in all_data.groupby('scenario'):
    for reference in ('ar_nominal','ema_nominal'):
        base=group[group['mode']==reference].set_index('seed')
        for mode in ('ar_calibrated','ar_gated'):
            comp=group[group['mode']==mode].set_index('seed')
            for metric in ('queue','drop_ratio','throughput','energy'):
                delta=(comp[metric]-base[metric]).dropna()
                n=len(delta); mean=delta.mean(); half=t.ppf(.975,n-1)*delta.std(ddof=1)/np.sqrt(n)
                pairs.append(dict(scenario=scenario,method=mode,reference=reference,metric=metric,n=n,mean_delta=mean,ci_low=mean-half,ci_high=mean+half))
pd.DataFrame(pairs).to_csv(out/'paired_t_intervals.csv',index=False)
print(all_data.groupby(['scenario','mode'])[['queue','drop_ratio','throughput','energy']].mean().to_string())
