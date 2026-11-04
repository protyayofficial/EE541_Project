"""Proposal-aligned uncertainty-aware weighted convex MPC study.
All online methods use identical service/admission rules and observed inputs.
"""
import argparse, hashlib, json, time
from dataclasses import replace
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import t as student_t
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from src.course_data import sources,load_solar
from src.experiment import make_trace
from src.scheduling import Config,capacity,solve_cvxpy

METHODS=('greedy','fixed_fraction','nominal','fixed_margin','adaptive_channel','adaptive_arrival','adaptive_harvest','adaptive_all')
FILES=('data/arco/dataset.csv','data/umass/homeC-generation.tar.gz','data/nrel/723170TYA.CSV')

def raw_forecasts(history,gain,horizon):
    """AR channel median and causal means for arrivals and harvested energy."""
    pg=np.asarray(history['gain'],float);pa=np.asarray(history['arrival'],float);ph=np.asarray(history['harvest'],float)
    if len(pg)>=12:
        z=np.log(np.maximum(pg[-80:],1e-8));x,y=z[:-1],z[1:];rho=float(np.clip(np.dot(x,y)/(np.dot(x,x)+3.),0.,.95))
    else:rho=0.
    g=np.exp((rho**np.arange(horizon))*np.log(max(gain,1e-8)));g[0]=gain
    a=np.full(horizon,(20.+pa.sum())/(8+len(pa)))
    # Same causal predictor for all optimization variants.
    hmean=float(np.mean(ph[-12:])) if len(ph)>=3 else float((8.8+ph.sum())/(8+len(ph)))
    return g,a,np.full(horizon,hmean)

def margins(error_history,mode):
    if mode=='nominal':return np.zeros(3)
    if mode=='fixed_margin':return np.array([.38,1.,.25])
    # Signed channel-overprediction, arrival-underprediction, harvest-overprediction.
    # Prior fixed warm-up, then the last 50 raw one-step errors. Empirical, not guaranteed.
    result=np.array([.38,1.,.25]) if len(error_history)<12 else np.maximum(0,np.quantile(np.asarray(error_history[-50:]),.8,axis=0))
    if mode=='adaptive_channel':result[1:]=0
    if mode=='adaptive_arrival':result[[0,2]]=0
    if mode=='adaptive_harvest':result[:2]=0
    return result

def apply_margins(g,a,h,m,mode):
    g=g.copy();a=a.copy();h=h.copy()
    if mode!='nominal':
        g[1:]=np.maximum(.01,g[1:]-m[0]);a=np.maximum(0,a+m[1]);h=np.maximum(0,h-m[2])
    return g,a,h

