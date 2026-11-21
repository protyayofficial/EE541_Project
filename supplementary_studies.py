"""Two fixed supplementary protocols; no tuning or additional traffic sweeps."""
import argparse
from dataclasses import asdict,replace
import json
from pathlib import Path
import platform
import shutil
import sys
import time
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from final_evaluation import DEFAULT_ROOT,evaluate,make_evaluation_trace
from proposal_study import run
from src.forecast_noise import NOISE_MODEL
from src.packets import DELAY_MEASURES,append_packet_run,paired_stats
from src.radio import simulation_settings
from src.scheduling import Config

VERSION='supplementary-v1'
POLICIES=('nominal','adaptive_all')
HARVEST=(.6,1.2)
VALUES={'delay_energy':(.15,15.,150.),'forecast_sensitivity':(0.,.25,.50)}


def planned_runs(study,seeds=10,benchmark_case=False):
    if study not in VALUES or not 1<=seeds<=10:raise ValueError('unknown study or seed count outside 1..10')
    rows=[dict(study=study,harvest_mean=h,seed=seed,mode=mode,study_value=value,
               energy_weight=value if study=='delay_energy' else .15,
               forecast_perturbation=value if study=='forecast_sensitivity' else 0.)
          for h in HARVEST for seed in range(6000,6000+seeds) for mode in POLICIES for value in VALUES[study]]
    if benchmark_case:rows=[r for r in rows if r['harvest_mean']==.6 and r['seed']==6000 and r['mode']=='nominal' and r['study_value']==VALUES[study][1]]
    return rows


def scenario_key(harvest,seed):return f'normalized:harvest={float(harvest):g}:seed={int(seed)}'


def reference_cost(frame):
    return float(frame.b.sum()+35.*frame['drop'].sum()+.15*frame.energy.sum()+6.*frame.b_next.iloc[-1])


def forecast_errors(frame):
    """Post-run truth is evaluation only; lead is measured from decision origin."""
    truth=frame.sort_values('t').actual_gain.to_numpy();rows=[]
    for name,column in (('base','base_channel_forecasts'),('perturbed','perturbed_channel_forecasts'),('planned','planned_channel_forecasts')):
        errors={}
        for r in frame.itertuples(index=False):
            for lead,prediction in enumerate(json.loads(getattr(r,column))):
                if lead:errors.setdefault(lead,[]).append(prediction-truth[r.t+lead])
        for lead,samples in errors.items():
            samples=np.asarray(samples)
            rows.append(dict(forecast_kind=name,decision_lead=lead,samples=len(samples),
                             mae=float(np.mean(np.abs(samples))),rmse=float(np.sqrt(np.mean(samples**2))),
                             evaluation='post_run_true_gain_all_targets'))
    return pd.DataFrame(rows)


def run_case(case,slots=1000,horizon=10):
    cfg=replace(Config(),horizon=horizon,energy_weight=case['energy_weight'])
    trace=make_evaluation_trace(slots,case['seed'],case['harvest_mean'],sigma=.45,mean_normalize=True,rho=.68)
    tic=time.perf_counter()
    frame=run(trace,cfg,case['mode'],forecast_perturbation=case['forecast_perturbation'],
              forecast_scenario=scenario_key(case['harvest_mean'],case['seed']),log_forecasts=True)
    elapsed=time.perf_counter()-tic
    stats=evaluate(frame,cfg)
    admitted=stats['newly_admitted_packets'];completed=stats['newly_acknowledged_packets']
    errors=forecast_errors(frame)
    first=errors[(errors.forecast_kind=='perturbed')&(errors.decision_lead==1)].iloc[0]
    stats.update(common_reference_cost=reference_cost(frame),configured_objective_cost=stats['realized_cost'],
                 newly_completed_fraction=completed/admitted if admitted else np.nan,
                 newly_unfinished_fraction=(admitted-completed)/admitted if admitted else np.nan,
                 future_channel_mae_lead1=first.mae,future_channel_rmse_lead1=first.rmse,
                 future_channel_samples_lead1=int(first.samples),wall_seconds=elapsed,
                 optimization_calls=int((frame.solver_name!='none').sum()))
    return frame,stats,errors


