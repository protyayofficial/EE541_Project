"""Audit a matched uncertainty-policy comparison from its saved actions."""
import argparse,json
from pathlib import Path
import numpy as np,pandas as pd
from src.auditing import audit_packet_outputs,audit_packets,audit_metrics,saved_config,trajectory_config

def main():
 p=argparse.ArgumentParser();p.add_argument('directory');out=Path(p.parse_args().directory)
 settings=json.loads((out/'settings.json').read_text());raw=pd.read_csv(out/'per_window.csv');df=pd.read_csv(out/'per_slot.csv');cfg=saved_config(settings);n=settings['slots'];methods=set(settings.get('modes',raw['mode']));assert not raw.duplicated(['dataset','window','mode']).any()
 assert set(raw['mode'])==methods
 assert df.groupby(['dataset','window','mode']).ngroups==len(raw)
 assert (raw.max_violation<=1e-4).all()
 for key,group in df.groupby(['dataset','window']):
  assert set(group['mode'])==methods,key
  reference=group[group['mode']=='nominal'].sort_values('t')
  for mode,g in group.groupby('mode'):
   g=g.sort_values('t');assert len(g)==n;np.testing.assert_array_equal(g.t,np.arange(n))
   for field in ('gain','arrivals','harvest'):np.testing.assert_allclose(g[field],reference[field],atol=1e-8)
   meta=raw[(raw.dataset==key[0])&(raw.window==key[1])&(raw['mode']==mode)];assert len(meta)==1
   c=trajectory_config(settings,key[0])
   audit_packets(g,c,expected_seed=meta.seed.iloc[0],initial_state=settings.get('initial_state'))
   audit_metrics(g,meta.iloc[0],c)
   if mode.endswith('_forced') and 'planned_excess_rejection' in g:
    assert (g.planned_excess_rejection<=1.02e-4).all(),(key,mode,'first-slot cap')

 audit_packet_outputs(out,df,raw)
 report={'passed':True,'trajectories':len(raw),'datasets':int(raw.dataset.nunique()),'methods':sorted(methods),'slots_per_trajectory':n,'checks':'matched inputs, packet IDs, matched reception draws, ACK queue transitions and total-energy battery transitions, aggregate metrics, action bounds, energy causality, channel capacity, phase/event timestamps, next-interval state availability, runtime budget flags, and first-slot cap when applicable','packet_delay_checks':'independent per-packet replay, admission/attempt/ACK times, retry stability, censoring, cohorts and completed-observation delay summaries','scope':'does not reconstruct predicted horizon plans or certify optimality'}
 (out/'audit.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
