"""Audit solar study traces, physical actions, and earlier-window overlap."""
import argparse,json
from pathlib import Path
import numpy as np,pandas as pd
from src.experiment import make_trace
from final_solar_evaluation import get_windows,MODES
from audit_comparison import main as audit_actions

def intervals(dataset,starts,slots):
    for value in starts:
        if dataset=='nrel_tmy3':
            i=int(value.rsplit('_',1)[1]);yield i,i+slots
        else:
            d=pd.Timestamp(value);yield d,d+pd.Timedelta(minutes=slots)

def main():
    p=argparse.ArgumentParser();p.add_argument('directory');out=Path(p.parse_args().directory)
    s=json.loads((out/'settings.json').read_text());raw=pd.read_csv(out/'per_window.csv');df=pd.read_csv(out/'per_slot.csv')
    assert len(raw)==3*s['windows']*len(MODES)
    sources={name:(seconds,dict(wins)) for name,seconds,wins in get_windows(s['slots'],s['windows'])}
    old_paths=[Path('results')/x/'per_window.csv' for x in ('proposal_final','proposal_tuned','proposal_guarded','proposal_minimax','proposal_consistency')]
    available=[pd.read_csv(f) for f in old_paths if f.exists()]
    verified=0
    for (name,window),g in df.groupby(['dataset','window']):
        meta=raw[(raw.dataset==name)&(raw.window==window)];assert meta.seed.nunique()==1
        n=s['slots'];seed=int(meta.seed.iloc[0]);tr=make_trace(n,seed,arrival_mean=2.5,harvest_mean=1.1)
        expected_a=np.minimum(tr['arrival'],10);expected_h=sources[name][1][window]
        for _,frame in g.groupby('mode'):
            frame=frame.sort_values('t');assert len(frame)==n
            np.testing.assert_allclose(frame.gain,tr['gain'],atol=1e-8)
            np.testing.assert_allclose(frame.arrivals,expected_a,atol=1e-8)
            np.testing.assert_allclose(frame.harvest,expected_h,atol=1e-8)
            verified+=1
        new_start,new_end=next(intervals(name,[window],n))
        for old in available:
            for old_start,old_end in intervals(name,set(old.loc[old.dataset==name,'window']),60):
                assert new_start>=old_end or old_start>=new_end,(name,window,old_start)
    result={'passed':True,'trajectories':verified,'checks':'generated channel, clipped arrivals and source-specific harvest match; no overlap with available prior saved windows','scope':'same sites/seasons, windows not independent; action audit is recorded separately'}
    (out/'source_audit.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
if __name__=='__main__':main()