def comparison_tables(raw):
    metrics=['queue','drop_ratio','throughput','energy','terminal_queue','common_reference_cost',
             'configured_objective_cost','newly_completed_fraction','newly_unfinished_fraction',
             'newly_admitted_packets','newly_acknowledged_packets','outstanding_packets',
             'future_channel_mae_lead1','future_channel_rmse_lead1',*DELAY_MEASURES]
    policies=[];conditions=[]
    for (harvest,value),g in raw.groupby(['harvest_mean','study_value']):
        base=g[g['mode']=='nominal'].set_index('seed');comp=g[g['mode']=='adaptive_all'].set_index('seed')
        for metric in metrics:
            policies.append(dict(harvest_mean=harvest,study_value=value,method='adaptive_all',metric=metric,
                                 **paired_stats(comp[metric]-base[metric])))
    baseline=VALUES[str(raw.study.iloc[0])][0]
    for (harvest,mode),g in raw.groupby(['harvest_mean','mode']):
        base=g[g.study_value==baseline].set_index('seed')
        for value,comp in g.groupby('study_value'):
            if value==baseline:continue
            for metric in metrics:
                # Cross-weight objectives are different scoring functions.
                if metric=='configured_objective_cost':continue
                conditions.append(dict(harvest_mean=harvest,mode=mode,study_value=value,baseline_value=baseline,
                    metric=metric,**paired_stats(comp.set_index('seed')[metric]-base[metric])))
    return pd.DataFrame(policies),pd.DataFrame(conditions)


