"""Select a proposal-compatible uncertainty rule by worst development scenario.

This is empirical minimax selection over a fixed list, not a mathematical
robust-optimization guarantee. Test windows are disjoint from prior studies.
"""
import argparse,hashlib,json,time
from pathlib import Path
from dataclasses import replace
import numpy as np,pandas as pd
from scipy.stats import t
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from src.course_data import sources,load_solar
from src.experiment import make_trace
from src.scheduling import Config
from proposal_study import METHODS,FILES
from tune_proposal import evaluate

CANDIDATES={'guard50_h10':('adaptive_guard50',1.,10),'guard75_h10':('adaptive_guard75',1.,10),
 'guard75_h15':('adaptive_guard75',1.,15),'guard75_h20':('adaptive_guard75',1.,20),
 'all050_h15':('adaptive_all',.5,15),'all050_h20':('adaptive_all',.5,20),
 'harvest_h15':('adaptive_harvest',1.,15),'harvest_h20':('adaptive_harvest',1.,20),
 'arrival_h15':('adaptive_arrival',1.,15),'arrival_h20':('adaptive_arrival',1.,20)}

def windows_for(slots):
 out=[]
 for name,seconds,windows in sources(slots,26):
  if len(windows)<6:raise ValueError('insufficient development windows')
  if name=='arco':
   solar=load_solar(FILES[0]);aug=[]
   for j,day in enumerate(pd.date_range('2018-08-01','2018-08-28',freq='D')):
    start=day+pd.Timedelta(hours=[8,12,17,21][j%4]);v=solar.reindex(pd.date_range(start,periods=slots,freq='min'))
    if v.notna().all():aug.append((str(start),v.to_numpy()*.01))
   if len(aug)<20:raise ValueError('insufficient previously unused ARCO windows')
   new=aug[16:20]
  else:
   if len(windows)<26:raise ValueError(f'{name}: insufficient previously unused windows')
   new=windows[22:26]
  out.append((name,seconds,windows[:6],new))
 return out

