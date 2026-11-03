"""Research evaluation with paired experiments and reproducible figures.

Usage (from project root):
 python research_experiments.py --study all --backend cvxpy --seeds 10 --slots 120
 python research_experiments.py --study all --backend lp --seeds 3 --slots 50

Caution: this is synthetic evidence, not proof of algorithmic novelty or optimality.
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
from src.scheduling import Config, solve_cvxpy, solve_lp, verify_plan
from src.experiment import make_trace, run_policy, summarize

METHODS=['nominal','robust','adaptive','adaptive_risk']

def causal_forecasts(trace, horizon, alpha=.25):
    """Forecasts for slot t use ONLY observations from slots <t.

    Current channel is separately revealed to the controller before transmission.
    This baseline intentionally uses a simple historical exponential smoother.
    """
    n=len(trace['gain'])
    fields=[('gain','forecast_gain',1.),('arrival','forecast_arrival',2.5),('harvest','forecast_harvest',1.1)]
    for name, target, prior in fields:
        values=np.asarray(trace[name]); pred=np.empty(n)
        estimate=float(prior)
        for t in range(n):
            pred[t]=estimate
            estimate=(1-alpha)*estimate+alpha*float(values[t])
        trace[target]=np.repeat(pred[:,None],horizon,axis=1)
    return trace

def run_case(seed, slots, backend, horizon, noise, arrival, harvest, predictor, policies):
    cfg=replace(Config(),horizon=horizon)
    trace=make_trace(slots,seed,arrival_mean=arrival,harvest_mean=harvest,forecast_noise=noise)
    if predictor=='causal':
        trace=causal_forecasts(trace,max(21,horizon))
    rows=[]; example=None
    for mode in policies:
        df=run_policy(trace,mode,cfg,backend=backend,allow_proactive=False)
        sm=summarize(df,cfg).iloc[0].to_dict()
        sm.update(seed=seed,slots=slots,horizon=horizon,noise=noise,
                  arrival_mean=arrival,harvest_mean=harvest,predictor=predictor,
                  forced_drops=float(df['drop'].sum()),
                  delivered=float(df['d'].sum()),
                  avg_spill_J=float(df.spill.mean()),
                  drop_events=int((df['drop']>1e-7).sum()),
                  mean_power_W=float(df.p.mean()))
        rows.append(sm)
        if example is None or mode == 'adaptive_risk':
            df=df.copy();df['seed']=seed;df['predictor']=predictor
            example=df if example is None else example
    return rows

def paired_intervals(df, xcols):
    """Per-seed paired differences versus nominal, with normal-approx 95% CI.

    Use 10+ seeds as a basic screening, not as publication-grade inference.
    """
    records=[]
    for keys, sub in df.groupby(xcols,dropna=False):
        if not isinstance(keys,tuple):keys=(keys,)
        base=sub[sub['mode']=='nominal'].set_index('seed')
        for mode in METHODS[1:]:
            m=sub[sub['mode']==mode].set_index('seed')
            seeds=base.index.intersection(m.index)
            for metric in ['average_queue','rejection_ratio','energy_J','throughput_bps']:
                if len(seeds)<2:continue
                diffs=(m.loc[seeds,metric]-base.loc[seeds,metric]).to_numpy()
                avg=float(np.mean(diffs));se=float(np.std(diffs,ddof=1)/np.sqrt(len(diffs)))
                row=dict(zip(xcols,keys));row.update(method=mode,metric=metric,n=len(diffs),
                      mean_difference=avg,ci_low=avg-1.96*se,ci_high=avg+1.96*se)
                records.append(row)
    return pd.DataFrame(records)

def plot_metric(data, x, metric, ylabel, filename):
    fig,ax=plt.subplots(figsize=(8.2,4.5))
    for mode in METHODS:
        part=data[data['mode']==mode]
        agg=part.groupby(x)[metric].agg(['mean','std','count']).reset_index().sort_values(x)
        if agg.empty:continue
        err=(agg['std']/np.sqrt(agg['count'])).fillna(0)*1.96
        ax.errorbar(agg[x],agg['mean'],yerr=err,marker='o',capsize=3,label=mode)
    ax.set(xlabel=x.replace('_',' ').capitalize(),ylabel=ylabel)
    ax.legend(fontsize=8)
    ax.grid(alpha=.2)
    fig.tight_layout();fig.savefig(filename,dpi=200);plt.close(fig)

def plot_pareto(df, file):
    fig,ax=plt.subplots(figsize=(7.5,5))
    summary=df.groupby('mode')[['average_queue','rejection_ratio','energy_J']].mean()
    for mode,r in summary.iterrows():
        ax.scatter(r.rejection_ratio,r.average_queue,s=95,label=mode)
        ax.annotate(mode,(r.rejection_ratio,r.average_queue),xytext=(6,4),textcoords='offset points',fontsize=8)
    ax.set(xlabel='Mean rejected fraction (lower is better)',ylabel='Mean queue occupancy (lower is better)',
           title='Reliability vs backlog: lower left is preferred')
    ax.grid(alpha=.2);fig.tight_layout();fig.savefig(file,dpi=200);plt.close(fig)

def solver_diagnostics(out,backend):
    """Objective/feasibility on increasingly long horizons, not optimizer convergence."""
    records=[]
    for n in [3,5,8,12,16,20]:
        cfg=replace(Config(),horizon=n)
        trace=make_trace(n,seed=982)
        g=trace['gain'].copy();l=trace['arrival'];H=trace['harvest']
        tic=time.perf_counter()
        try:
            sol=(solve_cvxpy if backend=='cvxpy' else solve_lp)(12,7,g,l,H,cfg)
            residual=max(verify_plan(sol,12,7,g,l,H,cfg).values())
            records.append(dict(horizon=n,objective=sol['objective'],objective_per_slot=sol['objective']/n,
                                max_violation=residual,solve_seconds=time.perf_counter()-tic,status=sol['status']))
        except Exception as exc:
            records.append(dict(horizon=n,objective=np.nan,objective_per_slot=np.nan,
                               max_violation=np.nan,solve_seconds=np.nan,status=str(exc)))
    df=pd.DataFrame(records);df.to_csv(out/'horizon_diagnostics.csv',index=False)
    for metric,ylabel in [('objective_per_slot','Objective / horizon (not convergence)'),
                          ('solve_seconds','Solver wall time (seconds)'),
                          ('max_violation','Worst planned constraint violation')]:
        fig,ax=plt.subplots(figsize=(6.5,4))
        ax.plot(df.horizon,df[metric],marker='o');ax.set(xlabel='Planning horizon (slots)',ylabel=ylabel)
        if metric=='max_violation':ax.set_yscale('symlog',linthresh=1e-9)
        ax.grid(alpha=.25);fig.tight_layout();fig.savefig(out/f'horizon_{metric}.png',dpi=200);plt.close(fig)
    return df

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--study',choices=['all','multiseed','forecast','horizon','stress','diagnostics'],default='all')
    ap.add_argument('--backend',choices=['cvxpy','lp'],default='cvxpy')
    ap.add_argument('--seeds',type=int,default=10)
    ap.add_argument('--slots',type=int,default=120)
    ap.add_argument('--horizon',type=int,default=10)
    ap.add_argument('--predictor',choices=['causal','oracle_noisy'],default='causal')
    ap.add_argument('--out',default='results/research')
    args=ap.parse_args()
    if args.seeds<2:raise ValueError('Use at least 2 seeds for uncertainty intervals')
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    studies={'multiseed':[(2.5,1.1,.4,args.horizon)],
             'forecast':[(2.5,1.1,v,args.horizon) for v in [0.1,.3,.6,1.0]],
             'horizon':[(2.5,1.1,.4,v) for v in [5,10,15,20]],
             'stress':[(a,h,.4,args.horizon) for a in [2.,2.5,3.] for h in [.6,1.1,1.6]]}
    if args.predictor=='causal' and args.study in ('forecast','all'):
        print('NOTE: oracle-noise sweeps cannot affect causal forecasts; forecast sweep runs oracle_noisy for diagnostic purposes.')
    if args.study=='diagnostics':
        print(solver_diagnostics(out,args.backend).to_string(index=False));return
    names=list(studies) if args.study=='all' else [args.study]
    for study in names:
        rows=[]; t0=time.perf_counter()
        for arrival,harvest,noise,horizon in studies[study]:
            pred='oracle_noisy' if study=='forecast' else args.predictor
            for seed in range(args.seeds):
                rows.extend(run_case(seed+100, args.slots, args.backend,horizon,noise,
                                     arrival,harvest,pred,METHODS))
        df=pd.DataFrame(rows);df.to_csv(out/f'{study}_raw_{args.backend}.csv',index=False)
        group_keys={'multiseed':['mode'], 'forecast':['mode','noise'],
                    'horizon':['mode','horizon'],
                    'stress':['mode','arrival_mean','harvest_mean']}[study]
        means=(df.groupby(group_keys).agg(
            mean_queue=('average_queue','mean'),sd_queue=('average_queue','std'),
            mean_drop=('rejection_ratio','mean'),sd_drop=('rejection_ratio','std'),
            mean_energy=('energy_J','mean'),mean_throughput=('throughput_bps','mean'),
            worst_feasibility=('max_planned_violation','max'),
            avg_solve_ms=('mean_solve_ms','mean'),
            inaccurate_fraction=('inaccurate_fraction','mean')).reset_index())
        means.to_csv(out/f'{study}_summary_{args.backend}.csv',index=False)
        xcols={'multiseed':['arrival_mean'],'forecast':['noise'],'horizon':['horizon'],'stress':['arrival_mean','harvest_mean']}[study]
        paired_intervals(df,xcols).to_csv(out/f'{study}_paired_ci_{args.backend}.csv',index=False)
        plot_pareto(df,out/f'{study}_queue_vs_drop_{args.backend}.png')
        if study=='stress':
            for metric, lab in [('rejection_ratio','Rejection fraction'),('average_queue','Mean queue')]:
                fig,axes=plt.subplots(1,3,figsize=(12.5,4.0),sharey=True)
                for ax,a in zip(axes,[2.,2.5,3.]):
                    sl=df[np.isclose(df.arrival_mean,a)]
                    for mode in METHODS:
                        ss=sl[sl['mode']==mode]
                        gg=ss.groupby('harvest_mean')[metric].agg(['mean','std','count']).reset_index()
                        error=(gg['std']/np.sqrt(gg['count'])).fillna(0)*1.96
                        ax.errorbar(gg.harvest_mean,gg['mean'],yerr=error,marker='o',capsize=2,label=mode)
                    ax.set(title=f'Arrival mean = {a}',xlabel='Mean harvest (J/slot)')
                    ax.grid(alpha=.2)
                axes[0].set_ylabel(lab);axes[-1].legend(fontsize=7)
                fig.tight_layout();fig.savefig(out/f'stress_{metric}_{args.backend}.png',dpi=200);plt.close(fig)
        if study=='forecast':
            plot_metric(df,'noise','rejection_ratio','Rejection fraction',out/f'{study}_rejection_{args.backend}.png')
            plot_metric(df,'noise','average_queue','Mean queue (packets)',out/f'{study}_queue_{args.backend}.png')
        if study=='horizon':
            plot_metric(df,'horizon','average_queue','Mean queue (packets)',out/f'{study}_queue_{args.backend}.png')
            plot_metric(df,'horizon','mean_solve_ms','Mean solve time (ms)',out/f'{study}_runtime_{args.backend}.png')
        print('\n',study,'elapsed',round(time.perf_counter()-t0,1),'seconds')
        print(means.to_string(index=False,float_format=lambda v:f'{v:.5f}'))
    if args.study=='all':
        print('\nHorizon sensitivity diagnostics (NOT mathematical solver convergence):')
        print(solver_diagnostics(out,args.backend).to_string(index=False))

if __name__=='__main__':main()
