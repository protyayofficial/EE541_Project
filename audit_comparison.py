"""Audit a matched uncertainty-policy comparison from its saved actions."""
import argparse,json
from pathlib import Path
import numpy as np,pandas as pd
from src.scheduling import Config,capacity

def main():
 p=argparse.ArgumentParser();p.add_argument('directory');out=Path(p.parse_args().directory)
 raw=pd.read_csv(out/'per_window.csv');df=pd.read_csv(out/'per_slot.csv');cfg=Config();n=int(df.groupby(['dataset','window','mode']).size().iloc[0]);methods=set(raw['mode']);assert not raw.duplicated(['dataset','window','mode']).any()
 assert (raw.max_violation<=1e-4).all()
 for key,group in df.groupby(['dataset','window']):
  assert set(group['mode'])==methods,key
  reference=group[group['mode']=='nominal'].sort_values('t')
  for mode,g in group.groupby('mode'):
   g=g.sort_values('t');assert len(g)==n;np.testing.assert_array_equal(g.t,np.arange(n))
   for field in ('gain','arrivals','harvest'):np.testing.assert_allclose(g[field],reference[field],atol=1e-8)
   assert (g.b>=-1e-6).all() and (g.b<=cfg.buffer_max+1e-6).all() and (g.E>=-1e-6).all() and (g.E<=cfg.energy_max+1e-6).all()
   assert (g.p>=-1e-7).all() and (g.p<=cfg.power_max+1e-7).all() and (g.p*cfg.tau<=g.E+1e-6).all()
   assert (g.d>=-1e-7).all() and (g.d<=g.b+1e-6).all() and (g.d<=cfg.data_max+1e-6).all() and np.all(g.d<=capacity(g.p,g.gain,cfg)+1e-6)
   assert (g['drop']>=-1e-7).all() and (g['drop']<=g.arrivals+1e-6).all()
   if mode.endswith('_forced') and 'planned_excess_rejection' in g:
    assert (g.planned_excess_rejection<=1.02e-4).all(),(key,mode,'first-slot cap')
   np.testing.assert_allclose(g.b.to_numpy()[1:],(g.b-g.d+g.arrivals-g['drop']).to_numpy()[:-1],atol=1e-6)
   np.testing.assert_allclose(g.E.to_numpy()[1:],np.minimum(cfg.energy_max,(g.E-g.p*cfg.tau+g.harvest).to_numpy()[:-1]),atol=1e-6)
 report={'passed':True,'trajectories':len(raw),'datasets':int(raw.dataset.nunique()),'methods':sorted(methods),'slots_per_trajectory':n,'checks':'matched inputs, queue and battery transitions, action bounds, energy causality, channel capacity, and first-slot cap when applicable','scope':'does not reconstruct predicted horizon plans or certify optimality'}
 (out/'audit.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
