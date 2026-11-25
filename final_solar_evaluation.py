"""Matched solar-proxy evaluation; dependent windows and synthetic traffic/channel."""
import argparse,hashlib,json,platform,shutil,sys,time
from dataclasses import replace
from pathlib import Path
import numpy as np,pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from src.course_data import SOURCE_INTERVALS,SOURCE_FILES,SOURCE_SCALES,SOURCE_SHA256,WINDOW_SELECTION,evaluation_sources
from src.experiment import make_trace
from src.scheduling import Config
from src.radio import simulation_settings,timing_metrics
from scheduling_policies import run
from final_evaluation import DEFAULT_ROOT,DEFAULT_SLOTS,evaluate
from src.packets import run_delay_metrics,append_packet_run,DELAY_MEASURES,paired_stats

MODES=('fixed','channel','greedy','nominal','fixed_margin','adaptive_harvest','adaptive_all',
       'fixed_fraction','adaptive_channel','adaptive_arrival')

def planned_runs(count=10,modes=MODES):
    if len(set(modes))!=len(modes):raise ValueError('policy identifiers must be unique')
    return [dict(dataset=dataset,scenario_index=j,seed=7000+j,mode=mode)
            for dataset in SOURCE_INTERVALS for j in range(count) for mode in modes]

def get_windows(slots,count):
    for name,seconds,windows,_ in evaluation_sources(slots,count):yield name,seconds,windows


def reconstruct_sources(settings):
    """Bind offline/audit reconstruction to the exact online window manifest."""
    if settings.get('window_selection_version')!=WINDOW_SELECTION:
        raise ValueError('Solar results predate consecutive-window selection; regenerate them')
    for file,digest in settings['dataset_sha256'].items():
        if hashlib.sha256(Path(file).read_bytes()).hexdigest()!=digest:
            raise ValueError(f'dataset checksum mismatch: {file}')
    sources={}
    for name,seconds,windows,metadata in evaluation_sources(settings['slots'],settings['windows']):
        if metadata!=settings['window_manifest'][name]:raise ValueError(f'{name}: window manifest mismatch')
        if seconds!=settings['dataset_slot_seconds'][name]:raise ValueError(f'{name}: source interval mismatch')
        sources[name]=(seconds,dict(windows))
    return sources

