"""Predeclare candidate margin scales, choose on development, test on fresh windows."""
import argparse,hashlib,json,time
from pathlib import Path
from dataclasses import replace
import numpy as np
import pandas as pd
from scipy.stats import t as student_t
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from src.scheduling import Config
from src.experiment import make_trace
from src.course_data import sources,load_solar
from proposal_study import run, METHODS, FILES

CANDIDATES={'all_025':('adaptive_all',.25),'all_050':('adaptive_all',.5),
            'all_100':('adaptive_all',1.),'arrival_050':('adaptive_arrival',.5),
            'arrival_100':('adaptive_arrival',1.),'harvest_050':('adaptive_harvest',.5),
            'harvest_100':('adaptive_harvest',1.)}

def study_windows(slots):
    out=[]
    for name,seconds,windows in sources(slots,18):
        if len(windows)<18:raise ValueError(f'{name} has fewer than 18 complete windows')
        if name=='arco':
            s=load_solar(FILES[0]);aug=[]
            for j,day in enumerate(pd.date_range('2018-08-01','2018-08-28',freq='D')):
                start=day+pd.Timedelta(hours=[8,12,17,21][j%4]);p=s.reindex(pd.date_range(start,periods=slots,freq='min'))
                if p.notna().all():aug.append((str(start),p.to_numpy()*.01))
            # Aug 1-4 in proposal_final; Aug 5-8 in earlier horizon comparison.
            if len(aug)<12:raise ValueError('not enough ARCO August windows')
            new=aug[8:12]
        else:new=windows[14:18]
        out.append((name,seconds,windows[:6],new))
    return out

