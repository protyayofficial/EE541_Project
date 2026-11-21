"""Matched causal Monte Carlo evaluation of the EE541 proposal.

Correlated lognormal volatility and energy-harvest regimes are varied;
none of the controllers are given the generated future values.
"""
import argparse,json,platform,shutil,sys,time
from pathlib import Path
from dataclasses import replace
import numpy as np,pandas as pd
from scipy.stats import t as student_t
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from src.experiment import make_trace
from src.scheduling import Config
from src.radio import simulation_settings,timing_metrics
from proposal_study import run
from src.packets import run_delay_metrics,append_packet_run,DELAY_MEASURES,paired_stats

MODES=('greedy','nominal','fixed_margin','adaptive_harvest','adaptive_all')
HARVEST=(.6,1.2)
DEFAULT_SLOTS=1000
SIGMAS=(.20,.45,.80)
DEFAULT_ROOT='results/final_evaluation_continuous_1000'

def make_evaluation_trace(slots,seed,mean_harvest,*,sigma=.45,mean_normalize=True,rho=.68):
    generated=make_trace(slots,seed,harvest_mean=mean_harvest,channel_sigma=sigma,
                         channel_rho=rho,mean_normalize=mean_normalize)
    return {k:generated[k] for k in ('condition','gain','arrival','harvest','seed',
                                    'channel_rho','channel_sigma','channel_mean_normalize')}


def planned_runs(seeds=10,seed_start=None,mean_normalize=False,sigmas=SIGMAS):
    start=(6000 if mean_normalize else 5000) if seed_start is None else seed_start
    return [dict(harvest_mean=h,channel_sigma=sigma,seed=seed,mode=mode)
            for h in HARVEST for sigma in sigmas for seed in range(start,start+seeds) for mode in MODES]


def evaluate(df,cfg):
    end=float(df.b_next.iloc[-1])
    return dict(queue=df.b.mean(),drop_ratio=df['drop'].sum()/max(1.,df.arrivals.sum()),
      energy=df.energy.sum(),data_energy=df.data_energy.sum(),control_energy=df.control_energy.sum(),
      attempted=df.attempted.sum(),received=df.received.sum(),acknowledged=df.acknowledged.sum(),delivered=df.delivered.sum(),
      throughput=df.throughput_bps.mean(),terminal_queue=end,
      realized_cost=float(df.b.sum()+cfg.drop_weight*df['drop'].sum()+cfg.energy_weight*df.energy.sum()+cfg.terminal_weight*end),
      max_violation=df.plan_violation.max(),inaccurate=int((df.solver_status=='optimal_inaccurate').sum()),
      mean_solve_ms=df.solve_ms.mean(),coverage_gain=df.covered_gain.mean(),coverage_arrival=df.covered_arrival.mean(),
      coverage_harvest=df.covered_harvest.mean(),forecast_mae_gain=df.raw_error_gain.abs().mean(),
      forecast_mae_arrival=df.raw_error_arrival.abs().mean(),forecast_mae_harvest=df.raw_error_harvest.abs().mean(),
      **timing_metrics(df),**run_delay_metrics(df))

