"""Full-horizon deterministic expected-goodput reference.

This continuous mean-state model knows future exogenous inputs and permits
proactive rejection and relaxed future control activation. It is not the expected
objective of a stochastic queue and is not a pathwise bound on realized costs.
"""
import argparse,json,time
from dataclasses import replace
from pathlib import Path
import numpy as np,pandas as pd
from src.experiment import make_trace
from src.scheduling import INITIAL_QUEUE,INITIAL_ENERGY,Config,solve_cvxpy,verify_plan,planned_energy
from src.radio import simulation_settings
from src.auditing import saved_config
from src.channel import condition_at
from final_evaluation import DEFAULT_ROOT,make_evaluation_trace
from final_solar_evaluation import reconstruct_sources

def solve_one(dataset,window,seed,trace,cfg):
    t=time.perf_counter()
    try:
        s=solve_cvxpy(INITIAL_QUEUE,INITIAL_ENERGY,trace['gain'],trace['arrival'],trace['harvest'],cfg)
        row=dict(dataset=dataset,window=window,seed=seed,channel_sigma=cfg.channel_sigma,status=s['status'],solver=s['solver'],objective=s['objective'],
          max_violation=max(verify_plan(s,INITIAL_QUEUE,INITIAL_ENERGY,trace['gain'],trace['arrival'],trace['harvest'],cfg).values()),
          reference_kind='deterministic_expected_goodput',seconds=time.perf_counter()-t,planned_rejection=float(np.sum(s['o'])),terminal_queue=float(s['b'][-1]),error='')
        plan=pd.DataFrame({'t':np.arange(len(trace['gain'])),'gain':trace['gain'],'condition':[condition_at(trace,t) for t in range(len(trace['gain']))],'arrival':trace['arrival'],'harvest':trace['harvest'],
          'u':s['u'],'energy':planned_energy(s,INITIAL_ENERGY,cfg),'expected_received':cfg.success_probability*s['d'],'p':s['p'],'d':s['d'],'b':s['b'][:-1],'b_next':s['b'][1:],'E':s['E'][:-1],'E_next':s['E'][1:],'o':s['o'],'w':s['w']})
        plan['dataset']=dataset;plan['window']=window;plan['seed']=seed;plan['channel_sigma']=cfg.channel_sigma
        return row,plan
    except Exception as exc:
        return dict(dataset=dataset,window=window,seed=seed,channel_sigma=cfg.channel_sigma,status='failed',solver='',objective=np.nan,max_violation=np.nan,
                    reference_kind='deterministic_expected_goodput',seconds=time.perf_counter()-t,planned_rejection=np.nan,terminal_queue=np.nan,error=str(exc)),None

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',default=DEFAULT_ROOT);a=p.parse_args();root=Path(a.root);out=root/'offline';out.mkdir(parents=True,exist_ok=True);rows=[];plans=[]
    sw=json.loads((root/'sweep_normalized/settings.json').read_text());raw=pd.read_csv(root/'sweep_normalized/per_seed.csv')
    if not saved_config(sw).channel_mean_normalize:raise ValueError('offline synthetic reference requires normalized sweep')
    for (harvest,sigma,seed),g in raw.groupby(['harvest_mean','channel_sigma','seed']):
        print('synthetic',harvest,sigma,seed,flush=True)
        tr=make_evaluation_trace(sw['slots'],int(seed),harvest,sigma=sigma,mean_normalize=True,rho=sw['config']['channel_rho'])
        cfg=replace(saved_config(sw),horizon=sw['slots'],channel_sigma=sigma)
        row,plan=solve_one('synthetic',f'harvest_{harvest}_sigma_{sigma}',int(seed),tr,cfg);row.update(harvest_mean=harvest)
        if plan is not None:plans.append(plan)
        rows.append(row);pd.DataFrame(rows).to_csv(out/'partial.csv',index=False)
    ss=json.loads((root/'solar/settings.json').read_text())
    solar=pd.read_csv(root/'solar/per_window.csv');sources=reconstruct_sources(ss)
    for (dataset,window),g in solar.groupby(['dataset','window']):
        seed=int(g.seed.iloc[0]);print('solar',dataset,window,seed,flush=True)
        tr=make_trace(ss['slots'],seed,harvest_mean=1.1);tr['harvest']=sources[dataset][1][window]
        cfg=replace(saved_config(ss),horizon=ss['slots'],slot_seconds=sources[dataset][0]);row,plan=solve_one(dataset,window,seed,tr,cfg)
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
            comparisons.append(dict(dataset=row.dataset,window=row.window,seed=row.seed,channel_sigma=row.channel_sigma,mode=z.mode,online_cost=z.realized_cost,
                  offline_objective=row.objective,online_minus_offline=z.realized_cost-row.objective,offline_status=row.status,reference_kind='deterministic_expected_goodput'))
    c=pd.DataFrame(comparisons);c.to_csv(out/'paired_reference.csv',index=False)
    c.groupby(['dataset','channel_sigma','mode'])[['online_minus_offline']].agg(['mean','std','count']).to_csv(out/'summary.csv')
    (out/'settings.json').write_text(json.dumps(simulation_settings(saved_config(sw))|{'synthetic':'sweep_normalized','solar':'solar','objective':'same weighted cost, full horizon',
       'dataset_slot_seconds':ss.get('dataset_slot_seconds',{}),
       'reference_horizon':'full episode, independent of online Config.horizon',
       'delay_measurement_applicability':'online execution only; continuous reference has no identifiable packet-delay samples',
       'source_slot_counts':{'synthetic':sw['slots'],'solar':ss['slots']},
       'online_mpc_horizon':{'synthetic':sw['horizon'],'solar':ss['horizon']},
       'solar_window_selection_version':ss['window_selection_version'],
       'information':'perfect future channel, arrivals and harvest','admission':'allows proactive rejection; online execution rejects only forced overflow',
       'qualification':'deterministic expected-goodput mean-state reference, not a pathwise bound or the expected stochastic online objective; differences against realized costs are descriptive only'},indent=2)+'\n')
    print('instances',len(df),'failures',int((df.status=='failed').sum()),'inaccurate',int((df.status=='optimal_inaccurate').sum()),'max residual',df.max_violation.max())
    print('minimum online-minus-offline',c.online_minus_offline.min())
if __name__=='__main__':main()