def evaluate(trace,cfg,mode,scale):
    d=run(trace,cfg,mode,margin_scale=scale);terminal=float(d.b.iloc[-1]-d.d.iloc[-1]+d.arrivals.iloc[-1]-d['drop'].iloc[-1])
    stats={'queue':float(d.b.mean()),'drop_ratio':float(d['drop'].sum()/max(1,d.arrivals.sum())),
        'energy':float(d.energy.sum()),'terminal_queue':terminal,'throughput':float(d.throughput_bps.mean()),
        'realized_cost':float(d.b.sum()+cfg.drop_weight*d['drop'].sum()+cfg.energy_weight*d.energy.sum()+cfg.terminal_weight*terminal),
        'max_violation':float(d.plan_violation.max()),'inaccurate':int((d.solver_status=='optimal_inaccurate').sum()),'solve_ms':float(d.solve_ms.mean())}
    return d,stats

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',default='results/proposal_tuned');p.add_argument('--slots',type=int,default=60);p.add_argument('--horizon',type=int,default=10);args=p.parse_args()
    if args.slots!=60 or args.horizon!=10:p.error('selection is matched to existing 60-slot, 10-horizon development reference')
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True);data=study_windows(args.slots)
    original=Path('results/proposal_final');orig_settings=json.loads((original/'settings.json').read_text());ref=pd.read_csv(original/'per_window.csv')
    if orig_settings['slots']!=args.slots or orig_settings['horizon']!=args.horizon:raise ValueError('reference settings mismatch')
    hashes={f:hashlib.sha256(Path(f).read_bytes()).hexdigest() for f in FILES}
    if hashes!=orig_settings['dataset_sha256']:raise ValueError('dataset checksum mismatch with development reference')
    settings=vars(args)|{'candidates':CANDIDATES,'selection':'equal source average of candidate mean realized proposal cost divided by nominal mean realized cost on the same development windows; lower is better',
        'development_windows_per_source':6,'new_windows_per_source':4,'nominal_reference':'results/proposal_final/per_window.csv','dataset_sha256':hashes,
        'caution':'small matched windows, proxy energy conversions, TMY3 stitched; no guaranteed superiority or uncertainty coverage'}
    (out/'settings.json').write_text(json.dumps(settings,indent=2)+'\n');dev=[]
    for dataset,seconds,windows,_ in data:
      for j,(start,harvest) in enumerate(windows):
        seed=700+j;trace=make_trace(args.slots,seed,arrival_mean=2.5,harvest_mean=1.1);trace['harvest']=harvest;cfg=replace(Config(),horizon=args.horizon,slot_seconds=seconds)
        r=ref[(ref.dataset==dataset)&(ref['split']=='development')&(ref['mode']=='nominal')&(ref.window==start)&(ref.seed==seed)]
        if len(r)!=1:raise ValueError('development nominal trace mismatch')
        for label,(mode,scale) in CANDIDATES.items():
          print('development',dataset,start,label,flush=True);begin=time.perf_counter();_,stats=evaluate(trace,cfg,mode,scale)
          dev.append(stats|dict(dataset=dataset,window=start,seed=seed,candidate=label,reference_cost=float(r.realized_cost.iloc[0]),wall_seconds=time.perf_counter()-begin))
          pd.DataFrame(dev).to_csv(out/'development_partial.csv',index=False)
    d=pd.DataFrame(dev);d.to_csv(out/'development.csv',index=False)
    grouped=d.groupby(['candidate','dataset'])[['realized_cost','reference_cost']].mean();grouped['normalized_cost']=grouped.realized_cost/grouped.reference_cost
    score=grouped.groupby('candidate').normalized_cost.mean().sort_values();score.to_csv(out/'selection_scores.csv',header=True)
    selected=str(score.index[0]);mode,scale=CANDIDATES[selected];(out/'selected.json').write_text(json.dumps({'candidate':selected,'method':mode,'margin_scale':scale,'development_relative_cost':float(score.iloc[0])},indent=2)+'\n')
    print('SELECTED',selected,flush=True);rows=[];frames=[]
    for dataset,seconds,_,windows in data:
      for j,(start,harvest) in enumerate(windows):
        seed=1200+j;trace=make_trace(args.slots,seed,arrival_mean=2.5,harvest_mean=1.1);trace['harvest']=harvest;cfg=replace(Config(),horizon=args.horizon,slot_seconds=seconds)
        for name in (*METHODS,'selected'):
          chosen=mode if name=='selected' else name;strength=scale if name=='selected' else 1.
          print('new',dataset,start,name,flush=True);begin=time.perf_counter();df,stats=evaluate(trace,cfg,chosen,strength)
          rows.append(stats|dict(dataset=dataset,window=start,seed=seed,mode=name,wall_seconds=time.perf_counter()-begin))
          df=df.copy();df['dataset']=dataset;df['window']=start;df['mode']=name;frames.append(df)
          pd.DataFrame(rows).to_csv(out/'new_windows_partial.csv',index=False)
        pd.concat(frames,ignore_index=True).to_csv(out/'new_slots_partial.csv',index=False)
    raw=pd.DataFrame(rows);raw.to_csv(out/'per_window.csv',index=False);pd.concat(frames,ignore_index=True).to_csv(out/'per_slot.csv',index=False)
    raw.groupby(['dataset','mode'])[['queue','drop_ratio','energy','terminal_queue','realized_cost','throughput']].agg(['mean','std']).to_csv(out/'summary.csv')
    pairs=[]
    for dataset,group in raw.groupby('dataset'):
      cand=group[group['mode']=='selected'].set_index('window')
      for name in METHODS:
       base=group[group['mode']==name].set_index('window')
       for metric in ('queue','drop_ratio','energy','terminal_queue','realized_cost','throughput'):
        delta=(cand[metric]-base[metric]).dropna();n=len(delta);mu=delta.mean();half=student_t.ppf(.975,n-1)*delta.std(ddof=1)/np.sqrt(n)
        pairs.append(dict(dataset=dataset,baseline=name,metric=metric,n=n,delta=mu,ci_low=mu-half,ci_high=mu+half))
    pd.DataFrame(pairs).to_csv(out/'paired.csv',index=False)
    for met,label in [('realized_cost','Realized weighted cost'),('drop_ratio','Rejection fraction'),('queue','Average queue'),('energy','Transmission energy (J)'),('terminal_queue','Final queue')]:
      fig,axs=plt.subplots(1,3,figsize=(16,5))
      for ax,(dataset,grp) in zip(axs,raw.groupby('dataset')):
       v=grp.groupby('mode')[met].mean().sort_values();ax.barh(v.index,v.values);ax.set(title=dataset,xlabel=label);ax.grid(axis='x',alpha=.2)
      fig.tight_layout();fig.savefig(out/f'{met}.png',dpi=180);plt.close(fig)
    print('SCORES\n',score.to_string());print('SELECTED',selected)
    print(raw.groupby(['dataset','mode'])[['realized_cost','drop_ratio','queue','energy','terminal_queue']].mean().to_string())
    print('max residual',raw.max_violation.max(),'inaccurate',raw.inaccurate.sum())
if __name__=='__main__':main()
