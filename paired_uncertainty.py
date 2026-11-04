"""Paired Student-t intervals from an uncertainty_study output directory."""
import argparse
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import t

p=argparse.ArgumentParser();p.add_argument('directory');args=p.parse_args()
out=Path(args.directory);data=pd.read_csv(out/'per_seed.csv');rows=[]
for scenario, group in data.groupby('scenario'):
    for reference in ('ar_nominal','ema_nominal'):
        base=group[group['mode']==reference].set_index('seed')
        for method in ('ar_calibrated','ar_gated'):
            comp=group[group['mode']==method].set_index('seed')
            for metric in ('queue','drop_ratio','energy','throughput'):
                delta=(comp[metric]-base[metric]).dropna(); n=len(delta)
                if n<2: raise ValueError('At least two matched seeds are required')
                mean=delta.mean();half=t.ppf(.975,n-1)*delta.std(ddof=1)/np.sqrt(n)
                rows.append(dict(scenario=scenario,method=method,reference=reference,metric=metric,n=n,mean_delta=mean,ci_low=mean-half,ci_high=mean+half))
pd.DataFrame(rows).to_csv(out/'paired_t_intervals.csv',index=False)
print('Saved',out/'paired_t_intervals.csv')