def main():
 p=argparse.ArgumentParser();p.add_argument('--out',default='results/proposal_minimax');p.add_argument('--slots',type=int,default=60);args=p.parse_args()
 if args.slots!=60:p.error('requires matched 60-slot development baseline')
 out=Path(args.out);out.mkdir(parents=True,exist_ok=True);data=windows_for(args.slots)
 base=pd.read_csv('results/proposal_final/per_window.csv');settings0=json.loads(Path('results/proposal_final/settings.json').read_text());hashes={f:hashlib.sha256(Path(f).read_bytes()).hexdigest() for f in FILES}
 if hashes!=settings0['dataset_sha256']:raise ValueError('dataset checksum mismatch')
 settings=vars(args)|{'dataset_sha256':hashes,'candidates':CANDIDATES,'selection':'minimize the worst, across three development datasets, candidate mean realized proposal cost divided by the lowest mean of the eight matched baseline costs on the same dataset','development_per_dataset':6,'new_windows_per_dataset':4,'caveat':'empirical selection among fixed candidates, not robust optimization or a general guarantee; proxy energy and small correlated windows'}
 (out/'settings.json').write_text(json.dumps(settings,indent=2)+'\n');rows=[]
 for name,seconds,wins,_ in data:
  for j,(start,h) in enumerate(wins):
   seed=700+j;trace=make_trace(args.slots,seed,arrival_mean=2.5,harvest_mean=1.1);trace['harvest']=h
   ref=base[(base.dataset==name)&(base['split']=='development')&(base.window==start)&(base.seed==seed)]
   if len(ref)!=len(METHODS) or set(ref['mode'])!=set(METHODS):raise ValueError('mismatched baseline development traces')
   for label,(mode,scale,horizon) in CANDIDATES.items():
    print('development',name,start,label,flush=True);cfg=replace(Config(),horizon=horizon,slot_seconds=seconds);tic=time.perf_counter();_,stats=evaluate(trace,cfg,mode,scale)
    rows.append(stats|dict(dataset=name,window=start,seed=seed,candidate=label,wall_seconds=time.perf_counter()-tic));pd.DataFrame(rows).to_csv(out/'development_partial.csv',index=False)
 d=pd.DataFrame(rows);d.to_csv(out/'development.csv',index=False)
 baseline=base[base['split']=='development'].groupby(['dataset','mode']).realized_cost.mean().groupby('dataset').min()
 means=d.groupby(['candidate','dataset']).realized_cost.mean();ratios=means.div(baseline,level='dataset');score=ratios.groupby('candidate').max().sort_values();score.rename('worst_case_relative_cost').to_csv(out/'selection_scores.csv')
 selected=str(score.index[0]);mode,scale,horizon=CANDIDATES[selected]
 (out/'selected.json').write_text(json.dumps({'candidate':selected,'method':mode,'margin_scale':scale,'horizon':horizon,'worst_development_ratio':float(score.iloc[0])},indent=2)+'\n')
 print('SELECTED',selected,flush=True);records=[];frames=[]
 for name,seconds,_,wins in data:
  for j,(start,h) in enumerate(wins):
   seed=1600+j;trace=make_trace(args.slots,seed,arrival_mean=2.5,harvest_mean=1.1);trace['harvest']=h
   for label in (*METHODS,'selected'):
    chosen=mode if label=='selected' else label;strength=scale if label=='selected' else 1.;n=horizon if label=='selected' else 10;cfg=replace(Config(),horizon=n,slot_seconds=seconds)
    print('new',name,start,label,flush=True);tic=time.perf_counter();df,stats=evaluate(trace,cfg,chosen,strength)
    records.append(stats|dict(dataset=name,window=start,seed=seed,mode=label,horizon=n,wall_seconds=time.perf_counter()-tic));df=df.copy();df['dataset']=name;df['window']=start;df['mode']=label;frames.append(df)
    pd.DataFrame(records).to_csv(out/'new_windows_partial.csv',index=False)
   pd.concat(frames,ignore_index=True).to_csv(out/'new_slots_partial.csv',index=False)
 raw=pd.DataFrame(records);raw.to_csv(out/'per_window.csv',index=False);pd.concat(frames,ignore_index=True).to_csv(out/'per_slot.csv',index=False)
 raw.groupby(['dataset','mode'])[['queue','drop_ratio','energy','terminal_queue','realized_cost','throughput']].agg(['mean','std']).to_csv(out/'summary.csv')
 pairs=[]
 for name,group in raw.groupby('dataset'):
  cand=group[group['mode']=='selected'].set_index('window')
  for baseline_name in METHODS:
   ref=group[group['mode']==baseline_name].set_index('window')
   for metric in ('queue','drop_ratio','energy','terminal_queue','realized_cost','throughput'):
    diff=(cand[metric]-ref[metric]).dropna();n=len(diff);mean=diff.mean();half=t.ppf(.975,n-1)*diff.std(ddof=1)/np.sqrt(n)
    pairs.append(dict(dataset=name,baseline=baseline_name,metric=metric,n=n,delta=mean,ci_low=mean-half,ci_high=mean+half))
 pd.DataFrame(pairs).to_csv(out/'paired.csv',index=False)
 for metric,label in [('realized_cost','Realized weighted cost'),('drop_ratio','Rejection fraction'),('queue','Mean queue'),('terminal_queue','Final queue'),('energy','Transmit energy (J)')]:
  fig,axs=plt.subplots(1,3,figsize=(16,5))
  for ax,(name,g) in zip(axs,raw.groupby('dataset')):
   values=g.groupby('mode')[metric].mean().sort_values();ax.barh(values.index,values.values);ax.set(title=name,xlabel=label);ax.grid(axis='x',alpha=.2)
  fig.tight_layout();fig.savefig(out/f'{metric}.png',dpi=180);plt.close(fig)
 print('DEVELOPMENT SCORE\n',score.to_string());print('SELECTED',selected);print(raw.groupby(['dataset','mode'])[['realized_cost','drop_ratio','queue','energy','terminal_queue']].mean().to_string());print('max violation',raw.max_violation.max(),'inaccurate',raw.inaccurate.sum())
if __name__=='__main__':main()