def main():
    p=argparse.ArgumentParser(description='Correlated lognormal channel; original or stationary mean-normalized sweep')
    p.add_argument('--seeds',type=int,default=10);p.add_argument('--seed-start',type=int)
    p.add_argument('--mean-normalize',action='store_true');p.add_argument('--rho',type=float,default=.68)
    p.add_argument('--sigma',type=float,nargs='+',default=list(SIGMAS))
    p.add_argument('--slots',type=int,default=DEFAULT_SLOTS);p.add_argument('--horizon',type=int,default=10);p.add_argument('--out');a=p.parse_args()
    if a.seeds<2 or a.slots<2 or a.horizon<2:p.error('seeds, slots and horizon must be at least 2')
    if len(set(a.sigma))!=len(a.sigma) or any(not np.isfinite(x) or x<=0 for x in a.sigma):p.error('sigma values must be distinct, positive and finite')
    if a.seed_start is None:a.seed_start=6000 if a.mean_normalize else 5000
    if a.out is None:a.out=DEFAULT_ROOT+('/sweep_normalized' if a.mean_normalize else '/sweep')
    out=Path(a.out)
    if any((out/name).exists() for name in ('per_seed.csv','per_slot.csv','per_packet.csv','partial_slots.csv','partial_windows.csv')):
        p.error('output already contains trajectories; choose a fresh --out directory')
    cfg=replace(Config(),horizon=a.horizon,channel_rho=a.rho,channel_mean_normalize=a.mean_normalize)
    matrix=planned_runs(a.seeds,a.seed_start,a.mean_normalize,a.sigma)
    out.mkdir(parents=True,exist_ok=True);rows=[]
    pd.DataFrame(matrix).to_csv(out/'run_matrix.csv',index=False)
    settings=vars(a)|simulation_settings(cfg)|{'modes':MODES,'mean_harvest':HARVEST,'volatility':a.sigma,
      'arrivals':'IID discrete uniform integers 0..10 inclusive, mean 5; no load sweep',
      'predictor':'causal conditional lognormal means from timed numerical probe reports; causal arrival/harvest estimates',
      'note':'normalized stationary mean 1; original stationary mean exp(v/2); higher moments vary with sigma; no realized-sample normalization',
      'scenario_channel_models':{str(s):replace(cfg,channel_sigma=s).channel_model.settings() for s in a.sigma},
      'seed_ids':list(range(a.seed_start,a.seed_start+a.seeds)),'planned_policy_runs':len(matrix),
      'platform':platform.platform(),'python':sys.version}
    (out/'settings.json').write_text(json.dumps(settings,indent=2)+'\n')
    for harvest in HARVEST:
      for sigma in a.sigma:
       c=replace(cfg,channel_sigma=sigma)
       for seed in range(a.seed_start,a.seed_start+a.seeds):
        trace=make_evaluation_trace(a.slots,seed,harvest,sigma=sigma,mean_normalize=a.mean_normalize,rho=a.rho)
        for mode in MODES:
          print('harvest',harvest,'sigma',sigma,'seed',seed,'mode',mode,flush=True)
          start=time.perf_counter();df=run(trace,c,mode);row=evaluate(df,c)|dict(harvest_mean=harvest,channel_sigma=sigma,seed=seed,mode=mode,wall_seconds=time.perf_counter()-start)
          run_id=append_packet_run(df,out,dict(experiment='sweep_normalized' if a.mean_normalize else 'sweep',harvest_mean=harvest,seed=seed,mode=mode))
          row['run_id']=run_id
          rows.append(row);df=df.copy();df['harvest_mean']=harvest;df['channel_sigma']=sigma;df['seed']=seed;df['run_id']=run_id
          df.to_csv(out/'partial_slots.csv',mode='a',header=not (out/'partial_slots.csv').exists(),index=False)
          pd.DataFrame(rows).to_csv(out/'partial_windows.csv',index=False)
    raw=pd.DataFrame(rows);raw.to_csv(out/'per_seed.csv',index=False);shutil.copyfile(out/'partial_slots.csv',out/'per_slot.csv')
    measures=['queue','drop_ratio','energy','throughput','terminal_queue','realized_cost','coverage_gain','coverage_arrival','coverage_harvest','forecast_mae_gain','forecast_mae_arrival','forecast_mae_harvest','mean_solve_ms',*timing_metrics(df),*run_delay_metrics(df)]
    raw.groupby(['harvest_mean','channel_sigma','mode'])[measures].agg(['mean','std','count']).to_csv(out/'summary.csv')
    pairs=[]
    for (h,sigma),g in raw.groupby(['harvest_mean','channel_sigma']):
      base=g[g['mode']=='nominal'].set_index('seed')
      for mode in MODES:
        if mode=='nominal':continue
        comp=g[g['mode']==mode].set_index('seed')
        for metric in ('queue','drop_ratio','energy','throughput','terminal_queue','realized_cost',*DELAY_MEASURES):
          diff=comp[metric]-base[metric]
          pairs.append(dict(harvest_mean=h,channel_sigma=sigma,method=mode,metric=metric,**paired_stats(diff)))
    pd.DataFrame(pairs).to_csv(out/'paired_vs_nominal.csv',index=False)
    for metric,label in [('realized_cost','Realized weighted cost'),('drop_ratio','Rejection fraction'),('queue','Mean queue (packets)'),('energy','TX data and control energy (J)'),('coverage_gain','One-step channel bound coverage')]:
      fig,axes=plt.subplots(1,len(HARVEST),figsize=(12,4),squeeze=False)
      for ax,harvest in zip(axes.ravel(),HARVEST):
       for mode in MODES:
        if metric.startswith('coverage') and mode=='greedy':continue
        group=raw[(raw['mode']==mode)&(raw.harvest_mean==harvest)].groupby('channel_sigma')[metric].agg(['mean','std','count'])
        half=student_t.ppf(.975,group['count']-1)*group['std']/np.sqrt(group['count'])
        ax.errorbar(group.index,group['mean'],yerr=half,marker='o',capsize=2,label=mode)
       ax.set(title=f'Mean harvest {harvest} J',xlabel='Log-channel innovation sigma',ylabel=label);ax.grid(alpha=.25);ax.legend(fontsize=7)
      fig.suptitle('Stationary mean-normalized channel' if a.mean_normalize else 'Original channel: mean gain also varies with sigma')
      fig.tight_layout();fig.savefig(out/f'{metric}.png',dpi=180);plt.close(fig)
    print('Max violation:',raw.max_violation.max(),'inaccurate:',int(raw.inaccurate.sum()))
    print(raw.groupby(['harvest_mean','channel_sigma','mode'])[['realized_cost','drop_ratio','queue','energy']].mean().to_string())
if __name__=='__main__':main()