def main():
    p=argparse.ArgumentParser();p.add_argument('--windows',type=int,default=10);p.add_argument('--slots',type=int,default=DEFAULT_SLOTS);p.add_argument('--horizon',type=int,default=10);p.add_argument('--out',default=DEFAULT_ROOT+'/solar');p.add_argument('--validate-only',action='store_true',help='validate real windows and save run matrix/settings without executing policies');a=p.parse_args()
    if min(a.windows,a.slots,a.horizon)<2:p.error('windows,slots,horizon must be at least 2')
    out=Path(a.out)
    if any((out/name).exists() for name in ('per_window.csv','per_slot.csv','per_packet.csv','partial_slots.csv','partial_windows.csv')):
        p.error('output already contains trajectories; choose a fresh --out directory')
    selected=list(evaluation_sources(a.slots,a.windows))  # Validate all inputs before any policy executes.
    out.mkdir(parents=True,exist_ok=True);rows=[]
    hashes={f:hashlib.sha256(Path(f).read_bytes()).hexdigest() for f in SOURCE_FILES.values()}
    manifest={name:metadata for name,_,_,metadata in selected}
    matrix=planned_runs(a.windows)
    for row in matrix:row['window']=manifest[row['dataset']]['windows'][row['scenario_index']]['window']
    pd.DataFrame(matrix).to_csv(out/'run_matrix.csv',index=False)
    settings=vars(a)|simulation_settings(replace(Config(),horizon=a.horizon))|{'modes':MODES,'dataset_slot_seconds':SOURCE_INTERVALS,'dataset_sha256':hashes,
      'recorded_reference_sha256':{SOURCE_FILES[name]:digest for name,digest in SOURCE_SHA256.items()},
      'matches_recorded_checksums':{name:hashes[SOURCE_FILES[name]]==digest for name,digest in SOURCE_SHA256.items()},
      'window_selection_version':WINDOW_SELECTION,'window_manifest':manifest,'planned_policy_runs':len(matrix),
      'seed_ids':list(range(7000,7000+a.windows)),
      'selection':'prefer spread disjoint consecutive valid windows; otherwise spread distinct valid starts across available range; overlap recorded in window_manifest',
      'uncertainty_intervals':'approximate/descriptive paired scenario-level t intervals; shared solar observations and source dependence; slots are not independent repetitions',
      'caveat':'one source per dataset; windows share sites/seasons and may share observations; not independent solar records; energy conversion assumed, traffic/channel synthetic; TMY stitched and hourly; no exclusion of earlier-study windows',
      'arrival':'IID discrete uniform integers 0..10 inclusive, probability 1/11 each, mean 5','scales':SOURCE_SCALES,'python':sys.version,'platform':platform.platform()}
    (out/'settings.json').write_text(json.dumps(settings,indent=2)+'\n')
    if a.validate_only:
        print(f'Validated {len(selected)*a.windows} solar windows; planned policy-runs: {len(matrix)}; no policies executed')
        return
    for dataset,slot,wins,_ in selected:
      cfg=replace(Config(),horizon=a.horizon,slot_seconds=slot)
      for j,(start,h) in enumerate(wins):
        seed=7000+j;generated=make_trace(a.slots,seed,harvest_mean=1.1)
        # Discard unused oracle-aided forecast fields from the trace generator.
        tr={k:generated[k] for k in ('condition','gain','arrival','harvest','seed')}
        tr['harvest']=h
        for mode in MODES:
          print(dataset,start,'seed',seed,mode,flush=True);tic=time.perf_counter();df=run(tr,cfg,mode)
          row=evaluate(df,cfg)|dict(dataset=dataset,window=start,seed=seed,mode=mode,slot_seconds=slot,wall_seconds=time.perf_counter()-tic)
          run_id=append_packet_run(df,out,dict(experiment='solar',dataset=dataset,window=start,seed=seed,mode=mode))
          rows.append(row|dict(run_id=run_id))
          df=df.copy();df['dataset']=dataset;df['window']=start;df['seed']=seed;df['run_id']=run_id
          df.to_csv(out/'partial_slots.csv',mode='a',header=not (out/'partial_slots.csv').exists(),index=False)
          pd.DataFrame(rows).to_csv(out/'partial_windows.csv',index=False)
    raw=pd.DataFrame(rows);raw.to_csv(out/'per_window.csv',index=False);shutil.copyfile(out/'partial_slots.csv',out/'per_slot.csv')
    metrics=['queue','drop_ratio','energy','throughput','terminal_queue','realized_cost','coverage_gain','coverage_arrival','coverage_harvest','mean_solve_ms',*timing_metrics(df),*run_delay_metrics(df)]
    raw.groupby(['dataset','mode'])[metrics].agg(['mean','std','count']).to_csv(out/'summary.csv')
    pairs=[]
    for dataset,g in raw.groupby('dataset'):
      base=g[g['mode']=='nominal'].set_index('window')
      for mode in MODES:
        if mode=='nominal':continue
        comp=g[g['mode']==mode].set_index('window')
        for metric in ('queue','drop_ratio','energy','throughput','terminal_queue','realized_cost',*DELAY_MEASURES):
          dif=comp[metric]-base[metric]
          pairs.append(dict(dataset=dataset,method=mode,metric=metric,**paired_stats(dif),
                            interval_interpretation='approximate/descriptive; dependent source windows'))
    pd.DataFrame(pairs).to_csv(out/'paired_vs_nominal.csv',index=False)
    for metric,label in [('realized_cost','Realized weighted cost'),('drop_ratio','Rejected fraction'),('queue','Mean queue (packets)'),('energy','TX data and control energy (J)')]:
      fig,axs=plt.subplots(1,3,figsize=(15,4),layout='constrained')
      for ax,(dataset,group) in zip(axs,raw.groupby('dataset')):
        values=group.groupby('mode')[metric].mean().reindex(MODES);ax.barh(values.index,values.values);ax.set(title=dataset,xlabel=label);ax.grid(axis='x',alpha=.2)
      fig.suptitle('Dependent solar windows; descriptive scenario means, not independent slot repetitions',fontsize=9)
      fig.savefig(out/f'{metric}.png',dpi=180);plt.close(fig)
    print(raw.groupby(['dataset','mode'])[['realized_cost','drop_ratio','queue','energy']].mean().to_string());print('max violation',raw.max_violation.max(),'inaccurate',raw.inaccurate.sum())
if __name__=='__main__':main()
