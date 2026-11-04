"""Paired causal AR ablation over a traffic/harvest grid, with saved traces."""
import argparse, json
from dataclasses import replace
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import t
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from src.scheduling import Config
from src.experiment import make_trace
from research_experiments import causal_forecasts
from uncertainty_study import rollout

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--seeds',type=int,default=5);ap.add_argument('--seed-start',type=int,default=300)
    ap.add_argument('--slots',type=int,default=80);ap.add_argument('--horizon',type=int,default=10)
    ap.add_argument('--out',default='results/uncertainty_stress')
    args=ap.parse_args()
    if args.seeds<2 or args.slots<2 or args.horizon<1: ap.error('seeds and slots >= 2; horizon >= 1')
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    (out/'settings.json').write_text(json.dumps(vars(args),indent=2))
    cfg=replace(Config(),horizon=args.horizon); rows=[]; all_slots=[]
    for a in (2.,2.5,3.):
        for h in (.6,1.1,1.6):
            for seed in range(args.seed_start,args.seed_start+args.seeds):
                trace=causal_forecasts(make_trace(args.slots,seed,arrival_mean=a,harvest_mean=h),max(21,args.horizon))
                for mode in ('ar_nominal','ar_calibrated'):
                    print(f'arrival={a} harvest={h} seed={seed} method={mode}',flush=True)
                    df=rollout(trace,cfg,mode,'cvxpy');df['seed']=seed;df['arrival_mean']=a;df['harvest_mean']=h
                    all_slots.append(df)
                    rows.append(dict(arrival_mean=a,harvest_mean=h,seed=seed,mode=mode,
                        queue=df.b.mean(),drop_ratio=df['drop'].sum()/max(1,df.arrivals.sum()),
                        energy=df.energy.sum(),throughput=df.throughput_bps.mean(),
                        max_violation=df.violation.max(),fallbacks=int(df.stage2_fallback.sum()),
                        inaccurate=int((df.solver_status=='optimal_inaccurate').sum())))
                    pd.DataFrame(rows).to_csv(out/'per_seed_partial.csv',index=False)
                    pd.concat(all_slots,ignore_index=True).to_csv(out/'per_slot_partial.csv',index=False)
    raw=pd.DataFrame(rows);raw.to_csv(out/'per_seed.csv',index=False)
    pd.concat(all_slots,ignore_index=True).to_csv(out/'per_slot.csv',index=False)
    raw.groupby(['arrival_mean','harvest_mean','mode']).agg(['mean','std']).to_csv(out/'summary.csv')
    pairs=[]
    for (a,h),group in raw.groupby(['arrival_mean','harvest_mean']):
        ref=group[group['mode']=='ar_nominal'].set_index('seed'); comp=group[group['mode']=='ar_calibrated'].set_index('seed')
        for metric in ('queue','drop_ratio','energy','throughput'):
            diff=(comp[metric]-ref[metric]).dropna(); m=diff.mean(); ci=t.ppf(.975,len(diff)-1)*diff.std(ddof=1)/np.sqrt(len(diff))
            pairs.append(dict(arrival_mean=a,harvest_mean=h,metric=metric,n=len(diff),delta=m,ci_low=m-ci,ci_high=m+ci))
    pd.DataFrame(pairs).to_csv(out/'paired.csv',index=False)
    for metric in ('queue','drop_ratio'):
        fig,axes=plt.subplots(1,3,figsize=(12,4),sharey=True)
        for ax,a in zip(axes,(2.,2.5,3.)):
            for mode in ('ar_nominal','ar_calibrated'):
                part=raw[(raw.arrival_mean==a)&(raw['mode']==mode)].groupby('harvest_mean')[metric].mean()
                ax.plot(part.index,part.values,marker='o',label=mode)
            ax.set(title=f'Arrival mean {a}',xlabel='Mean harvest (J/slot)');ax.grid(alpha=.25)
        axes[0].set_ylabel(metric);axes[-1].legend();fig.tight_layout();fig.savefig(out/f'{metric}.png',dpi=180);plt.close(fig)
    print('Finished; fallbacks:',raw.fallbacks.sum(),'worst residual:',raw.max_violation.max())
if __name__=='__main__':main()
