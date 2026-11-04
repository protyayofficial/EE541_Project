"""Clairvoyant convex reference for the same weighted objective.

The optimizer sees future traces and can proactively reject arrivals; every
feasible forced-overflow online rollout is feasible for this relaxed offline
model. A numerical primal solution is only an approximate reference, not a
certified lower bound; its theoretical optimum is a lower bound.
"""
import argparse,hashlib,json,time
from dataclasses import replace
from pathlib import Path
import numpy as np,pandas as pd
from src.experiment import make_trace
from src.scheduling import Config,solve_cvxpy,verify_plan
from final_evaluation import make_evaluation_trace
from final_solar_evaluation import get_windows

def solve_one(dataset,window,seed,trace,cfg):
    t=time.perf_counter()
    try:
        s=solve_cvxpy(12.,7.,trace['gain'],trace['arrival'],trace['harvest'],cfg)
        row=dict(dataset=dataset,window=window,seed=seed,status=s['status'],solver=s['solver'],objective=s['objective'],
          max_violation=max(verify_plan(s,12.,7.,trace['gain'],trace['arrival'],trace['harvest'],cfg).values()),
          seconds=time.perf_counter()-t,planned_rejection=float(np.sum(s['o'])),terminal_queue=float(s['b'][-1]),error='')
        plan=pd.DataFrame({'t':np.arange(len(trace['gain'])),'gain':trace['gain'],'arrival':trace['arrival'],'harvest':trace['harvest'],
          'p':s['p'],'d':s['d'],'b':s['b'][:-1],'b_next':s['b'][1:],'E':s['E'][:-1],'E_next':s['E'][1:],'o':s['o'],'w':s['w']})
        plan['dataset']=dataset;plan['window']=window;plan['seed']=seed
        return row,plan
    except Exception as exc:
        return dict(dataset=dataset,window=window,seed=seed,status='failed',solver='',objective=np.nan,max_violation=np.nan,
                    seconds=time.perf_counter()-t,planned_rejection=np.nan,terminal_queue=np.nan,error=str(exc)),None

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',default='results/final_evaluation');a=p.parse_args();root=Path(a.root);out=root/'offline';out.mkdir(parents=True,exist_ok=True);rows=[];plans=[]
    sw=json.loads((root/'sweep_normalized/settings.json').read_text());raw=pd.read_csv(root/'sweep_normalized/per_seed.csv')
    for (harvest,sigma,seed),g in raw.groupby(['harvest_mean','channel_sigma','seed']):
        print('synthetic',harvest,sigma,seed,flush=True)
        tr=make_evaluation_trace(sw['slots'],int(seed),sigma,harvest,sw.get('mean_normalize',False));cfg=replace(Config(),horizon=sw['slots'])
        row,plan=solve_one('synthetic',f'{harvest}:{sigma}',int(seed),tr,cfg);row.update(harvest_mean=harvest,channel_sigma=sigma)
        if plan is not None:plans.append(plan)
        rows.append(row);pd.DataFrame(rows).to_csv(out/'partial.csv',index=False)
    ss=json.loads((root/'solar/settings.json').read_text())
    for file,digest in ss['dataset_sha256'].items():
        if hashlib.sha256(Path(file).read_bytes()).hexdigest()!=digest:raise ValueError(f'dataset checksum mismatch: {file}')
    solar=pd.read_csv(root/'solar/per_window.csv');sources={name:(seconds,dict(wins)) for name,seconds,wins in get_windows(ss['slots'],ss['windows'])}
    for (dataset,window),g in solar.groupby(['dataset','window']):
        seed=int(g.seed.iloc[0]);print('solar',dataset,window,seed,flush=True)
        tr=make_trace(ss['slots'],seed,arrival_mean=2.5,harvest_mean=1.1);tr['arrival']=np.minimum(tr['arrival'],10.);tr['harvest']=sources[dataset][1][window]
        cfg=replace(Config(),horizon=ss['slots'],slot_seconds=sources[dataset][0]);row,plan=solve_one(dataset,window,seed,tr,cfg)
        rows.append(row)
        if plan is not None:plans.append(plan)
        pd.DataFrame(rows).to_csv(out/'partial.csv',index=False)
    df=pd.DataFrame(rows);df.to_csv(out/'per_instance.csv',index=False)
    if plans:pd.concat(plans,ignore_index=True).to_csv(out/'plans.csv',index=False)
    comparisons=[]
    for row in df.itertuples(index=False):
        if row.dataset=='synthetic':
            group=raw[(raw.harvest_mean==row.harvest_mean)&(raw.channel_sigma==row.channel_sigma)&(raw.seed==row.seed)]
        else:group=solar[(solar.dataset==row.dataset)&(solar.window==row.window)&(solar.seed==row.seed)]
        for z in group.itertuples(index=False):
            comparisons.append(dict(dataset=row.dataset,window=row.window,seed=row.seed,mode=z.mode,online_cost=z.realized_cost,
                  offline_objective=row.objective,online_minus_offline=z.realized_cost-row.objective,offline_status=row.status))
    c=pd.DataFrame(comparisons);c.to_csv(out/'paired_reference.csv',index=False)
    c.groupby(['dataset','mode'])[['online_minus_offline']].agg(['mean','std','count']).to_csv(out/'summary.csv')
    (out/'settings.json').write_text(json.dumps({'synthetic':'sweep_normalized','solar':'solar','objective':'same weighted cost, full horizon',
       'information':'perfect future channel, arrivals and harvest','admission':'allows proactive rejection; online execution rejects only forced overflow',
       'qualification':'theoretical optimum is a lower bound over forced-only rollouts; numerical primal objective is an approximate reference, not a certified lower bound'},indent=2)+'\n')
    print('instances',len(df),'failures',int((df.status=='failed').sum()),'inaccurate',int((df.status=='optimal_inaccurate').sum()),'max residual',df.max_violation.max())
    print('minimum online-minus-offline',c.online_minus_offline.min())
if __name__=='__main__':main()
