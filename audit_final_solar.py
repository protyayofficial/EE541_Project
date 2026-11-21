"""Audit solar study traces, physical actions, and earlier-window overlap."""
import argparse,json
from pathlib import Path
import numpy as np,pandas as pd
from src.experiment import make_trace
from src.auditing import saved_config
from final_solar_evaluation import reconstruct_sources,planned_runs

def intervals(dataset,starts,slots):
    for value in starts:
        if dataset=='nrel_tmy3':
            i=int(value.rsplit('_',1)[1]);yield i,i+slots
        else:
            d=pd.Timestamp(value);yield d,d+pd.Timedelta(minutes=slots)

def main():
    p=argparse.ArgumentParser();p.add_argument('directory');out=Path(p.parse_args().directory)
    s=json.loads((out/'settings.json').read_text());saved_config(s);raw=pd.read_csv(out/'per_window.csv');df=pd.read_csv(out/'per_slot.csv')
    methods=s['modes'];assert len(methods)==len(set(methods))
    assert len(raw)==len(s['dataset_slot_seconds'])*s['windows']*len(methods)
    assert not raw.duplicated(['dataset','window','mode']).any()
    sources=reconstruct_sources(s)
    matrix=pd.read_csv(out/'run_matrix.csv')
    expected=pd.DataFrame(planned_runs(s['windows'],methods))
    # Policy names come from saved configuration; never infer seven policies.
    keys=['dataset','scenario_index','seed','mode']
    pd.testing.assert_frame_equal(matrix[keys].sort_values(keys).reset_index(drop=True),expected[keys].sort_values(keys).reset_index(drop=True))
    assert s['planned_policy_runs']==len(matrix)==len(raw)
    old_paths=[Path('results')/x/'per_window.csv' for x in ('proposal_final','proposal_tuned','proposal_guarded','proposal_minimax','proposal_consistency')]
    available=[pd.read_csv(f) for f in old_paths if f.exists()]
    verified=0;earlier_overlap=[]
    for (name,window),g in df.groupby(['dataset','window']):
        meta=raw[(raw.dataset==name)&(raw.window==window)];assert meta.seed.nunique()==1
        assert set(meta['mode'])==set(methods) and set(g['mode'])==set(methods)
        records=s['window_manifest'][name]['windows']
        window_record=next(record for record in records if record['window']==window)
        assert int(meta.seed.iloc[0])==window_record['seed']
        planned=matrix[(matrix.dataset==name)&(matrix.window==window)]
        assert len(planned)==len(methods) and set(planned['mode'])==set(methods)
        assert (planned.seed==window_record['seed']).all()
        assert (planned.scenario_index==window_record['scenario_index']).all()
        n=s['slots'];seed=int(meta.seed.iloc[0]);tr=make_trace(n,seed,harvest_mean=1.1)
        expected_a=tr['arrival'];expected_h=sources[name][1][window]
        for _,frame in g.groupby('mode'):
            frame=frame.sort_values('t');assert len(frame)==n
            np.testing.assert_array_equal(frame.t,np.arange(n))
            np.testing.assert_allclose(frame.gain,tr['gain'],atol=1e-8)
            np.testing.assert_array_equal(frame.condition,tr['condition'])
            np.testing.assert_allclose(frame.arrivals,expected_a,atol=1e-8)
            np.testing.assert_allclose(frame.harvest,expected_h,atol=1e-8)
            verified+=1
        new_start,new_end=next(intervals(name,[window],n))
        for old in available:
            for old_start,old_end in intervals(name,set(old.loc[old.dataset==name,'window']),60):
                if new_start<old_end and old_start<new_end:
                    earlier_overlap.append(dict(dataset=name,window=window,earlier_start=str(old_start)))
    assert verified==len(raw)
    result={'passed':True,'trajectories':verified,'checks':'complete configured policy matrix; exact consecutive windows, manifest and pairwise overlap reconstruction; generated channel, uniform 0..10 arrivals and source-specific harvest match',
            'overlapping_pairs_by_source':{name:meta['overlapping_pairs'] for name,meta in s['window_manifest'].items()},
            'prior_window_files_checked':[str(p) for p in old_paths if p.exists()],'earlier_study_overlap':earlier_overlap,
            'scope':'shared source observations/sites/seasons; scenario intervals approximate/descriptive, not independent slot repetitions; action audit recorded separately'}
    (out/'source_audit.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
if __name__=='__main__':main()
