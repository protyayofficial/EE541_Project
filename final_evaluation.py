"""Matched causal Monte Carlo evaluation of the EE541 proposal.

The channel's innovation variance and energy-harvest regime are varied;
none of the controllers are given the generated future values.
"""
import argparse,json,platform,subprocess,sys,time
from pathlib import Path
from dataclasses import replace
import numpy as np,pandas as pd
from scipy.stats import t as student_t
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from src.experiment import make_trace
from src.scheduling import Config
from proposal_study import run

MODES=('greedy','nominal','fixed_margin','adaptive_harvest','adaptive_all')
VOLATILITY=(.2,.45,.8)
HARVEST=(.6,1.2)

def make_evaluation_trace(slots,seed,sigma,mean_harvest,mean_normalize=False):
    generated=make_trace(slots,seed,arrival_mean=2.5,harvest_mean=mean_harvest)
    # Discard the generator's oracle-aided forecast fields; the controller
    # constructs all forecasts causally from observation history.
    tr={k:generated[k] for k in ('gain','arrival','harvest')}
    tr['arrival']=np.minimum(tr['arrival'],10.) # matches proposal support
    rng=np.random.default_rng(seed+48001);gain=np.empty(slots)
    rho=.68; variance=sigma**2/(1-rho**2)
    z=rng.normal(0,np.sqrt(variance)) if mean_normalize else 0.
    for i in range(slots):
        z=rho*z+rng.normal(0,sigma)
        gain[i]=np.exp(z-.5*variance if mean_normalize else z)
    tr['gain']=gain
    return tr

def evaluate(df,cfg):
    end=float(df.b.iloc[-1]-df.d.iloc[-1]+df.arrivals.iloc[-1]-df['drop'].iloc[-1])
    return dict(queue=df.b.mean(),drop_ratio=df['drop'].sum()/max(1.,df.arrivals.sum()),
      energy=df.energy.sum(),throughput=df.throughput_bps.mean(),terminal_queue=end,
      realized_cost=float(df.b.sum()+cfg.drop_weight*df['drop'].sum()+cfg.energy_weight*df.energy.sum()+cfg.terminal_weight*end),
      max_violation=df.plan_violation.max(),inaccurate=int((df.solver_status=='optimal_inaccurate').sum()),
      mean_solve_ms=df.solve_ms.mean(),coverage_gain=df.covered_gain.mean(),coverage_arrival=df.covered_arrival.mean(),
      coverage_harvest=df.covered_harvest.mean(),forecast_mae_gain=df.raw_error_gain.abs().mean(),
      forecast_mae_arrival=df.raw_error_arrival.abs().mean(),forecast_mae_harvest=df.raw_error_harvest.abs().mean())

