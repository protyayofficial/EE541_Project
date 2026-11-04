"""Independently validate physical execution and paired sweep inputs."""
import argparse,json
from pathlib import Path
import numpy as np,pandas as pd
from src.scheduling import Config,capacity
from final_evaluation import MODES,make_evaluation_trace

def main():
    ap=argparse.ArgumentParser();ap.add_argument('directory');out=Path(ap.parse_args().directory)
    settings=json.loads((out/'settings.json').read_text());raw=pd.read_csv(out/'per_seed.csv');df=pd.read_csv(out/'per_slot.csv');cfg=Config();n=settings['slots'];checks=0
    expected=len(settings['mean_harvest'])*len(settings['volatility'])*settings['seeds']*len(MODES)
    assert len(raw)==expected and not raw.duplicated(['harvest_mean','channel_sigma','seed','mode']).any()
    assert (raw.max_violation<=1e-4).all()
    for (harvest,sigma,seed),group in df.groupby(['harvest_mean','channel_sigma','seed']):
        assert set(group['mode'])==set(MODES)
        trace=make_evaluation_trace(n,int(seed),sigma,harvest,settings.get('mean_normalize',False))
        for mode,g in group.groupby('mode'):
            g=g.sort_values('t');assert len(g)==n
            np.testing.assert_array_equal(g.t,np.arange(n))
            for col,key in [('gain','gain'),('arrivals','arrival'),('harvest','harvest')]:np.testing.assert_allclose(g[col],trace[key],atol=1e-8)
            assert (g.arrivals>=0).all() and (g.arrivals<=10).all()
            assert (g.b>=-1e-6).all() and (g.b<=cfg.buffer_max+1e-6).all() and (g.E>=-1e-6).all() and (g.E<=cfg.energy_max+1e-6).all()
            assert (g.p>=-1e-7).all() and (g.p<=cfg.power_max+1e-7).all() and (g.p*cfg.tau<=g.E+1e-6).all()
            assert (g.d>=-1e-7).all() and (g.d<=g.b+1e-6).all() and (g.d<=cfg.data_max+1e-6).all() and np.all(g.d<=capacity(g.p,g.gain,cfg)+1e-6)
            assert (g['drop']>=-1e-7).all() and (g['drop']<=g.arrivals+1e-6).all()
            np.testing.assert_allclose(g.b.to_numpy()[1:],(g.b-g.d+g.arrivals-g['drop']).to_numpy()[:-1],atol=1e-6)
            np.testing.assert_allclose(g.E.to_numpy()[1:],np.minimum(cfg.energy_max,(g.E-g.p*cfg.tau+g.harvest).to_numpy()[:-1]),atol=1e-6)
            checks+=1
    result={'passed':True,'trajectories':checks,'slots_per_trajectory':n,'checks':'matched causal exogenous inputs, bounded arrivals, all execution bounds, channel rate, queue and battery transitions','scope':'does not independently reconstruct predicted plans, prove optimality, or certify uncertainty coverage'}
    (out/'audit.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
if __name__=='__main__':main()
