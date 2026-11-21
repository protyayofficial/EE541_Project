"""Audit proposal experiment using logged exogenous values and physical dynamics."""
import argparse,json
from pathlib import Path
import numpy as np,pandas as pd
from src.auditing import audit_packet_outputs,audit_packets,audit_metrics,saved_config,trajectory_config
from proposal_study import METHODS

def main():
    parser=argparse.ArgumentParser();parser.add_argument('directory');out=Path(parser.parse_args().directory)
    settings=json.loads((out/'settings.json').read_text());raw=pd.read_csv(out/'per_window.csv');df=pd.read_csv(out/'per_slot.csv');cfg=saved_config(settings);n=settings['slots']
    assert len(raw)==3*(settings['development']+settings['validation'])*len(METHODS)
    assert df.groupby(['dataset','window','mode']).ngroups==len(raw)
    assert not raw.duplicated(['dataset','window','mode']).any();assert (raw.max_violation<=1e-4).all()
    for key,group in df.groupby(['dataset','window']):
        assert set(group['mode'])==set(METHODS),key
        reference=group[group['mode']=='nominal'].sort_values('t')
        for mode,g in group.groupby('mode'):
            g=g.sort_values('t');assert len(g)==n;np.testing.assert_array_equal(g.t,np.arange(n))
            for column in ('gain','arrivals','harvest'):np.testing.assert_allclose(g[column],reference[column],atol=1e-8)
            meta=raw[(raw.dataset==key[0])&(raw.window==key[1])&(raw['mode']==mode)];assert len(meta)==1
            c=trajectory_config(settings,key[0])
            audit_packets(g,c,expected_seed=meta.seed.iloc[0],initial_state=settings.get('initial_state'))
            audit_metrics(g,meta.iloc[0],c)
    audit_packet_outputs(out,df,raw)
    result={'passed':True,'trajectories':len(raw),'slots_per_trajectory':n,'checks':['identical trace inputs','packet IDs, matched reception draws, ACK departures and total energy','power and energy causality','rate and service limits','phase/event timestamps, next-interval availability and runtime budget flags'],'packet_delay_checks':'independent per-packet replay, admission/attempt/ACK times, retry stability, censoring, cohorts and completed-observation delay summaries','scope':'does not independently reconstruct forecast-horizon plans or certify optimality'}
    (out/'audit.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
if __name__=='__main__':main()
