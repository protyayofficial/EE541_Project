"""Compute realized proposal objective and paired comparisons from saved rollout."""
import argparse
from pathlib import Path
import numpy as np,pandas as pd
from scipy.stats import t
from src.scheduling import Config
from proposal_study import METHODS
p=argparse.ArgumentParser();p.add_argument('directory');out=Path(p.parse_args().directory)
raw=pd.read_csv(out/'per_window.csv');slots=pd.read_csv(out/'per_slot.csv');cfg=Config()
agg=slots.groupby(['dataset','split','window','mode']).agg(sum_b=('b','sum'),sum_drop=('drop','sum'),sum_energy=('energy','sum')).reset_index()
raw=raw.drop(columns=['realized_cost'],errors='ignore').merge(agg,on=['dataset','split','window','mode'],validate='one_to_one')
raw['realized_cost']=raw.sum_b+cfg.drop_weight*raw.sum_drop+cfg.energy_weight*raw.sum_energy+cfg.terminal_weight*raw.terminal_queue
raw=raw.drop(columns=['sum_b','sum_drop','sum_energy']);raw.to_csv(out/'per_window.csv',index=False)
raw.groupby(['dataset','split','mode'])[['queue','drop_ratio','energy','throughput','terminal_queue','realized_cost','covered_gain','covered_arrival','covered_harvest']].agg(['mean','std']).to_csv(out/'summary.csv')
rows=[]
for (dataset,split),group in raw.groupby(['dataset','split']):
 base=group[group['mode']=='nominal'].set_index('window')
 for mode in METHODS:
  if mode=='nominal':continue
  comp=group[group['mode']==mode].set_index('window')
  for metric in ('queue','drop_ratio','energy','throughput','terminal_queue','realized_cost'):
   x=(comp[metric]-base[metric]).dropna();mu=x.mean();n=len(x);half=t.ppf(.975,n-1)*x.std(ddof=1)/np.sqrt(n)
   rows.append(dict(dataset=dataset,split=split,method=mode,metric=metric,n=n,delta=mu,ci_low=mu-half,ci_high=mu+half))
pd.DataFrame(rows).to_csv(out/'paired_vs_nominal.csv',index=False)
print(raw[raw['split']=='validation'].groupby(['dataset','mode'])[['realized_cost','drop_ratio','queue','energy']].mean().to_string())
