"""Test battery-gated harvest margins and compare on unused windows."""
import argparse,hashlib,json,time
from pathlib import Path
from dataclasses import replace
import numpy as np,pandas as pd
from scipy.stats import t
from src.scheduling import Config
from src.experiment import make_trace
from src.course_data import sources,load_solar
from proposal_study import METHODS,FILES
from tune_proposal import evaluate,CANDIDATES

def windows_for(slots):
    out=[]
    for name,seconds,windows in sources(slots,22):
        if len(windows)<6:raise ValueError('insufficient development windows')
        if name=='arco':
            solar=load_solar(FILES[0]);aug=[]
            for j,day in enumerate(pd.date_range('2018-08-01','2018-08-28',freq='D')):
                start=day+pd.Timedelta(hours=[8,12,17,21][j%4]);v=solar.reindex(pd.date_range(start,periods=slots,freq='min'))
                if v.notna().all():aug.append((str(start),v.to_numpy()*.01))
            if len(aug)<16:raise ValueError('insufficient ARCO holdout windows')
            new=aug[12:16]
        else:
            if len(windows)<22:raise ValueError(f'{name} insufficient holdout windows')
            new=windows[18:22]
        out.append((name,seconds,windows[:6],new))
    return out

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',default='results/proposal_guarded');ap.add_argument('--slots',type=int,default=60);args=ap.parse_args()
    if args.slots!=60:ap.error('study uses 60-slot development reference')
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True);data=windows_for(args.slots)
    original_settings=json.loads(Path('results/proposal_final/settings.json').read_text())
    hashes={f:hashlib.sha256(Path(f).read_bytes()).hexdigest() for f in FILES}
    if hashes!=original_settings['dataset_sha256']:raise ValueError('dataset checksum mismatch')
    settings=vars(args)|{'dataset_sha256':hashes,'development_reference':'results/proposal_tuned/development.csv',
        'development_reference_sha256':hashlib.sha256(Path('results/proposal_tuned/development.csv').read_bytes()).hexdigest(),
        'score':'mean across datasets of mean candidate cost divided by matched mean nominal cost',
        'new_windows':'ARCO next August windows, other sources next nonoverlapping windows; four per source',
        'caution':'guard proposed after earlier exploratory results; only new windows are reserved for this comparison'}
    (out/'settings.json').write_text(json.dumps(settings,indent=2)+'\n')
    prior=pd.read_csv('results/proposal_tuned/development.csv');ref=pd.read_csv('results/proposal_final/per_window.csv');rows=[]
    for name,seconds,windows,_ in data:
      for j,(start,harvest) in enumerate(windows):
        seed=700+j;tr=make_trace(args.slots,seed,arrival_mean=2.5,harvest_mean=1.1);tr['harvest']=harvest;cfg=replace(Config(),horizon=10,slot_seconds=seconds)
        r=ref[(ref.dataset==name)&(ref['split']=='development')&(ref['mode']=='nominal')&(ref.window==start)&(ref.seed==seed)]
        if len(r)!=1:raise ValueError('development mismatch')
        for mode in ('adaptive_guard50','adaptive_guard75'):
          print('development',name,start,mode,flush=True);tic=time.perf_counter();_,stats=evaluate(tr,cfg,mode,1.)
          rows.append(stats|dict(dataset=name,window=start,seed=seed,candidate=mode,reference_cost=float(r.realized_cost.iloc[0]),wall_seconds=time.perf_counter()-tic))
          pd.DataFrame(rows).to_csv(out/'development_partial.csv',index=False)
    d=pd.concat([prior,pd.DataFrame(rows)],ignore_index=True);d.to_csv(out/'development.csv',index=False)
    g=d.groupby(['candidate','dataset'])[['realized_cost','reference_cost']].mean();g['ratio']=g.realized_cost/g.reference_cost
    scores=g.groupby('candidate').ratio.mean().sort_values();scores.to_csv(out/'selection_scores.csv',header=True);chosen=str(scores.index[0])
    mapping=CANDIDATES|{'adaptive_guard50':('adaptive_guard50',1.),'adaptive_guard75':('adaptive_guard75',1.)};mode,scale=mapping[chosen]
    (out/'selected.json').write_text(json.dumps({'candidate':chosen,'method':mode,'scale':scale,'development_relative_cost':float(scores.iloc[0])},indent=2)+'\n')
    print('SELECTED',chosen,flush=True);records=[];frames=[]
    for name,seconds,_,wins in data:
      for j,(start,harvest) in enumerate(wins):
        seed=1400+j;tr=make_trace(args.slots,seed,arrival_mean=2.5,harvest_mean=1.1);tr['harvest']=harvest;cfg=replace(Config(),horizon=10,slot_seconds=seconds)
        for label in (*METHODS,'selected'):
            usemode=mode if label=='selected' else label;strength=scale if label=='selected' else 1.
            print('new',name,start,label,flush=True);tic=time.perf_counter();df,stats=evaluate(tr,cfg,usemode,strength)
            records.append(stats|dict(dataset=name,window=start,seed=seed,mode=label,wall_seconds=time.perf_counter()-tic));df=df.copy();df['dataset']=name;df['window']=start;df['mode']=label;frames.append(df)
            pd.DataFrame(records).to_csv(out/'new_windows_partial.csv',index=False)
        pd.concat(frames,ignore_index=True).to_csv(out/'new_slots_partial.csv',index=False)
    raw=pd.DataFrame(records);raw.to_csv(out/'per_window.csv',index=False);pd.concat(frames,ignore_index=True).to_csv(out/'per_slot.csv',index=False)
    raw.groupby(['dataset','mode'])[['queue','drop_ratio','energy','terminal_queue','realized_cost','throughput']].agg(['mean','std']).to_csv(out/'summary.csv')
    comparisons=[]
    for name,group in raw.groupby('dataset'):
      cand=group[group['mode']=='selected'].set_index('window')
      for baseline in METHODS:
        base=group[group['mode']==baseline].set_index('window')
        for metric in ('queue','drop_ratio','energy','terminal_queue','realized_cost','throughput'):
            v=(cand[metric]-base[metric]).dropna();n=len(v);m=v.mean();half=t.ppf(.975,n-1)*v.std(ddof=1)/np.sqrt(n)
            comparisons.append(dict(dataset=name,baseline=baseline,metric=metric,n=n,delta=m,ci_low=m-half,ci_high=m+half))
    pd.DataFrame(comparisons).to_csv(out/'paired.csv',index=False)
    print('SCORES\n',scores.to_string());print('SELECTED',chosen);print(raw.groupby(['dataset','mode'])[['realized_cost','drop_ratio','queue','energy']].mean().to_string());print('max residual',raw.max_violation.max(),'inaccurate',raw.inaccurate.sum())
if __name__=='__main__':main()
