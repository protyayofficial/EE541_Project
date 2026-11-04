"""Audit proposal experiment using logged exogenous values and physical dynamics."""
import argparse,json
from pathlib import Path
import numpy as np,pandas as pd
from src.scheduling import Config,capacity
from proposal_study import METHODS

def main():
    parser=argparse.ArgumentParser();parser.add_argument('directory');out=Path(parser.parse_args().directory)
    settings=json.loads((out/'settings.json').read_text());raw=pd.read_csv(out/'per_window.csv');df=pd.read_csv(out/'per_slot.csv');cfg=Config();n=settings['slots']
    assert len(raw)==3*(settings['development']+settings['validation'])*len(METHODS)
    assert not raw.duplicated(['dataset','window','mode']).any();assert (raw.max_violation<=1e-4).all()
    for key,group in df.groupby(['dataset','window']):
        assert set(group['mode'])==set(METHODS),key
        reference=group[group['mode']=='nominal'].sort_values('t')
        for mode,g in group.groupby('mode'):
            g=g.sort_values('t');assert len(g)==n;np.testing.assert_array_equal(g.t,np.arange(n))
            for column in ('gain','arrivals','harvest'):np.testing.assert_allclose(g[column],reference[column],atol=1e-8)
            assert (g.b>=-1e-6).all() and (g.b<=cfg.buffer_max+1e-6).all()
            assert (g.E>=-1e-6).all() and (g.E<=cfg.energy_max+1e-6).all()
            assert (g.p>=-1e-7).all() and (g.p<=cfg.power_max+1e-7).all() and (g.p*cfg.tau<=g.E+1e-6).all()
            assert (g.d>=-1e-7).all() and (g.d<=g.b+1e-6).all() and (g.d<=cfg.data_max+1e-6).all()
            assert np.all(g.d<=capacity(g.p,g.gain,cfg)+1e-6)
            assert (g['drop']>=-1e-7).all() and (g['drop']<=g.arrivals+1e-6).all()
            np.testing.assert_allclose(g.b.to_numpy()[1:],(g.b-g.d+g.arrivals-g['drop']).to_numpy()[:-1],atol=1e-6)
            np.testing.assert_allclose(g.E.to_numpy()[1:],np.minimum(cfg.energy_max,(g.E-g.p*cfg.tau+g.harvest).to_numpy()[:-1]),atol=1e-6)
    result={'passed':True,'trajectories':len(raw),'slots_per_trajectory':n,'checks':['identical trace inputs','queue/battery bounds and transitions','power and energy causality','rate and service limits'],'scope':'does not independently reconstruct forecast-horizon plans or certify optimality'}
    (out/'audit.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
if __name__=='__main__':main()