def main():
    p=argparse.ArgumentParser();p.add_argument('--seeds',type=int,default=10);p.add_argument('--seed-start',type=int,default=5000)
    p.add_argument('--mean-normalize',action='store_true',help='Normalize stationary lognormal gain to theoretical mean one')
    p.add_argument('--slots',type=int,default=80);p.add_argument('--horizon',type=int,default=10);p.add_argument('--out',default='results/final_evaluation/sweep');a=p.parse_args()
    if a.seeds<2 or a.slots<2 or a.horizon<2:p.error('seeds, slots and horizon must be at least 2')
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True);cfg=replace(Config(),horizon=a.horizon);rows=[];frames=[]
    settings=vars(a)|{'modes':MODES,'volatility':VOLATILITY,'mean_harvest':HARVEST,'arrivals':'Poisson mean 2.5, clipped to [0,10]',
      'predictor':'causal past-only AR channel and historical arrival/harvest estimate; current channel observed',
      'note':'fixed method settings; normalized case sets stationary expected gain to one but higher moments still change; volatility is not a direct forecast-noise injection; paired comparisons by seed',
      'platform':platform.platform(),'python':sys.version}
    (out/'settings.json').write_text(json.dumps(settings,indent=2)+'\n')
    for harvest in HARVEST:
      for sigma in VOLATILITY:
        for seed in range(a.seed_start,a.seed_start+a.seeds):
          trace=make_evaluation_trace(a.slots,seed,sigma,harvest,a.mean_normalize)
          for mode in MODES:
            print('harvest',harvest,'volatility',sigma,'seed',seed,'mode',mode,flush=True)
            start=time.perf_counter();df=run(trace,cfg,mode);row=evaluate(df,cfg)|dict(harvest_mean=harvest,channel_sigma=sigma,seed=seed,mode=mode,wall_seconds=time.perf_counter()-start)
            rows.append(row);df=df.copy();df['harvest_mean']=harvest;df['channel_sigma']=sigma;df['seed']=seed;frames.append(df)
            pd.DataFrame(rows).to_csv(out/'partial_windows.csv',index=False)
          # Save progress after each paired seed; no data from future windows required.
          pd.concat(frames,ignore_index=True).to_csv(out/'partial_slots.csv',index=False)
    raw=pd.DataFrame(rows);raw.to_csv(out/'per_seed.csv',index=False);pd.concat(frames,ignore_index=True).to_csv(out/'per_slot.csv',index=False)
    measures=['queue','drop_ratio','energy','throughput','terminal_queue','realized_cost','coverage_gain','coverage_arrival','coverage_harvest','forecast_mae_gain','forecast_mae_arrival','forecast_mae_harvest','mean_solve_ms']
    raw.groupby(['harvest_mean','channel_sigma','mode'])[measures].agg(['mean','std']).to_csv(out/'summary.csv')
    pairs=[]
    for (h,sigma),g in raw.groupby(['harvest_mean','channel_sigma']):
      base=g[g['mode']=='nominal'].set_index('seed')
      for mode in MODES:
        if mode=='nominal':continue
        comp=g[g['mode']==mode].set_index('seed')
        for metric in ('queue','drop_ratio','energy','throughput','terminal_queue','realized_cost'):
          diff=(comp[metric]-base[metric]).dropna();n=len(diff);mean=diff.mean();half=student_t.ppf(.975,n-1)*diff.std(ddof=1)/np.sqrt(n)
          pairs.append(dict(harvest_mean=h,channel_sigma=sigma,method=mode,metric=metric,n=n,delta=mean,ci_low=mean-half,ci_high=mean+half))
    pd.DataFrame(pairs).to_csv(out/'paired_vs_nominal.csv',index=False)
    for metric,label in [('realized_cost','Realized weighted cost'),('drop_ratio','Rejection fraction'),('queue','Mean queue (packet equivalents)'),('energy','Transmit energy (J)'),('coverage_gain','One-step channel bound coverage')]:
      fig,axes=plt.subplots(1,2,figsize=(11,4),sharey=True)
      for ax,h in zip(axes,HARVEST):
        for mode in MODES:
          if metric.startswith('coverage') and mode=='greedy':continue
          group=raw[(raw.harvest_mean==h)&(raw['mode']==mode)].groupby('channel_sigma')[metric].agg(['mean','std','count'])
          half=student_t.ppf(.975,group['count']-1)*group['std']/np.sqrt(group['count'])
          ax.errorbar(group.index,group['mean'],yerr=half,marker='o',capsize=2,label=mode)
        ax.set(title=f'Mean harvest {h} J/slot',xlabel='Channel innovation standard deviation',ylabel=label);ax.grid(alpha=.25)
      axes[-1].legend(fontsize=7);fig.tight_layout();fig.savefig(out/f'{metric}.png',dpi=180);plt.close(fig)
    print('Max violation:',raw.max_violation.max(),'inaccurate:',int(raw.inaccurate.sum()))
    print(raw.groupby(['harvest_mean','channel_sigma','mode'])[['realized_cost','drop_ratio','queue','energy']].mean().to_string())
if __name__=='__main__':main()
