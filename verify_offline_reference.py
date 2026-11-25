"""Recheck saved clairvoyant plans, their objective and online gaps."""
import argparse,json
from pathlib import Path
import numpy as np,pandas as pd
from src.scheduling import INITIAL_QUEUE,INITIAL_ENERGY,verify_plan,planned_energy
from src.auditing import saved_config,trajectory_config
from dataclasses import replace
from src.experiment import make_trace
from final_evaluation import make_evaluation_trace
from final_solar_evaluation import reconstruct_sources

def main():
 p=argparse.ArgumentParser();p.add_argument('directory');out=Path(p.parse_args().directory);raw=pd.read_csv(out/'per_instance.csv');plans=pd.read_csv(out/'plans.csv');pairs=pd.read_csv(out/'paired_reference.csv');settings=json.loads((out/'settings.json').read_text());saved_config(settings);checked=0
 root=out.parent;synth=json.loads((root/'sweep_normalized/settings.json').read_text());solar=json.loads((root/'solar/settings.json').read_text())
 synthetic_online=pd.read_csv(root/'sweep_normalized/per_seed.csv');solar_online=pd.read_csv(root/'solar/per_window.csv')
 assert len(raw[raw.dataset=='synthetic'])==len(synth['mean_harvest'])*len(synth['volatility'])*synth['seeds']
 assert len(raw[raw.dataset!='synthetic'])==len(solar['dataset_slot_seconds'])*solar['windows']
 assert not raw.duplicated(['dataset','window','seed']).any()
 assert len(pairs)==len(synthetic_online)+len(solar_online)
 assert not pairs.duplicated(['dataset','window','seed','mode']).any()
 windows={name:wins for name,(_,wins) in reconstruct_sources(solar).items()}
 for key,g in plans.groupby(['dataset','window','seed']):
  dataset,window,seed=key;g=g.sort_values('t');meta=raw[(raw.dataset==dataset)&(raw.window==window)&(raw.seed==seed)];assert len(meta)==1
  expected_slots=(synth if dataset=='synthetic' else solar)['slots']
  assert len(g)==expected_slots==settings['source_slot_counts']['synthetic' if dataset=='synthetic' else 'solar']
  if dataset=='synthetic':
   trace=make_evaluation_trace(len(g),int(seed),float(meta.harvest_mean.iloc[0]),sigma=float(meta.channel_sigma.iloc[0]),mean_normalize=True,rho=synth['config']['channel_rho'])
   online=synthetic_online[(synthetic_online.harvest_mean==meta.harvest_mean.iloc[0])&(synthetic_online.channel_sigma==meta.channel_sigma.iloc[0])&(synthetic_online.seed==seed)]
  else:
   trace=make_trace(len(g),int(seed),harvest_mean=1.1);trace['harvest']=windows[dataset][window]
   online=solar_online[(solar_online.dataset==dataset)&(solar_online.window==window)&(solar_online.seed==seed)]
  paired=pairs[(pairs.dataset==dataset)&(pairs.window==window)&(pairs.seed==seed)]
  assert set(paired['mode'])==set(online['mode'])
  np.testing.assert_allclose(paired.set_index('mode').online_cost.sort_index(),online.set_index('mode').realized_cost.sort_index())
  np.testing.assert_allclose(paired.offline_objective,meta.objective.iloc[0])
  for column,keyname in [('gain','gain'),('arrival','arrival'),('harvest','harvest')]:np.testing.assert_allclose(g[column],trace[keyname],atol=1e-8)
  np.testing.assert_array_equal(g.condition,trace['condition'])
  np.testing.assert_array_equal(g.t,np.arange(len(g)));np.testing.assert_allclose(g.b_next.to_numpy()[:-1],g.b.to_numpy()[1:],atol=1e-7);np.testing.assert_allclose(g.E_next.to_numpy()[:-1],g.E.to_numpy()[1:],atol=1e-7)
  cfg=trajectory_config(synth if dataset=='synthetic' else solar,dataset,channel_sigma=meta.channel_sigma.iloc[0])
  sol={'u':g.u.to_numpy(),'p':g.p.to_numpy(),'d':g.d.to_numpy(),'b':np.r_[g.b.to_numpy(),g.b_next.iloc[-1]],'E':np.r_[g.E.to_numpy(),g.E_next.iloc[-1]],'o':g.o.to_numpy(),'w':g.w.to_numpy()}
  violation=max(verify_plan(sol,INITIAL_QUEUE,INITIAL_ENERGY,g.gain.to_numpy(),g.arrival.to_numpy(),g.harvest.to_numpy(),cfg).values());assert violation<=1e-4,(key,violation)
  value=float(g.b.sum()+cfg.drop_weight*g.o.sum()+cfg.energy_weight*g.energy.sum()+cfg.terminal_weight*g.b_next.iloc[-1])
  np.testing.assert_allclose(g.energy,planned_energy(sol,INITIAL_ENERGY,cfg),atol=1e-7)
  np.testing.assert_allclose(g.expected_received,cfg.success_probability*g.d,atol=1e-7)
  np.testing.assert_allclose(value,meta.objective.iloc[0],rtol=1e-7,atol=1e-5);checked+=1
 assert not (raw.status=='failed').any(), 'offline instances failed; comparison is incomplete'
 assert checked==len(raw);np.testing.assert_allclose(pairs.online_minus_offline,pairs.online_cost-pairs.offline_objective,atol=1e-7);assert (pairs.reference_kind=='deterministic_expected_goodput').all()
 result={'passed':True,'plans_audited':checked,'failed_instances':int((raw.status=='failed').sum()),'maximum_rechecked_violation':float(raw.max_violation.max()),'minimum_online_minus_offline':float(pairs.online_minus_offline.min()),'checks':'same exogenous traces, saved primal dynamics, bounds, rate and objective; descriptive differences against realized stochastic online costs','scope':'does not prove solver optimality or establish a bound on realized stochastic costs'}
 (out/'audit.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
if __name__=='__main__':main()
