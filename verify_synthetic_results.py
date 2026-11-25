"""Independently validate physical execution and paired sweep inputs."""
import argparse,json
from pathlib import Path
import numpy as np,pandas as pd
from src.auditing import audit_packet_outputs,audit_packets,audit_metrics,saved_config,trajectory_config
from final_evaluation import MODES,make_evaluation_trace

def main():
    ap=argparse.ArgumentParser();ap.add_argument('directory');out=Path(ap.parse_args().directory)
    settings=json.loads((out/'settings.json').read_text());raw=pd.read_csv(out/'per_seed.csv');df=pd.read_csv(out/'per_slot.csv');cfg=saved_config(settings);n=settings['slots'];checks=0
    expected=len(settings['mean_harvest'])*len(settings['volatility'])*settings['seeds']*len(settings['modes'])
    assert len(raw)==expected and not raw.duplicated(['harvest_mean','channel_sigma','seed','mode']).any()
    keys=['harvest_mean','channel_sigma','seed','mode']
    matrix=pd.read_csv(out/'run_matrix.csv')
    pd.testing.assert_frame_equal(matrix[keys].sort_values(keys).reset_index(drop=True),raw[keys].sort_values(keys).reset_index(drop=True))
    assert settings['planned_policy_runs']==len(matrix)==expected
    assert df.groupby(['harvest_mean','channel_sigma','seed','mode']).ngroups==len(raw)
    assert (raw.max_violation<=1e-4).all()
    for (harvest,sigma,seed),group in df.groupby(['harvest_mean','channel_sigma','seed']):
        assert set(group['mode'])==set(settings['modes'])
        assert sigma in settings['volatility'] and seed in settings['seed_ids'] and harvest in settings['mean_harvest']
        cfg=trajectory_config(settings,channel_sigma=sigma)
        trace=make_evaluation_trace(n,int(seed),harvest,sigma=sigma,mean_normalize=cfg.channel_mean_normalize,rho=cfg.channel_rho)
        for mode,g in group.groupby('mode'):
            g=g.sort_values('t');assert len(g)==n
            np.testing.assert_array_equal(g.t,np.arange(n))
            for col,key in [('gain','gain'),('arrivals','arrival'),('harvest','harvest')]:np.testing.assert_allclose(g[col],trace[key],atol=1e-8)
            assert (g.arrivals>=0).all() and (g.arrivals<=10).all()
            meta=raw[(raw.harvest_mean==harvest)&(raw.channel_sigma==sigma)&(raw.seed==seed)&(raw['mode']==mode)];assert len(meta)==1
            audit_packets(g,cfg,expected_seed=seed,initial_state=settings.get('initial_state'))
            audit_metrics(g,meta.iloc[0],cfg)
            checks+=1
    audit_packet_outputs(out,df,raw)
    result={'passed':True,'trajectories':checks,'slots_per_trajectory':n,'checks':'matched causal exogenous inputs, bounded arrivals, all execution bounds, channel rate, packet IDs, matched reception draws, ACK queue transitions, total-energy battery transitions, phase/event timestamps, next-interval state availability and runtime budget flags','packet_delay_checks':'independent per-packet replay, admission/attempt/ACK times, retry stability, censoring, cohorts and completed-observation delay summaries','scope':'does not independently reconstruct predicted plans, prove optimality, or certify uncertainty coverage'}
    (out/'audit.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
if __name__=='__main__':main()