def analyze(directory):
    out=Path(directory);raw=pd.read_csv(out/'per_seed.csv')
    group=['harvest_mean','study_value','mode']
    numeric=[c for c in raw.select_dtypes(include='number') if c not in ('seed',*group)]
    raw.groupby(group)[numeric].agg(['mean','std','count']).to_csv(out/'summary.csv')
    paired,conditions=comparison_tables(raw)
    paired.to_csv(out/'paired_vs_nominal.csv',index=False);conditions.to_csv(out/'paired_vs_baseline.csv',index=False)
    errors=pd.read_csv(out/'forecast_errors.csv')
    errors.groupby(group+['forecast_kind','decision_lead'])[['mae','rmse']].agg(['mean','std','count']).to_csv(out/'forecast_summary.csv')
    study=str(raw.study.iloc[0]);label='w' if study=='delay_energy' else 'a'
    fig,axes=plt.subplots(3,2,figsize=(13,12),squeeze=False)
    for j,harvest in enumerate(HARVEST):
        for mode in POLICIES:
            part=raw[(raw.harvest_mean==harvest)&(raw['mode']==mode)]
            for i,metric in enumerate(('mean_initial_wait_s','mean_ack_completion_delay_s','newly_unfinished_fraction')):
                ax=axes[i,j];g=part.groupby('study_value')
                x=g.energy.mean();y=g[metric].mean();ax.plot(x,y,'o-',label=mode)
                for label_index,value in enumerate(x.index):
                    if np.isfinite(y[value]):
                        cohort=part[part.study_value==value]
                        text=f'{label}={value:g}; valid={cohort[metric].notna().sum()}'
                        if i==2:text+=f"; completed={int(cohort.newly_acknowledged_packets.sum())}/{int(cohort.newly_admitted_packets.sum())}"
                        offset=8+12*label_index if mode=='nominal' else -12*(label_index+1)
                        ax.annotate(text,(x[value],y[value]),xytext=(5,offset),textcoords='offset points',fontsize=7)
                ax.set(title=f'Mean harvest {harvest:g} J',xlabel='Mean run total TX energy (J)',ylabel=metric)
                ax.grid(alpha=.25);ax.legend(fontsize=8)
    fig.suptitle('Completed-observation delays; unfinished admissions shown below; runs are repetitions')
    fig.tight_layout();fig.savefig(out/'delay_energy.png',dpi=150);plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(13,4),squeeze=False)
    for ax,harvest in zip(axes.ravel(),HARVEST):
        for (mode,value),g in errors[(errors.harvest_mean==harvest)&(errors.forecast_kind=='perturbed')].groupby(['mode','study_value']):
            means=g.groupby('decision_lead').rmse.mean()
            ax.plot(means.index,means,'o-',label=f'{mode}, {label}={value:g}')
        ax.set(title=f'Harvest {harvest:g} J; post-run truth scoring',xlabel='Lead from decision origin (intervals)',ylabel='Mean run channel forecast RMSE (1/W)')
        if ax.get_legend_handles_labels()[0]:ax.legend(fontsize=7)
        ax.grid(alpha=.25)
    fig.tight_layout();fig.savefig(out/'channel_forecast_errors.png',dpi=150);plt.close(fig)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('study',choices=VALUES)
    p.add_argument('--seeds',type=int,default=10);p.add_argument('--slots',type=int,default=1000)
    p.add_argument('--horizon',type=int,default=10);p.add_argument('--out');p.add_argument('--plan-only',action='store_true')
    p.add_argument('--benchmark-case',action='store_true',help='one H=.6, seed 6000 nominal case at the middle setting')
    a=p.parse_args()
    if not 1<=a.seeds<=10 or min(a.slots,a.horizon)<2:p.error('seeds 1..10; slots/horizon >=2 required')
    if a.benchmark_case and not a.out:p.error('--benchmark-case requires a separate explicit --out')
    out=Path(a.out or f'{DEFAULT_ROOT}/supplementary/{a.study}')
    if any((out/name).exists() for name in ('per_seed.csv','per_slot.csv','per_packet.csv','partial_slots.csv')):
        p.error('output contains trajectories; choose a fresh directory')
    matrix=planned_runs(a.study,a.seeds,a.benchmark_case);cfg=replace(Config(),horizon=a.horizon)
    settings=vars(a)|simulation_settings(cfg)|dict(supplementary_version=VERSION,study_values=VALUES[a.study],
        seed_ids=list(range(6000,6000+a.seeds)),modes=POLICIES,harvest_means=HARVEST,planned_policy_runs=len(matrix),
        run_configs={str(v):asdict(replace(cfg,energy_weight=v if a.study=='delay_energy' else .15)) for v in VALUES[a.study]},
        common_reference_weights=dict(backlog=1.,drop=35.,energy=.15,terminal=6.),
        forecast_noise=dict(version=NOISE_MODEL,key='model tag, scenario (harvest/seed), decision origin, lead; no policy or amplitude',
             normal='BLAKE2b-128; two open-uniform 53-bit variates; Box-Muller cosine',
             multiplier='exp(a*z-0.5*a*a) for future decision leads >=1, before margins; current input unchanged',
             history='perturbed lead-one base prediction scored at next target only if report observed; available to following decision'),
        baseline_overlap='in each full 120-run matrix, 40 baseline executions reproduce the sigma .45 normalized main nominal/adaptive_all cases; the two studies repeat these same scenarios; not extra independent repetitions',
        statistics='run-level paired seed differences; missing delays excluded with n_valid_pairs; completed cohorts and censoring retained',
        offline='no supplementary offline matrix or identifiable offline delay samples',
        penalties='constant within run; adaptive penalty updates excluded',python=sys.version,platform=platform.platform())
    out.mkdir(parents=True,exist_ok=True)
    if (out/'settings.json').exists():
        old=json.loads((out/'settings.json').read_text())
        for key in ('study','slots','horizon','seed_ids','study_values','run_configs','benchmark_case'):
            if json.dumps(old[key],sort_keys=True)!=json.dumps(settings[key],sort_keys=True):p.error(f'existing plan differs: {key}')
    (out/'settings.json').write_text(json.dumps(settings,indent=2)+'\n')
    pd.DataFrame(matrix).to_csv(out/'run_matrix.csv',index=False)
    if a.plan_only:print(f'Planned {len(matrix)} runs; no policies executed');return
    for case in matrix:
        print(case,flush=True);frame,stats,errors=run_case(case,a.slots,a.horizon)
        identity=case|dict(experiment=a.study)
        stats['config_id']=frame.attrs['packet_run']['config_id']
        run_id=append_packet_run(frame,out,identity)
        for data,name in ((pd.DataFrame([stats|case|dict(run_id=run_id)]),'per_seed.csv'),
                          (frame.assign(**case,run_id=run_id),'partial_slots.csv'),
                          (errors.assign(**case,run_id=run_id),'forecast_errors.csv')):
            data.to_csv(out/name,mode='a',header=not (out/name).exists(),index=False)
    shutil.copyfile(out/'partial_slots.csv',out/'per_slot.csv')
    analyze(out)


if __name__=='__main__':main()