def run(trace,cfg,mode,margin_scale=1.0):
    if mode not in (*METHODS, 'fixed', 'channel', 'adaptive_guard50', 'adaptive_guard75', 'nominal_forced', 'adaptive_forced', 'adaptive_arrival_forced', 'adaptive_harvest_forced'):
        raise ValueError(f'unknown method: {mode}')
    if not np.isfinite(margin_scale) or margin_scale < 0:
        raise ValueError('margin_scale must be finite and nonnegative')
    b,E=12.,7.;history={'gain':[],'arrival':[],'harvest':[]};errors=[];prev=None;rows=[]
    for t in range(len(trace['gain'])):
        gain=float(trace['gain'][t]);arrival=float(trace['arrival'][t]);harvest=float(trace['harvest'][t]);horizon=min(cfg.horizon,len(trace['gain'])-t)
        rawg,rawa,rawh=raw_forecasts(history,gain,horizon)
        forced_modes={'nominal_forced':'nominal','adaptive_forced':'adaptive_all',
                      'adaptive_arrival_forced':'adaptive_arrival','adaptive_harvest_forced':'adaptive_harvest'}
        prediction_mode=forced_modes.get(mode,mode)
        if mode in ('adaptive_guard50','adaptive_guard75'):
            m=margins(errors,'adaptive_harvest')
            threshold=.5 if mode=='adaptive_guard50' else .75
            if E >= threshold*cfg.energy_max:m*=0.
        else:
            m=margins(errors,prediction_mode) if mode not in ('greedy','fixed_fraction','fixed','channel') else np.zeros(3)
        if mode.startswith('adaptive_'):
            m=m*margin_scale
        g,a,h=apply_margins(rawg,rawa,rawh,m,prediction_mode)
        # Lowest possible first-slot rejection under the predicted arrivals.
        # With current gain known, this is a scalar constant, preserving DCP.
        max_power=min(cfg.power_max,E/cfg.tau)
        max_service=min(b,cfg.data_max,float(capacity(max_power,gain,cfg)))
        unavoidable=max(0.,b+a[0]-cfg.buffer_max-max_service)
        drop_cap=min(float(a[0]),unavoidable+1e-6) if mode in forced_modes else None
        tic=time.perf_counter();v=0.;status='heuristic';solver='none';planned_reject=0.
        if mode=='greedy':
            p=min(cfg.power_max,E/cfg.tau) if b>1e-10 else 0.;d=min(b,cfg.data_max,float(capacity(p,gain,cfg)))
            p=min(p,float(np.expm1(np.log(2)*d/cfg.rate_scale)/gain)) if d>0 and gain>0 else 0.
        elif mode in ('fixed','channel'):
            target=1.2 if mode=='fixed' else (2.4 if gain>1.1 else .45)
            p=min(cfg.power_max,target,E/cfg.tau) if b>1e-10 else 0.
            d=min(b,cfg.data_max,float(capacity(p,gain,cfg)))
        elif mode=='fixed_fraction':
            p=min(cfg.power_max,(1.1/cfg.energy_max)*E/cfg.tau) if b>1e-10 else 0.;d=min(b,cfg.data_max,float(capacity(p,gain,cfg)))
        else:
            sol=solve_cvxpy(b,E,g,a,h,cfg,first_slot_drop_cap=drop_cap);v=float(sol['max_violation']);status=sol['status'];solver=sol['solver'];planned_reject=float(sol['o'][0])
            p=float(np.clip(sol['p'][0],0,min(cfg.power_max,E/cfg.tau)))
            d=float(np.clip(sol['d'][0],0,min(b,cfg.data_max,float(capacity(p,gain,cfg)))))
        elapsed=time.perf_counter()-tic
        # For all methods reject only forced overflow after seeing arrivals.
        drop=min(arrival,max(0.,b-d+arrival-cfg.buffer_max));bn=b-d+arrival-drop
        pre=E-p*cfg.tau+harvest;spill=max(0.,pre-cfg.energy_max);en=pre-spill
        if not (-1e-6<=bn<=cfg.buffer_max+1e-6 and -1e-6<=en<=cfg.energy_max+1e-6):raise AssertionError('physical state out of bounds')
        # Previous bounds were computed prior to the current data becoming known.
        covered=(np.nan,np.nan,np.nan);errs=(np.nan,np.nan,np.nan)
        if prev is not None:
            pg,pa,ph,mg,ma,mh=prev
            errs=(pg-gain,arrival-pa,ph-harvest)
            covered=(float(gain>=max(.01,pg-mg)-1e-12),float(arrival<=pa+ma+1e-12),float(harvest>=max(0,ph-mh)-1e-12))
        rows.append(dict(t=t,mode=mode,b=b,E=E,gain=gain,arrivals=arrival,harvest=harvest,p=p,d=d,drop=drop,spill=spill,
          planned_rejection=planned_reject,predicted_unavoidable_rejection=unavoidable,
          planned_excess_rejection=max(0.,planned_reject-unavoidable),energy=p*cfg.tau,throughput_bps=d*cfg.packet_bits/cfg.slot_seconds,solve_ms=elapsed*1000,
          plan_violation=v,solver_status=status,solver_name=solver,margin_gain=m[0],margin_arrival=m[1],margin_harvest=m[2],
          raw_error_gain=errs[0],raw_error_arrival=errs[1],raw_error_harvest=errs[2],covered_gain=covered[0],covered_arrival=covered[1],covered_harvest=covered[2]))
        if prev is not None:errors.append(errs)
        prev=(rawg[1],rawa[1],rawh[1],*m) if horizon>1 else None
        history['gain'].append(gain);history['arrival'].append(arrival);history['harvest'].append(harvest);b,E=bn,en
    return pd.DataFrame(rows)

