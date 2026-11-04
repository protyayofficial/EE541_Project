"""Matched evaluation on disjoint real solar-proxy windows; channel/traffic synthetic."""
import argparse,hashlib,json,platform,sys,time
from dataclasses import replace
from pathlib import Path
import numpy as np,pandas as pd
from scipy.stats import t
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from src.course_data import sources,load_solar
from src.experiment import make_trace
from src.scheduling import Config
from proposal_study import run,FILES
from final_evaluation import evaluate

MODES=('fixed','channel','greedy','nominal','fixed_margin','adaptive_harvest','adaptive_all')
def get_windows(slots,count):
    solar=load_solar(FILES[0]);ar=[]
    # Same dates may be used elsewhere, but these 80-minute intervals start
    # at different hours and do not overlap earlier project solar windows.
    for j,day in enumerate(pd.date_range('2018-08-01','2018-08-28')):
        start=day+pd.Timedelta(hours=[6,10,14,19][j%4]);part=solar.reindex(pd.date_range(start,periods=slots,freq='min'))
        if part.notna().all():ar.append((str(start),part.to_numpy()*.01))
        if len(ar)>=count:break
    yield 'arco',60.,ar
    for name,seconds,wins in sources(slots,30+count):
        if name=='umass_home_c':yield name,seconds,wins[30:30+count]
    # July block of the stitched typical year, disjoint from earlier April blocks.
    raw=pd.read_csv(FILES[2],skiprows=1);x=pd.to_numeric(raw['GHI (W/m^2)'],errors='coerce').clip(lower=0).to_numpy();n=[]
    for j in range(count):
        start=24*200+j*max(slots,96);part=x[start:start+slots]
        if len(part)==slots and np.isfinite(part).all():n.append((f'tmy_hour_index_{start}',part*.005))
    yield 'nrel_tmy3',3600.,n

def main():
    p=argparse.ArgumentParser();p.add_argument('--windows',type=int,default=10);p.add_argument('--slots',type=int,default=80);p.add_argument('--horizon',type=int,default=10);p.add_argument('--out',default='results/final_evaluation/solar');a=p.parse_args()
    if min(a.windows,a.slots,a.horizon)<2 or a.slots>120:p.error('windows,slots,horizon >=2; slots <=120 to preserve nonoverlap')
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True);rows=[];frames=[]
    settings=vars(a)|{'modes':MODES,'dataset_sha256':{f:hashlib.sha256(Path(f).read_bytes()).hexdigest() for f in FILES},
      'selection':'ARCO alternating 06,10,14,19 starts, UMass after first 30 windows, TMY3 later year index; nonoverlap of logged intervals with earlier episode windows',
      'caveat':'one source per dataset; windows in same dates/season can be correlated and were not prospectively preregistered; energy conversion is assumed, traffic and channel synthetic; TMY is stitched and hourly',
      'arrival':'Poisson mean 2.5 clipped at 10','scales':{'arco':.01,'umass_home_c':.1,'nrel_tmy3':.005},'python':sys.version,'platform':platform.platform()}
    (out/'settings.json').write_text(json.dumps(settings,indent=2)+'\n')
    for dataset,slot,wins in get_windows(a.slots,a.windows):
      if len(wins)<a.windows:raise ValueError(f'{dataset}: only {len(wins)} valid windows')
      cfg=replace(Config(),horizon=a.horizon,slot_seconds=slot)
      for j,(start,h) in enumerate(wins):
        seed=7000+j;generated=make_trace(a.slots,seed,arrival_mean=2.5,harvest_mean=1.1)
        # Discard unused oracle-aided forecast fields from the trace generator.
        tr={k:generated[k] for k in ('gain','arrival','harvest')}
        tr['arrival']=np.minimum(tr['arrival'],10.);tr['harvest']=h
        for mode in MODES:
          print(dataset,start,'seed',seed,mode,flush=True);tic=time.perf_counter();df=run(tr,cfg,mode)
          rows.append(evaluate(df,cfg)|dict(dataset=dataset,window=start,seed=seed,mode=mode,slot_seconds=slot,wall_seconds=time.perf_counter()-tic))
          df=df.copy();df['dataset']=dataset;df['window']=start;df['seed']=seed;frames.append(df)
          pd.DataFrame(rows).to_csv(out/'partial_windows.csv',index=False)
        pd.concat(frames,ignore_index=True).to_csv(out/'partial_slots.csv',index=False)
    raw=pd.DataFrame(rows);raw.to_csv(out/'per_window.csv',index=False);pd.concat(frames,ignore_index=True).to_csv(out/'per_slot.csv',index=False)
    metrics=['queue','drop_ratio','energy','throughput','terminal_queue','realized_cost','coverage_gain','coverage_arrival','coverage_harvest','mean_solve_ms']
    raw.groupby(['dataset','mode'])[metrics].agg(['mean','std']).to_csv(out/'summary.csv')
    pairs=[]
    for dataset,g in raw.groupby('dataset'):
      base=g[g['mode']=='nominal'].set_index('window')
      for mode in MODES:
        if mode=='nominal':continue
        comp=g[g['mode']==mode].set_index('window')
        for metric in ('queue','drop_ratio','energy','throughput','terminal_queue','realized_cost'):
          dif=(comp[metric]-base[metric]).dropna();n=len(dif);mu=dif.mean();half=t.ppf(.975,n-1)*dif.std(ddof=1)/np.sqrt(n)
          pairs.append(dict(dataset=dataset,method=mode,metric=metric,n=n,delta=mu,ci_low=mu-half,ci_high=mu+half))
    pd.DataFrame(pairs).to_csv(out/'paired_vs_nominal.csv',index=False)
    for metric,label in [('realized_cost','Realized weighted cost'),('drop_ratio','Rejected fraction'),('queue','Mean queue (packets)'),('energy','Transmit energy (J)')]:
      fig,axs=plt.subplots(1,3,figsize=(15,4),layout='constrained')
      for ax,(dataset,group) in zip(axs,raw.groupby('dataset')):
        values=group.groupby('mode')[metric].mean().reindex(MODES);ax.barh(values.index,values.values);ax.set(title=dataset,xlabel=label);ax.grid(axis='x',alpha=.2)
      fig.savefig(out/f'{metric}.png',dpi=180);plt.close(fig)
    print(raw.groupby(['dataset','mode'])[['realized_cost','drop_ratio','queue','energy']].mean().to_string());print('max violation',raw.max_violation.max(),'inaccurate',raw.inaccurate.sum())
if __name__=='__main__':main()
