"""Recheck saved clairvoyant plans, their objective and online gaps."""
import argparse,json
from pathlib import Path
import numpy as np,pandas as pd
from src.scheduling import Config,verify_plan
from src.experiment import make_trace
from final_evaluation import make_evaluation_trace
from final_solar_evaluation import get_windows

def main():
 p=argparse.ArgumentParser();p.add_argument('directory');out=Path(p.parse_args().directory);raw=pd.read_csv(out/'per_instance.csv');plans=pd.read_csv(out/'plans.csv');pairs=pd.read_csv(out/'paired_reference.csv');cfg=Config();checked=0
 root=out.parent;synth=json.loads((root/'sweep_normalized/settings.json').read_text());solar=json.loads((root/'solar/settings.json').read_text())
 windows={name:dict(wins) for name,_,wins in get_windows(solar['slots'],solar['windows'])}
 for key,g in plans.groupby(['dataset','window','seed']):
  dataset,window,seed=key;g=g.sort_values('t');meta=raw[(raw.dataset==dataset)&(raw.window==window)&(raw.seed==seed)];assert len(meta)==1
  if dataset=='synthetic':
   trace=make_evaluation_trace(len(g),int(seed),float(meta.channel_sigma.iloc[0]),float(meta.harvest_mean.iloc[0]),synth.get('mean_normalize',False))
  else:
   trace=make_trace(len(g),int(seed),arrival_mean=2.5,harvest_mean=1.1);trace['arrival']=np.minimum(trace['arrival'],10.);trace['harvest']=windows[dataset][window]
  for column,keyname in [('gain','gain'),('arrival','arrival'),('harvest','harvest')]:np.testing.assert_allclose(g[column],trace[keyname],atol=1e-8)
  np.testing.assert_array_equal(g.t,np.arange(len(g)));np.testing.assert_allclose(g.b_next.to_numpy()[:-1],g.b.to_numpy()[1:],atol=1e-7);np.testing.assert_allclose(g.E_next.to_numpy()[:-1],g.E.to_numpy()[1:],atol=1e-7)
  sol={'p':g.p.to_numpy(),'d':g.d.to_numpy(),'b':np.r_[g.b.to_numpy(),g.b_next.iloc[-1]],'E':np.r_[g.E.to_numpy(),g.E_next.iloc[-1]],'o':g.o.to_numpy(),'w':g.w.to_numpy()}
  violation=max(verify_plan(sol,12.,7.,g.gain.to_numpy(),g.arrival.to_numpy(),g.harvest.to_numpy(),cfg).values());assert violation<=1e-4,(key,violation)
  value=float(g.b.sum()+cfg.drop_weight*g.o.sum()+cfg.energy_weight*cfg.tau*g.p.sum()+cfg.terminal_weight*g.b_next.iloc[-1])
  np.testing.assert_allclose(value,meta.objective.iloc[0],rtol=1e-7,atol=1e-5);checked+=1
 assert checked==int((raw.status!='failed').sum());assert (pairs.online_minus_offline.dropna()>=-1e-3).all()
 result={'passed':True,'plans_audited':checked,'failed_instances':int((raw.status=='failed').sum()),'maximum_rechecked_violation':float(raw.max_violation.max()),'minimum_online_minus_offline':float(pairs.online_minus_offline.min()),'checks':'same exogenous traces, saved primal dynamics, bounds, rate and objective; numerical consistency against online costs','scope':'does not prove solver optimality or certify a dual lower bound'}
 (out/'audit.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
if __name__=='__main__':main()