def selected_windows(slots,dev,validation):
    for name,seconds,windows in sources(slots,dev+validation):
        if name=='arco':
            solar=load_solar(FILES[0]);aug=[]
            for j,day in enumerate(pd.date_range('2018-08-01','2018-08-25',freq='D')):
                start=day+pd.Timedelta(hours=[8,12,17,21][j%4]);p=solar.reindex(pd.date_range(start,periods=slots,freq='min'))
                if p.notna().all():aug.append((str(start),p.to_numpy()*.01))
            windows=windows[:dev]+aug[:validation]
        if len(windows)<dev+validation:raise ValueError(f'Not enough {name} windows')
        yield name,seconds,windows[:dev+validation]

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--development',type=int,default=6);ap.add_argument('--validation',type=int,default=4);ap.add_argument('--slots',type=int,default=60);ap.add_argument('--horizon',type=int,default=10);ap.add_argument('--out',default='results/proposal_course');args=ap.parse_args()
    if min(args.development,args.validation,args.slots)<2 or args.horizon<2:ap.error('splits/slots >=2 and horizon >=2 required')
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True);rows=[];frames=[]
    settings=vars(args)|{'methods':METHODS,'dataset_sha256':{f:hashlib.sha256(Path(f).read_bytes()).hexdigest() for f in FILES},
      'objective':'sum backlog + 35*planned rejection + .15*transmit energy + 6*terminal backlog',
      'margin':'80th percentile of last 50 raw signed one-step forecast errors after 12-score warm-up; zero-floor; no formal coverage guarantee',
      'split':'first six source windows then four other dates; ARCO validation uses August',
      'limitations':'simulated channel and traffic; solar values converted by assumed proxy factors; NREL TMY stitched and hourly; not an untouched test relative to all prior exploration'}
    (out/'settings.json').write_text(json.dumps(settings,indent=2)+'\n')
    for name,seconds,windows in selected_windows(args.slots,args.development,args.validation):
      for j,(start,harvest) in enumerate(windows):
        split='development' if j<args.development else 'validation';seed=700+j
        trace=make_trace(args.slots,seed,arrival_mean=2.5,harvest_mean=1.1);trace['harvest']=harvest
        cfg=replace(Config(),horizon=args.horizon,slot_seconds=seconds)
        for mode in METHODS:
          print(name,split,start,mode,flush=True);df=run(trace,cfg,mode)
          terminal=float(df.b.iloc[-1]-df.d.iloc[-1]+df.arrivals.iloc[-1]-df['drop'].iloc[-1]);a=float(df.arrivals.sum())
          row=dict(dataset=name,split=split,window=start,seed=seed,mode=mode,queue=df.b.mean(),drop_ratio=df['drop'].sum()/max(1,a),
             throughput=df.throughput_bps.mean(),energy=df.energy.sum(),terminal_queue=terminal,
             realized_cost=float(df.b.sum()+cfg.drop_weight*df['drop'].sum()+cfg.energy_weight*df.energy.sum()+cfg.terminal_weight*terminal),max_violation=df.plan_violation.max(),
             inaccurate=int((df.solver_status=='optimal_inaccurate').sum()),mean_solve_ms=df.solve_ms.mean(),
             covered_gain=df.covered_gain.mean(),covered_arrival=df.covered_arrival.mean(),covered_harvest=df.covered_harvest.mean())
          rows.append(row);df['dataset']=name;df['split']=split;df['window']=start;frames.append(df)
          pd.DataFrame(rows).to_csv(out/'partial_windows.csv',index=False)
        pd.concat(frames,ignore_index=True).to_csv(out/'partial_slots.csv',index=False)
    raw=pd.DataFrame(rows);raw.to_csv(out/'per_window.csv',index=False);pd.concat(frames,ignore_index=True).to_csv(out/'per_slot.csv',index=False)
    raw.groupby(['dataset','split','mode'])[['queue','drop_ratio','energy','throughput','terminal_queue','realized_cost','covered_gain','covered_arrival','covered_harvest']].agg(['mean','std']).to_csv(out/'summary.csv')
    pairs=[]
    for (dataset,split),part in raw.groupby(['dataset','split']):
      base=part[part['mode']=='nominal'].set_index('window')
      for mode in METHODS:
       if mode=='nominal':continue
       candidate=part[part['mode']==mode].set_index('window')
       for metric in ('queue','drop_ratio','energy','throughput','terminal_queue','realized_cost'):
        diff=(candidate[metric]-base[metric]).dropna();n=len(diff);mu=diff.mean();half=student_t.ppf(.975,n-1)*diff.std(ddof=1)/np.sqrt(n)
        pairs.append(dict(dataset=dataset,split=split,method=mode,metric=metric,n=n,delta=mu,ci_low=mu-half,ci_high=mu+half))
    pd.DataFrame(pairs).to_csv(out/'paired_vs_nominal.csv',index=False)
    for metric,label in [('drop_ratio','Rejection fraction'),('queue','Average queue (packet equivalents)'),('terminal_queue','Final queue (packet equivalents)'),('energy','Transmission energy (J)'),('realized_cost','Realized weighted cost')]:
      fig,axs=plt.subplots(1,3,figsize=(16,5))
      for ax,(dataset,group) in zip(axs,raw[raw.split=='validation'].groupby('dataset')):
        m=group.groupby('mode')[metric].mean().reindex(METHODS);ax.barh(m.index,m.values);ax.set(title=dataset,xlabel=label);ax.grid(axis='x',alpha=.2)
      fig.tight_layout();fig.savefig(out/f'{metric}.png',dpi=180);plt.close(fig)
    print(raw.groupby(['dataset','split','mode'])[['queue','drop_ratio','energy','terminal_queue']].mean().to_string())
    print('max violation',raw.max_violation.max(),'inaccurate',raw.inaccurate.sum())
if __name__=='__main__':main()
