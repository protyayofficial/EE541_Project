"""Compare convex first-slot rejection-consistency fix on fresh windows."""
import argparse,hashlib,json,time
from pathlib import Path
from dataclasses import replace
import numpy as np,pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from src.course_data import SOURCE_INTERVALS,sources,load_solar
from src.experiment import make_trace
from src.scheduling import Config
from src.radio import simulation_settings
from proposal_study import METHODS,FILES
from tune_proposal import evaluate
from src.packets import append_packet_run,DELAY_MEASURES,paired_stats

FIXES=('nominal_forced','adaptive_forced','adaptive_arrival_forced','adaptive_harvest_forced')
ALL=(*METHODS,*FIXES,'guarded_h15')

def fresh_windows(slots):
 for dataset,seconds,wins in sources(slots,30):
  if dataset=='arco':
   solar=load_solar(FILES[0]);aug=[]
   for j,day in enumerate(pd.date_range('2018-08-01','2018-08-28')):
    start=day+pd.Timedelta(hours=[8,12,17,21][j%4]);v=solar.reindex(pd.date_range(start,periods=slots,freq='min'))
    if v.notna().all():aug.append((str(start),v.to_numpy()*.01))
   if len(aug)<24:raise ValueError('not enough ARCO windows')
   new=aug[20:24]
  else:
   if len(wins)<30:raise ValueError(f'insufficient {dataset} windows')
   new=wins[26:30]
  yield dataset,seconds,new

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--out',default='results/proposal_consistency');ap.add_argument('--slots',type=int,default=60);args=ap.parse_args()
 if args.slots!=60:ap.error('uses 60-slot windows to match preceding studies')
 out=Path(args.out)
 if any((out/name).exists() for name in ('per_slot.csv','per_window.csv','per_packet.csv')):ap.error('choose a fresh --out directory')
 out.mkdir(parents=True,exist_ok=True)
 hashes={f:hashlib.sha256(Path(f).read_bytes()).hexdigest() for f in FILES};original=json.loads(Path('results/proposal_final/settings.json').read_text())
 if hashes!=original['dataset_sha256']:raise ValueError('input hashes differ from earlier experiments')
 settings=vars(args)|simulation_settings(Config())|{'methods':ALL,'dataset_slot_seconds':SOURCE_INTERVALS,'dataset_sha256':hashes,'windows':'four new disjoint windows per source after prior studies',
  'explanation':'o0 <= max(0,b0+forecast_arrivals-buffer_capacity-max_possible_service)+1e-6; max service respects actual channel, buffer, power and energy',
  'warning':'forecast-based cap only; actual arrivals differ; later planned rejection remains unconstrained; not an exact robust guarantee'}
 (out/'settings.json').write_text(json.dumps(settings,indent=2)+'\n');rows=[];frames=[]
 for dataset,seconds,wins in fresh_windows(args.slots):
  for j,(start,h) in enumerate(wins):
   seed=1800+j;tr=make_trace(args.slots,seed,harvest_mean=1.1);tr['harvest']=h
   for label in ALL:
    mode='adaptive_guard75' if label=='guarded_h15' else label;horizon=15 if label=='guarded_h15' else 10
    cfg=replace(Config(),horizon=horizon,slot_seconds=seconds);print(dataset,start,label,flush=True);tic=time.perf_counter()
    df,stats=evaluate(tr,cfg,mode,1.)
    rows.append(stats|dict(dataset=dataset,window=start,seed=seed,mode=label,horizon=horizon,wall_seconds=time.perf_counter()-tic,
      predicted_discretionary_slots=int((df.planned_excess_rejection>1e-3).sum()),
      mean_planned_excess=float(df.planned_excess_rejection.mean())))
    run_id=append_packet_run(df,out,dict(experiment='consistency',dataset=dataset,window=start,seed=seed,mode=label))
    rows[-1]['run_id']=run_id
    df=df.copy();df['dataset']=dataset;df['window']=start;df['mode']=label;df['run_id']=run_id;frames.append(df)
    pd.DataFrame(rows).to_csv(out/'partial_windows.csv',index=False)
   pd.concat(frames,ignore_index=True).to_csv(out/'partial_slots.csv',index=False)
 raw=pd.DataFrame(rows);raw.to_csv(out/'per_window.csv',index=False);pd.concat(frames,ignore_index=True).to_csv(out/'per_slot.csv',index=False)
 metrics=['realized_cost','drop_ratio','queue','terminal_queue','energy','throughput','predicted_discretionary_slots',*DELAY_MEASURES]
 raw.groupby(['dataset','mode'])[metrics].agg(['mean','std','count']).to_csv(out/'summary.csv')
 pairs=[]
 for dataset,group in raw.groupby('dataset'):
  for fix,base in [('nominal_forced','nominal'),('adaptive_forced','adaptive_all'),('adaptive_arrival_forced','adaptive_arrival'),('adaptive_harvest_forced','adaptive_harvest')]:
   a=group[group['mode']==fix].set_index('window');b=group[group['mode']==base].set_index('window')
   for metric in metrics:
    d=a[metric]-b[metric]
    pairs.append(dict(dataset=dataset,fix=fix,baseline=base,metric=metric,**paired_stats(d)))
 pd.DataFrame(pairs).to_csv(out/'paired.csv',index=False)
 for metric,label in [('realized_cost','Realized weighted cost'),('drop_ratio','Rejection fraction'),('queue','Mean queue'),('predicted_discretionary_slots','Slots with forecast-discretionary planned rejection')]:
  fig,axes=plt.subplots(1,3,figsize=(16,6))
  for ax,(dataset,g) in zip(axes,raw.groupby('dataset')):
   values=g.groupby('mode')[metric].mean().sort_values();ax.barh(values.index,values.values);ax.set(title=dataset,xlabel=label);ax.grid(axis='x',alpha=.2)
  fig.tight_layout();fig.savefig(out/f'{metric}.png',dpi=180);plt.close(fig)
 print(raw.groupby(['dataset','mode'])[['realized_cost','drop_ratio','queue','predicted_discretionary_slots',*DELAY_MEASURES]].mean().to_string())
 print('max residual',raw.max_violation.max(),'inaccurate',raw.inaccurate.sum())
if __name__=='__main__':main()
