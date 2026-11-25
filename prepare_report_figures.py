"""Read-only report figures/evidence from the completed EE541 production tables.

No simulator or optimizer imports. Writes only to a fresh output directory and ZIP.
The compact input capsule supports replotting via --input <output>/inputs.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import shutil
import sys
import zipfile
import numpy as np
import pandas as pd
from scipy.stats import t as student_t
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from PIL import Image

DEFAULT_INPUT=Path('report_results/production')
SPEC={'sweep':('per_seed.csv',300,5000),'sweep_normalized':('per_seed.csv',300,6000),
      'solar':('per_window.csv',300,7000),'supplementary/delay_energy':('per_seed.csv',120,6000),
      'supplementary/forecast_sensitivity':('per_seed.csv',120,6000)}
POLICIES=['greedy','nominal','fixed_margin','adaptive_harvest','adaptive_all']
SOLAR_POLICIES=['fixed','channel','greedy','nominal','fixed_margin','adaptive_harvest','adaptive_all',
                'fixed_fraction','adaptive_channel','adaptive_arrival']
LABELS={'greedy':'Greedy','nominal':'Nominal MPC','fixed_margin':'Fixed-margin MPC',
        'adaptive_all':'Adaptive-all MPC','adaptive_harvest':'Harvest-margin MPC',
        'adaptive_channel':'Channel-margin MPC','adaptive_arrival':'Arrival-margin MPC',
        'fixed':'Fixed power','channel':'Channel-aware','fixed_fraction':'Fixed fraction'}
COLORS={'greedy':'#4C4C4C','nominal':'#0072B2','adaptive_all':'#009E73','fixed_margin':'#E69F00',
        'adaptive_harvest':'#D55E00','adaptive_channel':'#CC79A7','adaptive_arrival':'#56B4E9',
        'fixed':'#999999','channel':'#000000','fixed_fraction':'#F0E442'}
MARKERS=dict(zip(SOLAR_POLICIES,['o','s','D','^','v','P','X','<','>','h']))
SOURCES={'arco':'ARCO (60 s intervals)','umass_home_c':'UMass Home C (60 s intervals)',
         'nrel_tmy3':'NREL TMY3 (3600 s intervals)'}
INTERVALS={'arco':60.,'umass_home_c':60.,'nrel_tmy3':3600.}
Y_LABEL={'common_score':'Weighted score','drop_ratio':'Rejected arrivals (%)',
         'queue':'Mean beginning-of-slot\nbacklog (packets)',
         'energy':'Mean total TX energy\n(J per 1000-slot episode)',
         'mean_initial_wait_s':'Mean first-attempt waiting time (s)',
         'mean_ack_completion_delay_s':'Mean ACK-completion delay (s)',
         'newly_unfinished_fraction':'Unfinished admitted packets (%)'}
PERCENT={'drop_ratio','newly_completed_fraction','newly_unfinished_fraction','offered_completion_fraction','admission_fraction',
         'coverage_gain','coverage_arrival','coverage_harvest'}
CORE_METRICS=['common_score','drop_ratio','queue','energy','throughput','mean_initial_wait_s',
              'mean_ack_completion_delay_s','newly_admitted_packets','newly_acknowledged_packets',
              'newly_unfinished_fraction','offered_completion_fraction']


def sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda:handle.read(4*1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def snapshot(root):
    return {str(p.relative_to(root)):dict(bytes=p.stat().st_size,sha256=sha(p))
            for p in sorted(root.rglob('*')) if p.is_file()}


def fresh(path):
    result=Path(path);i=2
    while result.exists():result=Path(f'{path}_{i}');i+=1
    return result


def choose(frame,group):
    result=frame
    for key,value in group.items():result=result[result[key]==value]
    return result


def stat(values):
    values=np.asarray(values,float);values=values[np.isfinite(values)];n=len(values)
    mean=float(np.mean(values)) if n else np.nan
    sd=float(np.std(values,ddof=1)) if n>1 else np.nan
    half=float(student_t.ppf(.975,n-1)*sd/np.sqrt(n)) if n>1 else np.nan
    return dict(n_valid=n,mean=mean,std=sd,ci_low=mean-half,ci_high=mean+half,ci_half=half)


class Report:
    def __init__(self,source,out):
        self.source=source;self.out=out;self.frames={};self.paths={};self.figures=[];self.points=[];self.cap=[]
        self.validation=dict(checks_now=[],previous_raw_audits=[],raw_ledger_audit_replayed=False,
                             intervals='unadjusted 95% t; solar intervals descriptive due to shared-source dependence')

    def write(self,name,frame):
        p=self.out/name;p.parent.mkdir(parents=True,exist_ok=True);frame.to_csv(p,index=False)

    def load(self):
        status=json.loads((self.source/'status.json').read_text())
        assert status['status']=='completed' and all(r['status']=='completed' for r in status['stages'])
        assert (self.source/'COMPLETED').exists() and 'PASS:' in (self.source/'logs/21_completion_audit.log').read_text()
        self.status=status;self.settings={};structure=[]
        for folder,(file,expected,start) in SPEC.items():
            d=pd.read_csv(self.source/folder/file);s=json.loads((self.source/folder/'settings.json').read_text())
            assert len(d)==expected and d.run_id.nunique()==expected
            assert s['slots']==1000 and s['horizon']==10 and s['config']['horizon']==10
            assert s['seed_ids']==list(range(start,start+10)) and set(d.seed)==set(range(start,start+10))
            matrix=pd.read_csv(self.source/folder/'run_matrix.csv')
            keys=['dataset','window','seed','mode'] if folder=='solar' else ['harvest_mean','channel_sigma','seed','mode'] if folder.startswith('sweep') else ['harvest_mean','seed','mode','study_value','energy_weight','forecast_perturbation']
            assert not matrix.duplicated(keys).any() and len(matrix)==expected
            pd.testing.assert_frame_equal(d[keys].sort_values(keys).reset_index(drop=True),matrix[keys].sort_values(keys).reset_index(drop=True),check_dtype=False)
            self.settings[folder]=s;self.paths[folder]=f'{folder}/{file}'
            d['offered_arrivals']=d.newly_admitted_packets+d.rejected_arrivals
            d['newly_completed_fraction']=d.newly_acknowledged_packets/d.newly_admitted_packets.replace(0,np.nan)
            d['newly_unfinished_fraction']=1-d.newly_completed_fraction
            d['offered_completion_fraction']=d.newly_acknowledged_packets/d.offered_arrivals.replace(0,np.nan)
            d['admission_fraction']=d.newly_admitted_packets/d.offered_arrivals.replace(0,np.nan)
            d['common_score']=d.common_reference_cost if 'common_reference_cost' in d else d.realized_cost
            for left,right in [('initial_wait_samples',d.newly_attempted_packets),('ack_completion_delay_samples',d.newly_acknowledged_packets),
                               ('initial_wait_unfinished_packets',d.newly_admitted_packets-d.newly_attempted_packets),
                               ('ack_completion_delay_unfinished_packets',d.newly_admitted_packets-d.newly_acknowledged_packets),
                               ('newly_outstanding_packets',d.newly_admitted_packets-d.newly_acknowledged_packets),
                               ('terminal_queue',d.outstanding_packets)]:
                np.testing.assert_allclose(d[left],right,atol=1e-9)
            np.testing.assert_allclose(d.drop_ratio,d.rejected_arrivals/d.offered_arrivals)
            np.testing.assert_allclose(d.initial_packets+d.newly_admitted_packets-d.acknowledged,d.outstanding_packets)
            np.testing.assert_allclose(d.energy,d.data_energy+d.control_energy)
            np.testing.assert_allclose(d.common_score,1000*d.queue+35*d.rejected_arrivals+.15*d.energy+6*d.terminal_queue)
            weight=d.energy_weight if 'energy_weight' in d else s['config']['energy_weight']
            np.testing.assert_allclose(d.realized_cost,1000*d.queue+35*d.rejected_arrivals+weight*d.energy+6*d.terminal_queue)
            seconds=d.slot_seconds if 'slot_seconds' in d else 5.
            np.testing.assert_allclose(d.throughput,256*d.delivered/(1000*seconds))
            for prefix,samples in [('initial_wait',d.initial_wait_samples),('ack_completion_delay',d.ack_completion_delay_samples)]:
                for measure in ('mean','median'):
                    col=d[f'{measure}_{prefix}_s'];assert col[samples==0].isna().all()
                    assert col[samples>0].notna().all() and (col[samples>0]>=0).all()
            assert (d.initial_packets==12).all() and d.max_violation.max()<=1e-4
            self.frames[folder]=d
            structure.append(dict(group=folder,executions=expected,slots_per_episode=1000,online_horizon=10,
                seed_first=start,seed_last=start+9,interval_seconds='60/60/3600 by source' if folder=='solar' else '5',
                policies=', '.join(s['modes']),repetition='matched seeds; solar scenarios dependent' if folder=='solar' else 'matched seed runs; baseline overlap across supplements'))
            for file2 in ('summary.csv','paired_vs_nominal.csv'):
                assert (self.source/folder/file2).is_file()
        offline=pd.read_csv(self.source/'offline/per_instance.csv');solver=pd.read_csv(self.source/'solver/solver_results.csv')
        assert len(offline)==90 and len(solver)==12 and (offline.status=='optimal').all() and (solver.status=='optimal').all()
        assert not solver.duplicated(['case','solver']).any()
        structure.extend([dict(group='offline',executions=90,slots_per_episode=1000,online_horizon=np.nan,reference_horizon=1000,repetition='60 normalized synthetic + 30 solar scenarios; no packet delays'),
                          dict(group='solver',executions=12,slots_per_episode=10,online_horizon=np.nan,repetition='six instances, two solvers; not online episodes')])
        self.write('tables/experiment_structure.csv',pd.DataFrame(structure))
        self.solar_meta=self.settings['solar']
        self.write('tables/source_intervals.csv',pd.DataFrame([dict(dataset=k,interval_s=v,
            selected_windows=10,overlapping_window_pairs=self.solar_meta['window_manifest'][k]['overlapping_pairs'],
            uncertainty='descriptive paired scenario intervals; shared source/season') for k,v in INTERVALS.items()]))
        for relative in ('sweep/audit.json','sweep_normalized/audit.json','solar/audit.json','solar/source_audit.json',
                         'supplementary/delay_energy/audit.json','supplementary/forecast_sensitivity/audit.json','offline/audit.json','solver/audit.json'):
            record=json.loads((self.source/relative).read_text());assert record['passed']
            self.validation['previous_raw_audits'].append(dict(path=relative,sha256=sha(self.source/relative),passed=True,replayed_now=False))
        self.validation['checks_now'].extend(['completed status/marker and final completion audit; exact saved run matrices/counts/seeds',
            'run-level packet cohort identities, admission/rejection denominators, missing-delay semantics',
            'run-level queue/terminal conservation, energy components, configured/common score formulas, source-specific throughput units'])
        assert self.solar_meta['window_manifest']['nrel_tmy3']['overlapping_pairs']==9
        for folder in ('supplementary/delay_energy','supplementary/forecast_sensitivity'):
            key=folder+'/errors';self.frames[key]=pd.read_csv(self.source/folder/'forecast_errors.csv');self.paths[key]=folder+'/forecast_errors.csv'
        self.frames['offline']=offline;self.paths['offline']='offline/per_instance.csv'
        self.frames['offline_pairs']=pd.read_csv(self.source/'offline/paired_reference.csv');self.paths['offline_pairs']='offline/paired_reference.csv'
        self.frames['solver']=solver;self.paths['solver']='solver/solver_results.csv'

    def vector(self,table,group,metric,kind='mean',reference=None,reference_group=None):
        a=choose(self.frames[table],group)
        if kind=='seed_mean':return a.groupby('seed')[metric].mean().to_numpy(),len(a.groupby('seed'))
        if kind=='paired':
            b=choose(self.frames[reference],reference_group);keys=['window','seed'] if table=='solar' else ['seed']
            assert not a.duplicated(keys).any() and not b.duplicated(keys).any()
            merged=a[keys+[metric]].merge(b[keys+[metric]],on=keys,how='outer',validate='one_to_one',indicator=True)
            assert (merged['_merge']=='both').all(),(table,group,reference_group)
            return (merged[metric+'_x']-merged[metric+'_y']).to_numpy(),len(merged)
        return a[metric].to_numpy(),len(a)

    def row(self,table,group,metric,kind='mean',reference=None,reference_group=None,scale=None,**extra):
        if scale is None:scale=100. if metric in PERCENT else 1.
        values,total=self.vector(table,group,metric,kind,reference,reference_group)
        record=dict(table=table,input_table=self.paths[table],group=json.dumps(group,sort_keys=True),metric=metric,
            kind=kind,reference_table=reference or '',reference_group=json.dumps(reference_group or {},sort_keys=True),
            scale=scale,n_total=total,**stat(np.asarray(values)*scale),**group,**extra)
        record['interval_interpretation']=('descriptive shared-source scenario t interval; not independent solar records'
            if table=='solar' else 'unadjusted 95% t across matched seed differences' if kind=='paired'
            else 'unadjusted 95% t across seed-level observations')
        record['n_valid_pairs']=record['n_valid'] if kind=='paired' else np.nan
        return record

    def summary(self,table,groups,metrics):
        rows=[]
        for key,g in self.frames[table].groupby(groups,sort=True):
            key=key if isinstance(key,tuple) else (key,);group=dict(zip(groups,key))
            for metric in metrics:rows.append(self.row(table,group,metric))
        return pd.DataFrame(rows)

    def save(self,fig,name,rows,caption,role,original='',function=''):
        directory=self.out/name;directory.parent.mkdir(parents=True,exist_ok=True)
        df=pd.DataFrame(rows);data_path='plotted_data/'+name.replace('/','__')+'.csv';self.write(data_path,df)
        fig.canvas.draw()
        for ax in fig.axes:
            ax.grid(alpha=.18);ax.spines[['top','right']].set_visible(False)
        fig.savefig(str(directory)+'.pdf',bbox_inches='tight',pad_inches=.08)
        fig.savefig(str(directory)+'.png',dpi=300,bbox_inches='tight',pad_inches=.08)
        plt.close(fig)
        sources=sorted({self.paths[key] for key in df.table})
        for key in df.reference_table.dropna():
            if key:sources.append(self.paths[key])
        self.figures.append(dict(figure_id=name,role=role,pdf=name+'.pdf',png=name+'.png',plotted_data=data_path,
            input_tables=';'.join(sorted(set(sources))),analysis_code='prepare_report_figures.py:'+function,
            original_plot=original,caption=caption))
        self.points.extend(rows)


def style():
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':9,'axes.titlesize':10,'axes.labelsize':9,
        'legend.fontsize':8,'legend.frameon':False,'pdf.fonttype':42,'ps.fonttype':42,'figure.dpi':120,
        'savefig.dpi':300,'axes.spines.top':False,'axes.spines.right':False,'lines.linewidth':1.4,
        'lines.markersize':4,'axes.formatter.useoffset':False})


def policy_legend(fig,policies,ncol=3):
    handles=[Line2D([],[],color=COLORS[p],marker=MARKERS[p],label=LABELS[p],markeredgecolor='#333333',markeredgewidth=.4) for p in policies]
    fig.legend(handles=handles,loc='outside lower center',ncol=ncol)


def line(ax,rows,policy,x='channel_sigma',style='-'):
    d=pd.DataFrame(rows).sort_values(x)
    ax.errorbar(d[x],d['mean'],yerr=d.ci_half,color=COLORS[policy],marker=MARKERS[policy],linestyle=style,capsize=2,
                markeredgecolor='#333333',markeredgewidth=.4)


def synthetic_support(r):
    for folder in ('sweep','sweep_normalized'):
        for metric,stem in [('common_score','realized_cost'),('drop_ratio','drop_ratio'),('queue','queue'),('energy','energy'),('coverage_gain','coverage_gain')]:
            fig,axes=plt.subplots(1,2,figsize=(9.2,3.8),layout='constrained');rows=[]
            policies=[p for p in POLICIES if p!='greedy' or metric!='coverage_gain']
            for ax,h in zip(axes,(.6,1.2)):
                for p in policies:
                    points=[r.row(folder,dict(harvest_mean=h,channel_sigma=s,mode=p),metric) for s in (.2,.45,.8)]
                    line(ax,points,p);rows+=points
                ax.set(title=f'Mean harvest {h:g} J / interval',xlabel='Log-channel innovation standard deviation, σ',
                       ylabel='Empirical channel lower-bound coverage (%)' if metric=='coverage_gain' else Y_LABEL[metric],xticks=[.2,.45,.8])
            policy_legend(fig,policies);variant='Stationary mean-normalized' if folder.endswith('normalized') else 'Original, non-mean-normalized'
            fig.suptitle(variant+' synthetic channel · 5 s intervals',fontsize=11)
            caption=f'{variant} channel; each point averages ten matched seed runs, each 1000 five-second intervals. Error bars are unadjusted 95% seed-level t intervals for means, not paired-effect tests. '+('Coverage is empirical, not a guarantee. ' if metric=='coverage_gain' else '')+'Paired contrasts are in the performance tables. Original σ changes average gain as well as higher moments; normalization fixes theoretical mean only.'
            r.save(fig,f'supporting/{folder}/{stem}',rows,caption,'supporting',f'{folder}/{stem}.png','synthetic_support')


def solar_plots(r,main=False,paired_only=False):
    if main:
        fig,axes=plt.subplots(1,3,figsize=(8.2,3.5),sharey=True,layout='constrained');rows=[]
        contrasts=[('nominal','greedy'),('adaptive_all','greedy'),('adaptive_all','nominal')]
        for ax,dataset in zip(axes,('arco','umass_home_c','nrel_tmy3')):
            for i,(p,base) in enumerate(contrasts):
                point=r.row('solar',dict(dataset=dataset,mode=p),'common_score',kind='paired',reference='solar',
                    reference_group=dict(dataset=dataset,mode=base),comparison=f'{p} - {base}',bar_order=i)
                rows.append(point)
                ax.errorbar(point['mean'],i,xerr=point['ci_half'],color=COLORS[p],marker=['^','X','o'][i],
                    linestyle='none',capsize=3,markersize=6,markeredgecolor='#333333',markeredgewidth=.5)
            ax.axvline(0,color='#777777',lw=.8)
            ax.set(title=SOURCES[dataset],yticks=range(3),yticklabels=['Nominal MPC\n− Greedy','Adaptive-all MPC\n− Greedy','Adaptive-all MPC\n− Nominal MPC'],
                   xlabel='Paired weighted-score difference')
            ax.ticklabel_format(axis='x',style='sci',scilimits=(-3,4),useMathText=True)
        axes[0].invert_yaxis()
        caption='Ten matched scenarios per source, 1000 intervals each. Two contrasts compare convex MPC with greedy; the third compares the MPC forecast-margin strategies. Negative means lower weighted score. Bars are unadjusted 95% descriptive paired-scenario t intervals, not independent solar-record confidence intervals. Shared source/site/season dependence remains; nine NREL window pairs overlap. ARCO/UMass intervals are 60 s, NREL 3600 s. All ten policies remain in the supporting figures/tables; physical delay and throughput comparisons stay within source.'
        r.save(fig,'main/02_solar_paired_cost',rows,caption,'main',function='solar_plots')
        return
    metrics=[('common_score','realized_cost'),('drop_ratio','drop_ratio'),('queue','queue'),('energy','energy')]
    if main or paired_only:metrics=[('common_score','solar_paired_cost')]
    for metric,stem in metrics:
        paired=stem=='solar_paired_cost';policies=[p for p in SOLAR_POLICIES if p!='nominal'] if paired else SOLAR_POLICIES
        fig,axes=plt.subplots(1,3,figsize=((8.2 if main else 10.4),4.8),sharey=True,layout='constrained');rows=[]
        for ax,dataset in zip(axes,('arco','umass_home_c','nrel_tmy3')):
            for i,p in enumerate(policies):
                g=dict(dataset=dataset,mode=p)
                point=r.row('solar',g,metric,kind='paired',reference='solar',reference_group=dict(dataset=dataset,mode='nominal')) if paired else r.row('solar',g,metric)
                point['bar_order']=i;rows.append(point)
                ax.errorbar(point['mean'],i,xerr=point['ci_half'],color=COLORS[p],marker=MARKERS[p],linestyle='none',capsize=2,
                            markersize=5,markeredgecolor='#333333',markeredgewidth=.5)
            if paired:ax.axvline(0,color='#777777',linewidth=.8)
            ax.set(title=SOURCES[dataset],yticks=range(len(policies)),yticklabels=[LABELS[p] for p in policies],
                   xlabel='Score difference\n(policy − nominal MPC)' if paired else Y_LABEL[metric])
            ax.invert_yaxis()
            if metric=='drop_ratio':ax.set_xlim(left=min(0,ax.get_xlim()[0]))
            ax.ticklabel_format(axis='x',style='sci',scilimits=(-3,4),useMathText=True)
        caption='Ten matched scenarios per source, 1000 intervals each. '+('Points are paired policy-minus-nominal weighted-score differences; negative is lower. ' if paired else 'Points are run-level means. ')+'Intervals are descriptive paired-scenario t intervals for differences (or descriptive scenario intervals for means), not independent-record confidence intervals. Shared source/site/season dependence remains; nine NREL window pairs overlap. ARCO/UMass intervals are 60 s, NREL 3600 s; physical delays/throughput are compared within a source.'
        name='main/02_solar_paired_cost' if main else 'supporting/figures/solar_paired_cost' if paired else f'supporting/solar/{stem}'
        r.save(fig,name,rows,caption,'main' if main else 'supporting','figures/solar_paired_cost.png' if paired else f'solar/{stem}.png','solar_plots')


def normalized_comparisons(r):
    fig,axes=plt.subplots(2,2,figsize=(7.8,5.7),layout='constrained');rows=[]
    contrasts=[('nominal','greedy','-'),('adaptive_all','greedy','-'),('adaptive_all','nominal','--')]
    for j,h in enumerate((.6,1.2)):
        for i,metric in enumerate(('common_score','drop_ratio')):
            ax=axes[i,j]
            for p,base,ls in contrasts:
                pts=[r.row('sweep_normalized',dict(harvest_mean=h,channel_sigma=s,mode=p),metric,kind='paired',
                    reference='sweep_normalized',reference_group=dict(harvest_mean=h,channel_sigma=s,mode=base),comparison=f'{p} - {base}') for s in (.2,.45,.8)]
                line(ax,pts,p,style=ls);rows+=pts
            ax.axhline(0,color='#777777',lw=.8)
            ax.set(title=f'Mean harvest {h:g} J / interval' if i==0 else '',xticks=[.2,.45,.8],
                   xlabel='Channel innovation σ',ylabel='Cost difference\n(weighted score)' if i==0 else 'Rejection difference\n(percentage points)')
    handles=[Line2D([],[],color=COLORS[p],marker=MARKERS[p],ls=ls,label=f'{LABELS[p]} − {LABELS[b]}') for p,b,ls in contrasts]
    fig.legend(handles=handles,loc='outside lower center',ncol=1,fontsize=8)
    caption='Normalized synthetic channel, 1000 five-second intervals per run. Differences pair the same ten seeds within every harvest/σ condition; bars are unadjusted 95% t intervals. Solid curves compare each convex MPC policy with greedy; the dashed contrast compares their forecast-margin strategies. Negative values mean lower cost or rejection. No slots or packets are treated as independent repetitions; higher moments still vary with σ.'
    r.save(fig,'main/01_normalized_cost_rejection',rows,caption,'main',function='normalized_comparisons')


def coverage_plot(r,main=False):
    fig,axes=plt.subplots(1,3,figsize=(7.8,3.4),sharey=True,layout='constrained');rows=[]
    policies=['nominal','fixed_margin','adaptive_harvest','adaptive_all']
    for ax,metric,title in zip(axes,('coverage_gain','coverage_arrival','coverage_harvest'),('Channel lower bound','Arrival upper bound','Harvest lower bound')):
        for i,p in enumerate(policies):
            point=r.row('sweep_normalized',dict(mode=p),metric,kind='seed_mean');point['bar_order']=i;rows.append(point)
            ax.errorbar(i,point['mean'],yerr=point['ci_half'],color=COLORS[p],marker=MARKERS[p],linestyle='none',capsize=3,markersize=6)
        ax.axhline(80,color='#777777',ls='--',lw=.9);ax.set(title=title,ylim=(0,100),xticks=range(4),
            xticklabels=['Nominal','Fixed\nmargin','Harvest\nmargin','Adaptive\nall'])
        ax.tick_params(axis='x',labelsize=8)
    axes[0].set_ylabel('Empirical bound coverage (%)')
    caption='All displayed policies are convex MPC. Normalized conditions are averaged within each seed before averaging across ten seeds; unadjusted 95% t intervals use those ten seed means. Adaptive-all coverage is approximately 79%, not a guaranteed 80%. The dashed 80% line is a reference only. Coverage is one-step empirical report-based coverage, not simultaneous horizon coverage or a chance-constraint guarantee.'
    r.save(fig,'main/05_empirical_coverage' if main else 'supporting/figures/one_step_coverage',rows,caption,'main' if main else 'supporting','figures/one_step_coverage.png','coverage_plot')


def delay_plot(r,folder,main=False):
    energy_study=folder.endswith('delay_energy');levels=[.15,15.,150.] if energy_study else [0.,.25,.5]
    metrics=['mean_ack_completion_delay_s'] if main else ['mean_initial_wait_s','mean_ack_completion_delay_s','newly_unfinished_fraction']
    fig,axes=plt.subplots(len(metrics),2,figsize=(7.8,3.9) if main else (9.5,8.8),squeeze=False,layout='constrained');rows=[]
    for j,h in enumerate((.6,1.2)):
        for i,metric in enumerate(metrics):
            ax=axes[i,j]
            for policy in ('nominal','adaptive_all'):
                pts=[]
                for k,value in enumerate(levels):
                    group=dict(harvest_mean=h,study_value=value,mode=policy)
                    point=r.row(folder,group,metric);energy=r.row(folder,group,'energy')
                    point.update(x_mean=energy['mean'],x_ci_half=energy['ci_half'],x_ci_low=energy['ci_low'],x_ci_high=energy['ci_high'])
                    pts.append(point);rows.append(point)
                    size=[9,6,5][k]+(1 if policy=='adaptive_all' else 0)
                    ax.errorbar(point['x_mean'],point['mean'],xerr=point['x_ci_half'],yerr=point['ci_half'],
                        color=COLORS[policy],marker=['o','s','^'][k],markersize=size,markerfacecolor='white',
                        markeredgewidth=1.2,linestyle='none',capsize=2,alpha=.9)
                ax.plot([p['x_mean'] for p in pts],[p['mean'] for p in pts],color=COLORS[policy],ls='-' if policy=='nominal' else '--',lw=1)
            ax.set(title=f'Mean harvest {h:g} J / interval' if i==0 else '',xlabel='Mean total TX energy\n(J per 1000-slot episode)',ylabel=Y_LABEL[metric])
    handles=[Line2D([],[],color=COLORS[p],ls='-' if p=='nominal' else '--',label=LABELS[p]) for p in ('nominal','adaptive_all')]
    handles.extend(Line2D([],[],color='#444444',marker=m,ms=sz,mfc='white',ls='none',label=f'{"w" if energy_study else "a"}={v:g}') for v,m,sz in zip(levels,['o','s','^'],[8,6,5]))
    fig.legend(handles=handles,loc='outside lower center',ncol=5,fontsize=8)
    caption=('Energy weight is constant at 0.15, 15 or 150 throughout each run. ' if energy_study else 'Added future-channel forecast noise amplitudes are 0, 0.25 and 0.50; energy weight stays 0.15. ')+ 'Ten matched synthetic seeds per setting; 1000 five-second intervals. Both axes use run-level means and unadjusted 95% t intervals; they are not a joint confidence region. Shapes encode settings; nested open markers retain coincident points without jitter. Connected points are an empirical trade-off, not a certified Pareto frontier. Initial packets are excluded from primary delay cohorts. Completed-only delays include retries/ACK waiting; rejected arrivals were never admitted. See delay_cohorts.csv for admissions, completions, valid samples, rejection, throughput and unfinished fractions; shorter completed-only delay is not sufficient evidence of better overall service.'
    stem='main/03_energy_ack_delay' if main else f'supporting/{folder}/delay_energy'
    r.save(fig,stem,rows,caption,'main' if main else 'supporting',f'{folder}/delay_energy.png','delay_plot')


def forecast_error_plot(r,folder):
    fig,axes=plt.subplots(2,2,figsize=(8.8,6.2),layout='constrained');rows=[];key=folder+'/errors'
    for i,p in enumerate(('nominal','adaptive_all')):
        for j,h in enumerate((.6,1.2)):
            ax=axes[i,j]
            levels=[0.,.25,.5] if folder.endswith('forecast_sensitivity') else [.15,15.,150.]
            for value,ls,m in zip(levels,['-','--',':'],['o','s','^']):
                pts=[r.row(key,dict(harvest_mean=h,mode=p,study_value=value,forecast_kind='perturbed',decision_lead=lead),'rmse') for lead in range(1,10)]
                d=pd.DataFrame(pts);rows+=pts
                ax.plot(d.decision_lead,d['mean'],color=COLORS[p],ls=ls,marker=m,ms=3)
                ax.fill_between(d.decision_lead,d.ci_low,d.ci_high,color=COLORS[p],alpha=.07)
            ax.set(title=f'{LABELS[p]} · harvest {h:g} J',xlabel='Lead from decision origin (intervals)',ylabel='Perturbed pre-margin forecast\nRMSE (1/W)')
    prefix='a' if folder.endswith('forecast_sensitivity') else 'w'
    fig.legend(handles=[Line2D([],[],color='#444444',ls=ls,marker=m,label=f'{prefix}={v:g}') for v,ls,m in zip(levels,['-','--',':'],['o','s','^'])],loc='outside lower center',ncol=3)
    caption='Quantity shown is the perturbed base channel forecast before uncertainty margins, evaluated against post-run actual gains at the labeled decision lead. Policy panels separate overlapping curves; policies, base forecasts and margin-adjusted forecasts are not pooled. Each line averages ten per-run RMSEs with unadjusted seed-level 95% t bands; slots are not repetitions. Gain/RMSE units are effective SNR per watt (1/W), not RSSI. Zero added noise retains channel-process forecast error; current probe reports remain ideal. All three forecast quantities remain separate in forecast_error_by_lead.csv.'
    r.save(fig,f'supporting/{folder}/channel_forecast_errors',rows,caption,'supporting',f'{folder}/channel_forecast_errors.png','forecast_error_plot')


def noise_outcomes(r,paired):
    folder='supplementary/forecast_sensitivity';fig,axes=plt.subplots(3,2,figsize=(7.8,6.5),layout='constrained');rows=[]
    for j,h in enumerate((.6,1.2)):
        for i,metric in enumerate(('common_score','drop_ratio','mean_ack_completion_delay_s')):
            ax=axes[i,j]
            for p in (['adaptive_all'] if paired else ['nominal','adaptive_all']):
                pts=[]
                for value in (0.,.25,.5):
                    group=dict(harvest_mean=h,mode=p,study_value=value)
                    point=r.row(folder,group,metric,kind='paired' if paired else 'mean',reference=folder if paired else None,
                        reference_group=dict(harvest_mean=h,mode='nominal',study_value=value) if paired else None)
                    pts.append(point);rows.append(point)
                line(ax,pts,p,x='study_value')
            if paired:ax.axhline(0,color='#777777',lw=.8)
            label=('Score difference\n(adaptive-all − nominal)' if metric=='common_score' else 'Rejection difference\n(percentage points)' if metric=='drop_ratio' else 'ACK-delay difference (s)') if paired else Y_LABEL[metric]
            ax.set(title=f'Mean harvest {h:g} J / interval' if i==0 else '',xlabel='Added channel-forecast noise, a',ylabel=label,xticks=[0,.25,.5])
    if not paired:policy_legend(fig,['nominal','adaptive_all'],ncol=2)
    caption=('Paired adaptive-all minus nominal MPC responses; each amplitude uses the same ten scenario seeds and common exogenous traces. Negative means lower score/rejection/completed ACK delay. ' if paired else 'Absolute nominal/adaptive-all responses use means across ten seed runs; paired policy differences are shown separately in main figure 04. ')+ 'Error bars are unadjusted 95% seed-level t intervals. Actual channel remains normalized rho=0.68, sigma=0.45; only future channel forecasts are perturbed. No independent arrival/harvest forecast-error intervention occurred. Zero added noise still has process forecast error. ACK delay is completed-only; the companion cohort table retains admissions, completions, rejection, throughput and unfinished fractions. Common-reference score always uses energy weight 0.15.'
    r.save(fig,'main/04_forecast_noise_paired' if paired else 'supporting_extra/forecast_noise_outcomes',rows,caption,'main' if paired else 'extra',function='noise_outcomes')


def report_tables(r):
    metrics=CORE_METRICS+['median_initial_wait_s','median_ack_completion_delay_s','newly_attempted_packets',
        'newly_completed_fraction','admission_fraction','rejected_arrivals','outstanding_packets',
        'initial_wait_samples','ack_completion_delay_samples','initial_wait_unfinished_packets','ack_completion_delay_unfinished_packets']
    summaries=[];cohorts=[];performance=[];weights=[];noise=[];forecast=[]
    for folder in SPEC:
        d=r.frames[folder]
        groups=['dataset','mode'] if folder=='solar' else ['harvest_mean','channel_sigma','mode'] if folder.startswith('sweep') else ['harvest_mean','study_value','mode']
        summary=r.summary(folder,groups,metrics);summaries.append(summary.assign(study_group=folder))
        cohort_cols=[c for c in d if c in {'run_id','seed','mode','dataset','window','harvest_mean','channel_sigma','study_value','energy_weight','forecast_perturbation','queue','drop_ratio','energy','throughput','common_score','offered_arrivals','rejected_arrivals'}
                     or c.startswith('initial_') or 'never_attempted' in c
                     or any(k in c for k in ('wait','ack_completion','outstanding','newly_','offered_completion','admission_fraction'))]
        cohorts.append(d[cohort_cols].assign(study_group=folder))
        condition=[c for c in groups if c!='mode']
        for values,g in d.groupby(condition):
            values=values if isinstance(values,tuple) else (values,);base_group=dict(zip(condition,values))
            for p in sorted(g['mode'].unique()):
                for base in (['greedy','nominal','fixed_margin'] if not folder.startswith('supplementary') else ['nominal','greedy']):
                    if p==base:continue
                    borrowed=folder.startswith('supplementary') and base=='greedy'
                    ref='sweep_normalized' if borrowed else folder
                    ref_group=dict(harvest_mean=base_group['harvest_mean'],channel_sigma=.45,mode=base) if borrowed else base_group|dict(mode=base)
                    for metric in CORE_METRICS:
                        row=r.row(folder,base_group|dict(mode=p),metric,kind='paired',reference=ref,reference_group=ref_group)
                        row.update(study_group=folder,policy=p,baseline=base,reference_origin='matched normalized-main greedy reused; no new execution' if borrowed else 'within-study matched condition')
                        performance.append(row)
        if folder.startswith('supplementary'):
            baseline=.15 if folder.endswith('delay_energy') else 0.
            for h in (.6,1.2):
                for p in ('nominal','adaptive_all'):
                    for value in sorted(d.study_value.unique()):
                        if value==baseline:continue
                        for metric in CORE_METRICS:
                            row=r.row(folder,dict(harvest_mean=h,mode=p,study_value=value),metric,kind='paired',reference=folder,
                                reference_group=dict(harvest_mean=h,mode=p,study_value=baseline),baseline_value=baseline)
                            (weights if folder.endswith('delay_energy') else noise).append(row)
            forecast.append(r.summary(folder+'/errors',['harvest_mean','mode','study_value','forecast_kind','decision_lead'],['mae','rmse']))
    r.write('tables/performance_summary.csv',pd.concat(summaries,ignore_index=True))
    r.write('tables/delay_cohorts.csv',pd.concat(cohorts,ignore_index=True))
    service=[]
    for folder,d in ((key,r.frames[key]) for key in SPEC):
        grouping=['dataset','mode'] if folder=='solar' else ['harvest_mean','channel_sigma','mode'] if folder.startswith('sweep') else ['harvest_mean','study_value','mode']
        for key,g in d.groupby(grouping):
            key=key if isinstance(key,tuple) else (key,)
            row=dict(zip(grouping,key))|dict(study_group=folder,n_runs=len(g))
            for field in ('newly_admitted_packets','newly_attempted_packets','newly_acknowledged_packets',
                          'initial_wait_samples','ack_completion_delay_samples','initial_wait_unfinished_packets',
                          'ack_completion_delay_unfinished_packets','rejected_arrivals','initial_packets','outstanding_packets'):
                row[field+'_total']=int(g[field].sum())
            for field in ('mean_initial_wait_s','median_initial_wait_s','mean_ack_completion_delay_s','median_ack_completion_delay_s','throughput','energy','queue'):
                row[field+'_run_mean']=g[field].mean();row[field+'_valid_runs']=int(g[field].notna().sum())
            for field in ('drop_ratio','newly_completed_fraction','newly_unfinished_fraction','offered_completion_fraction'):
                row[field+'_run_mean_pct']=100*g[field].mean()
            service.append(row)
    r.write('tables/delay_service_summary.csv',pd.DataFrame(service))
    r.write('tables/performance_paired.csv',pd.DataFrame(performance))
    r.write('tables/energy_weight_comparisons.csv',pd.DataFrame(weights))
    r.write('tables/forecast_noise_baseline_comparisons.csv',pd.DataFrame(noise))
    r.write('tables/forecast_error_by_lead.csv',pd.concat(forecast,ignore_index=True))
    r.write('tables/configured_and_common_scores.csv',r.summary('supplementary/delay_energy',['harvest_mean','study_value','mode'],['configured_objective_cost','common_score','energy']))
    # Coverage: each seed first averages the six normalized harvest/sigma conditions.
    coverage=[]
    for p in POLICIES[1:]:
        for metric in ('coverage_gain','coverage_arrival','coverage_harvest'):
            coverage.append(r.row('sweep_normalized',dict(mode=p),metric,kind='seed_mean'))
    r.write('tables/empirical_coverage.csv',pd.DataFrame(coverage))
    pairs=r.frames['offline_pairs'].copy();records=[]
    pairs['comparison_condition']=pairs['window'].where(pairs.dataset=='synthetic','ten matched source scenarios')
    for key,g in pairs.groupby(['dataset','comparison_condition','channel_sigma','mode'],dropna=False):
        dataset,window,sigma,mode=key
        records.append(dict(dataset=dataset,scenario_definition=window,channel_sigma=sigma,mode=mode,
            **stat(g.online_minus_offline),interval_interpretation='descriptive shared-source paired-scenario interval' if dataset!='synthetic' else 'unadjusted paired-seed 95% t interval',
            interpretation='descriptive online score minus relaxed expected-goodput reference; not a pathwise bound; no packet-delay optimum'))
    r.write('tables/offline_reference_differences.csv',pd.DataFrame(records))
    r.write('tables/solver_checks.csv',r.frames['solver'])


def runtime_table(r):
    rows=[];cached=r.source/'runtime_by_run.csv'
    if cached.exists():
        runtime=pd.read_csv(cached);scope='runtime metadata reused from packaged capsule'
    else:
        scope='streamed solver-name/status/time/t/run-ID metadata only; no packet/battery ledger audit replay'
        for folder in SPEC:
            accum={};statuses={}
            for chunk in pd.read_csv(r.source/folder/'per_slot.csv',usecols=['run_id','solver_name','solver_status','solver_runtime_s','t'],chunksize=50000):
                assert chunk.solver_runtime_s.ge(0).all() and chunk.t.between(0,999).all()
                for run_id,g in chunk.groupby('run_id',sort=False):
                    count,seconds,slots,mask=accum.get(run_id,(0,0.,0,0))
                    assert len(g.t.unique())==len(g)
                    new=0
                    for t in g.t:new|=1<<int(t)
                    assert not mask&new
                    counts=statuses.setdefault(run_id,{})
                    for status,n in g[g.solver_name!='none'].solver_status.value_counts().items():
                        counts[status]=counts.get(status,0)+int(n)
                    accum[run_id]=(count+int((g.solver_name!='none').sum()),seconds+float(g.solver_runtime_s.sum()),slots+len(g),mask|new)
            assert set(accum)==set(r.frames[folder].run_id)
            for run_id,(calls,seconds,slots,mask) in accum.items():
                assert slots==1000 and mask==(1<<1000)-1
                assert sum(statuses[run_id].values())==calls
                rows.append(dict(study_group=folder,run_id=run_id,optimization_calls=calls,total_solver_seconds=seconds,
                    accepted_optimal_calls=statuses[run_id].get('optimal',0),accepted_inaccurate_calls=statuses[run_id].get('optimal_inaccurate',0),
                    accepted_other_calls=sum(n for s,n in statuses[run_id].items() if s not in ('optimal','optimal_inaccurate')),
                    solver_ms_per_interval=seconds,solver_ms_per_call=1000*seconds/calls if calls else np.nan,slots=slots))
        runtime=pd.DataFrame(rows)
    assert len(runtime)==1140 and not runtime.duplicated(['study_group','run_id']).any()
    combined=[]
    for folder in SPEC:
        d=r.frames[folder].merge(runtime[runtime.study_group==folder],on='run_id',validate='one_to_one')
        np.testing.assert_allclose(d.mean_solve_ms,d.solver_ms_per_interval,rtol=1e-10,atol=1e-9)
        if 'optimization_calls_x' in d:np.testing.assert_array_equal(d.optimization_calls_x,d.optimization_calls_y)
        cols=[c for c in ('study_group','run_id','mode','dataset','harvest_mean','channel_sigma','study_value','energy_weight',
            'max_violation','inaccurate','solver_budget_exceedances','decision_budget_exceedances','mean_decision_ms',
            'optimization_calls','optimization_calls_y','accepted_optimal_calls','accepted_inaccurate_calls','accepted_other_calls',
            'solver_ms_per_interval','solver_ms_per_call','total_solver_seconds') if c in d]
        part=d[cols].rename(columns={'optimization_calls_y':'optimization_calls'})
        combined.append(part)
    by_run=pd.concat(combined,ignore_index=True)
    np.testing.assert_array_equal(by_run.inaccurate,by_run.accepted_inaccurate_calls)
    assert by_run.accepted_other_calls.sum()==0
    r.write('tables/solver_runtime_by_run.csv',by_run)
    overview=[]
    for (study,mode),g in by_run.groupby(['study_group','mode']):
        calls=int(g.optimization_calls.sum());seconds=g.total_solver_seconds.sum()
        overview.append(dict(study_group=study,mode=mode,n_runs=len(g),optimization_calls=calls,
            accepted_optimal_calls=int(g.accepted_optimal_calls.sum()),accepted_inaccurate_calls=int(g.accepted_inaccurate_calls.sum()),
            accepted_other_calls=int(g.accepted_other_calls.sum()),max_saved_plan_violation=g.max_violation.max(),
            solver_budget_exceedances=int(g.solver_budget_exceedances.sum()),decision_budget_exceedances=int(g.decision_budget_exceedances.sum()),
            solver_ms_per_interval=1000*seconds/(1000*len(g)),solver_ms_per_optimization_call=1000*seconds/calls if calls else np.nan))
    r.write('tables/solver_runtime_summary.csv',pd.DataFrame(overview))
    r.write('inputs/runtime_by_run.csv',runtime)
    r.validation['checks_now'].append(scope)


def validate_points(r):
    tested=0
    for p in r.points:
        group=json.loads(p['group']);ref_group=json.loads(p['reference_group']);a=choose(r.frames[p['table']],group)
        if p['kind']=='paired':
            b=choose(r.frames[p['reference_table']],ref_group);keys=['window','seed'] if p['table']=='solar' else ['seed']
            left={tuple(row[k] for k in keys):row[p['metric']] for row in a.to_dict('records')}
            right={tuple(row[k] for k in keys):row[p['metric']] for row in b.to_dict('records')}
            assert set(left)==set(right)
            values=[(left[k]-right[k])*p['scale'] for k in left if np.isfinite(left[k]) and np.isfinite(right[k])]
        elif p['kind']=='seed_mean':
            values=[]
            for seed in sorted(a.seed.unique()):
                selected=[float(x) for x in a[a.seed==seed][p['metric']] if np.isfinite(x)]
                if selected:values.append(math.fsum(selected)/len(selected)*p['scale'])
        else:values=[float(x)*p['scale'] for x in a[p['metric']] if np.isfinite(x)]
        n=len(values);mean=math.fsum(values)/n if n else np.nan
        sd=math.sqrt(math.fsum((x-mean)**2 for x in values)/(n-1)) if n>1 else np.nan
        half=float(student_t.ppf(.975,n-1))*sd/math.sqrt(n) if n>1 else np.nan
        assert p['n_valid']==n
        np.testing.assert_allclose([p['mean'],p['std'],p['ci_low'],p['ci_high'],p['ci_half']],
            [mean,sd,mean-half,mean+half,half],rtol=1e-10,atol=1e-8,equal_nan=True)
        if 'x_mean' in p:
            energy=a.energy.dropna().to_numpy();em=math.fsum(energy)/len(energy)
            eh=float(student_t.ppf(.975,len(energy)-1))*np.std(energy,ddof=1)/np.sqrt(len(energy))
            np.testing.assert_allclose([p['x_mean'],p['x_ci_half']],[em,eh],rtol=1e-10,atol=1e-8)
        tested+=1
    r.validation['plotted_point_interval_checks']=tested
    r.validation['checks_now'].append('every plotted mean/difference/CI/sample count independently recomputed with fsum and sample-variance formulas against saved rows; x-axis energy intervals checked separately')
    # Saved paired tables are cross-checks, not the estimator implementation.
    cross=0
    for folder in SPEC:
        saved=pd.read_csv(r.source/folder/'paired_vs_nominal.csv')
        for point in r.points:
            if point['table']!=folder or point['kind']!='paired':continue
            g=json.loads(point['group']);ref=json.loads(point['reference_group'])
            if ref.get('mode')!='nominal':continue
            metric='realized_cost' if point['metric']=='common_score' and not folder.startswith('supplementary') else 'common_reference_cost' if point['metric']=='common_score' else point['metric']
            selected=saved[(saved.metric==metric)&(saved.method==g['mode'])]
            for k in ('harvest_mean','channel_sigma','dataset','study_value'):
                if k in g:selected=selected[selected[k]==g[k]]
            assert len(selected)==1
            old=selected.iloc[0]
            np.testing.assert_allclose([point['mean'],point['ci_low'],point['ci_high']],
                np.array([old.delta,old.ci_low,old.ci_high])*point['scale'],rtol=1e-10,atol=1e-8,equal_nan=True)
            assert point['n_valid']==old.n_valid_pairs;cross+=1
    r.validation['saved_paired_crosschecks']=cross
    for figure in r.figures:
        png=r.out/figure['png'];pdf=r.out/figure['pdf']
        with Image.open(png) as image:
            assert image.width>500 and image.height>400 and abs(image.info['dpi'][0]-300)<1
        assert pdf.read_bytes().startswith(b'%PDF')
        assert b'/Subtype /Image' not in pdf.read_bytes(),'unexpected rasterized data in PDF'
    r.validation['checks_now'].append('all figures exported as vector PDF and 300-dpi PNG; data and caption/index mappings checked')


def findings(r):
    rows=pd.read_csv(r.out/'tables/performance_paired.csv')
    normalized=rows[(rows.study_group=='sweep_normalized')&(rows.policy=='adaptive_all')&(rows.baseline=='nominal')&(rows.metric=='common_score')]
    lines=['# Findings for a 5–7-page report (evidence notes, not the report)',
      '', '## Supported numerical descriptions',
      '- Nominal and adaptive-all are both convex MPC policies. Greedy comparisons measure a separate planning-versus-heuristic contrast; adaptive-all minus nominal isolates their forecast-margin strategies within this simulation.',
      '- Adaptive-all is not universally best. Keep all harvest/volatility conditions and the fixed-margin/greedy references, including equal and unfavorable outcomes.']
    for row in normalized.itertuples(index=False):
        lines.append(f'- Normalized harvest {row.harvest_mean:g} J, σ={row.channel_sigma:g}: adaptive-all minus nominal common score = {row.mean:.2f}, unadjusted paired 95% t interval [{row.ci_low:.2f}, {row.ci_high:.2f}], {row.n_valid_pairs:g} valid seed pairs.')
    cov=pd.read_csv(r.out/'tables/empirical_coverage.csv');values=cov[cov['mode']=='adaptive_all']
    lines.append('- Adaptive-all empirical coverage after averaging conditions within each seed: '+', '.join(f'{row.metric}={row.mean:.2f}%' for row in values.itertuples(index=False))+'. This is approximately 79%, not a guaranteed 80%.')
    d=r.frames['supplementary/delay_energy']
    for h in (.6,1.2):
        for p in ('nominal','adaptive_all'):
            base=choose(d,dict(harvest_mean=h,mode=p,study_value=.15));high=choose(d,dict(harvest_mean=h,mode=p,study_value=150.))
            lines.append(f'- Weight sensitivity, harvest {h:g}, {LABELS[p]}: mean episode energy {base.energy.mean():.2f} → {high.energy.mean():.2f} J and completed ACK delay {base.mean_ack_completion_delay_s.mean():.3f} → {high.mean_ack_completion_delay_s.mean():.3f} s (w=0.15 → 150). These descriptive means require the paired score/cohort/rejection/throughput tables; they do not establish a Pareto frontier.')
    lines+=['', '## Interpretation limits',
      '- All uncertainty intervals here are unadjusted 95% t intervals; ten matched seed pairs within each condition, not 1000 independent slots or individual packets. They are exploratory/descriptive across many conditions; no familywise significance claim or normality certification is made.',
      '- Completed-packet delays condition on admissions and observed completions. Initial packets are excluded; rejected arrivals were not admitted; missing/unfinished delays are not zero. Rejection, offered-completion rate, throughput and unfinished counts must accompany delay interpretations.',
      '- The solar comparisons use dependent windows from shared sources/sites/seasons, including nine overlapping NREL pairs. Their intervals are descriptive rather than independent-record confidence intervals. Delays and bits/s must be compared within each source (60/60/3600 s).',
      '- Added noise affects future channel forecasts only; zero added noise retains process error, and current probe reports remain ideal. Curves distinguish base/perturbed/planned quantities. Arrival/harvest forecast error was not independently intervened on.',
      '- Main normalized σ changes channel higher moments; original σ also changes average gain. Neither main volatility sweep is a controlled forecast-error-only intervention.',
      '- Common-reference cost uses energy weight 0.15 for every comparison. Configured scores at different weights are not the same scoring function.',
      '- The offline reference uses perfect future inputs, continuous expected goodput and relaxed future controls/admission. Score gaps are descriptive, not pathwise bounds or an optimal packet-delay benchmark.',
      '- Online convex planning uses continuous attempted service and expected-success queue dynamics; physical execution uses integer actions 0–5 and ACK-only packet departures. Future control activity is relaxed in planning. These distinctions remain part of the model, not a plotting correction.',
      '- Adaptive forecast margins remain included; adaptive penalty updates are excluded. No claim of real-hardware or universal policy superiority follows from these simulations.',
      '', '## Validation scope',
      '- Checks performed now: completion/matrices/run-level identities and formulas, runtime-metadata extraction, every plotted estimate/interval/count, metadata/units/missing values, figure exports, and full before/after production-file hashes.',
      '- Previously completed audits: packet events, battery trajectories, ACK/retry/deduplication, delay ledgers, full forecast reconstruction and source/raw offline-plan audits. Reports were checked as passed; these raw audits were not replayed for figure preparation.']
    (r.out/'FINDINGS.md').write_text('\n'.join(lines)+'\n')
    r.validation['statistical_fallacy_scan_11_of_11']={
        'Simpson':'harvest/sigma/source conditions retained; only coverage condition averages within seed',
        'Ecological':'run-level effects; no inference from aggregate means to individual packets',
        'Selection/Berkson':'admission and completion selection explicit; conditional delay cohorts counted',
        'Collider':'no adjusted causal regression; completion-conditioned delays explicitly limited',
        'Base rates':'offered/admitted/completed denominators and rejection included',
        'Regression to mean':'fixed predeclared conditions; no extremal subgroup selected as the only evidence',
        'Survivorship':'unfinished/rejected/initial counts and missing means preserved',
        'Look elsewhere':'all conditions and unfavorable/equal differences retained; intervals unadjusted',
        'Forking paths':'no model/policy/grid tuning; plotting selections and complete support collection disclosed',
        'Causal claims':'controlled simulated channel-forecast perturbation only; no real-world causal claim',
        'Reverse causality':'future truth only used for saved post-run evaluation, not rebuilt online inputs'}


def copy_inputs(r):
    names={'status.json','status.tsv','preflight.json','COMPLETED','logs/21_completion_audit.log'}
    for p in r.source.rglob('*'):
        if p.is_file() and p.suffix in ('.json','.csv') and p.name not in ('per_slot.csv','partial_slots.csv','per_packet.csv','plans.csv','partial_windows.csv','partial.csv'):
            names.add(str(p.relative_to(r.source)))
    for name in names:
        target=r.out/'inputs'/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(r.source/name,target)


def table_notes(r):
    (r.out/'TABLE_NOTES.md').write_text('''# Table and measurement notes

`experiment_structure.csv` checks the saved execution matrices: 300 original,
300 normalized, 300 solar, 120 weight-sensitivity and 120 forecast-sensitivity
online runs, plus 90 full-episode relaxed references and 12 short solver checks.
Online episodes contain 1000 intervals, MPC horizon 10. Seed sets are
5000–5009 (original), 6000–6009 (normalized/supplementary), and 7000–7009 (solar).
Supplementary baseline cases repeat main/between-study scenarios; these are
not extra independent repetitions. Each table retains its study/condition/run
identifiers; packet IDs are not pooled across runs.

## Units and cohorts

- `queue` is mean beginning-of-slot backlog in packets.
- `energy` is total TX data-plus-control J per 1000-slot episode; means are across
  episodes. `throughput` is uniquely delivered payload bits/s: 256 times unique
  deliveries divided by episode duration. Synthetic intervals last 5 s; solar
  ARCO/UMass/NREL intervals last 60/60/3600 s. Compare physical delay/throughput
  within the same source. These are virtual times, not host wall-clock time.
- Initial waiting = first burst's data-start time minus admission time. ACK delay
  = first successful ACK-availability/departure time minus admission time. It
  includes transmission, ACK waiting and retries. Packets in a burst share its
  start timestamp; first-attempt timestamps survive retries. Boundary admissions
  become eligible in the following interval. For a 5 s boundary admission,
  first attempt at 6.6 s gives 1.6 s waiting, ACK at 8.6 s gives 3.6 s delay;
  retry ACK at 13.6 s gives 8.6 s delay without changing initial waiting.
- Primary delay cohorts exclude the 12 initial packets per run (bookkeeping
  admission at simulation time zero). Rejected arrivals were never admitted.
  Outstanding packets have no fabricated ACK times; never-attempted packets
  have no completed initial-wait sample. Missing observations remain missing.
- `delay_cohorts.csv` retains all 1140 run-level cohort records and outstanding
  age summaries. `delay_service_summary.csv` puts admissions, attempts,
  completions, unfinished and rejection counts alongside run-averaged delay,
  rejection, throughput, energy and queue. Count totals sum run records; they
  are not a count of independent experimental repetitions or distinct packets
  across repeated matched policies. `median_*_run_mean` averages per-run medians;
  it is not the median of a pooled packet population.
- Rejection = rejected/offered arrivals. Unfinished admitted fraction =
  (new admissions − new ACK completions)/new admissions. Offered completion =
  new ACK completions/offered arrivals. `_pct` columns use 0–100 scaling;
  raw `_fraction`/`drop_ratio` columns use 0–1. Plotted-data `scale` records any
  conversion; paired percentage differences are percentage points. Initial
  outstanding packets are included in `outstanding_packets` but excluded from
  `newly_outstanding_packets` and primary unfinished fractions.

## Statistics and scores

All primary means/contrasts use run-level observations. Within each synthetic
condition, matched seed differences use unadjusted 95% Student t intervals:
mean(d) ± t(0.975,n−1) sd(d)/sqrt(n). `n_valid_pairs` counts finite paired run
observations for that metric; missing delay observations are not filled with
zero. Absolute mean intervals use seed-level observations. Coverage averages
all six normalized conditions within each seed before its ten-seed interval.
Solar intervals are descriptive paired-scenario intervals with shared-source
dependence, including nine overlapping NREL pairs; they are not independent
solar-record confidence intervals. No slots or packets are used as independent
replicates. No multiplicity correction or population normality guarantee is made.

`performance_paired.csv` retains all conditions and comparisons against greedy,
nominal and (where present) fixed-margin. Supplementary greedy comparisons reuse
the exactly matched normalized-main greedy reference and are explicitly labeled;
greedy was not executed again in those supplementary matrices.
`energy_weight_comparisons.csv` and `forecast_noise_baseline_comparisons.csv` pair each setting
with its own policy's predeclared baseline. Estimates/intervals/counts for every
figure are independently recomputed from the saved rows, not from rounded labels.

`common_score` aliases saved `common_reference_cost` in supplementary tables
and saved `realized_cost` in the main study (whose weights are fixed).
Common-reference score = 1000 × mean backlog + 35 × rejected arrivals +
0.15 × total TX energy + 6 × terminal backlog. It is a weighted score, not J.
`configured_and_common_scores.csv` keeps configured objectives separate: their
energy coefficients differ, so configured objectives at different weights are
not compared as the same scoring function. Trade-off coordinates are empirical,
not a certified Pareto frontier. Lower completed-only delay requires the cohort,
rejection and throughput context before making an overall-service comparison.

Forecast tables distinguish `base`, `perturbed` (pre-margin), and `planned`
(margin-adjusted) errors. Only perturbed pre-margin RMSE is drawn in the revised
forecast-error panels, in effective SNR per watt (1/W). Each run's MAE/RMSE is
scored against saved post-run truth at the labeled decision lead, then averaged
over seeds; it is not pooled across different forecast quantities. Noise changes
future channel forecasts only. Zero added noise still has process error; current
probe reports remain ideal. Arrival/harvest errors were not independently varied.
The dimensionless amplitude a multiplies future forecasts by exp(a z − a²/2).
The independent standard-normal stream is keyed by scenario seed, decision
origin and lead; policies and amplitude levels share those underlying draws.

## Solver and offline evidence

`solver_runtime_by_run.csv` and `solver_runtime_summary.csv` distinguish host
solver runtime per interval from runtime per actual optimization call. Inactive
intervals/baselines have no optimization call. Runtime/status metadata were
streamed now from saved slot tables; this was not a packet/battery audit replay.
Maximum residuals are the saved per-run plan-verification maxima. Budget fields
retain the 1 s solver/scheduling budget checks. `solver_checks.csv` retains the
12 separate short solver statuses/residuals/runtimes.

`offline_reference_differences.csv` describes online weighted score minus the
continuous perfect-input expected-goodput reference. It is not a pathwise lower
bound on stochastic realized costs, and it has no identifiable packet-delay
samples or optimal packet-delay interpretation.

## Reproducibility and omissions

`inputs/` copies only saved small tables/settings/audit reports/status records
and a newly extracted runtime capsule. Large raw slot/packet/offline-plan ledgers,
solar downloads, historical runs and the environment are omitted. Previously
passed raw-ledger/source audits are retained as evidence, not claimed as replayed.
No experiments/model/policy parameters were changed. Adaptive forecast margins
remain included; adaptive penalty updates remain excluded.
''')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--input',type=Path,default=DEFAULT_INPUT)
    parser.add_argument('--out',type=Path,default=Path('results/report_figures_20261120'))
    parser.add_argument('--zip',type=Path,default=Path('EE541_report_figures_review.zip'));args=parser.parse_args()
    source=args.input.resolve();out=fresh(args.out).resolve();archive=fresh(args.zip).resolve()
    assert source.is_dir() and not out.is_relative_to(source),'output must be outside read-only production input'
    out.mkdir(parents=True,exist_ok=False);print('OUTPUT_DIRECTORY='+str(out),flush=True)
    before=snapshot(source);(out/'production_hashes_before.json').write_text(json.dumps(before,indent=2)+'\n')
    r=Report(source,out);r.load();copy_inputs(r);runtime_table(r);style();report_tables(r)
    synthetic_support(r);solar_plots(r);solar_plots(r,paired_only=True);solar_plots(r,main=True);coverage_plot(r);coverage_plot(r,main=True)
    for folder in ('supplementary/delay_energy','supplementary/forecast_sensitivity'):
        delay_plot(r,folder);forecast_error_plot(r,folder)
    normalized_comparisons(r);delay_plot(r,'supplementary/delay_energy',main=True);noise_outcomes(r,paired=True);noise_outcomes(r,paired=False)
    assert len(r.figures)==26 and sum(f['role']=='supporting' for f in r.figures)==20 and sum(f['role']=='main' for f in r.figures)==5
    validate_points(r);findings(r);table_notes(r)
    r.write('FIGURE_INDEX.csv',pd.DataFrame(r.figures))
    (out/'CAPTIONS.md').write_text('# Suggested figure captions\n\n'+'\n\n'.join(f"## {f['figure_id']}\n\n{f['caption']}\n\nPlotted data: `{f['plotted_data']}`." for f in r.figures)+'\n')
    after=snapshot(source);assert before==after,'production input hashes changed'
    (out/'production_hashes_after.json').write_text(json.dumps(after,indent=2)+'\n')
    r.validation.update(passed=True,verified_utc=datetime.now(timezone.utc).isoformat(),input_directory=str(source),
        production_files=len(before),production_bytes=sum(x['bytes'] for x in before.values()),production_file_hashes_unchanged=True,
        counts=dict(original=300,normalized=300,solar=300,delay_energy=120,forecast_sensitivity=120,offline=90,solver=12),
        revised_supporting_figures=20,recommended_main_figures=5,additional_outcome_figures=1,
        experiments_rerun=False,model_or_optimizer_modified=False,
        limitations=['unadjusted small-n t intervals; no multiplicity correction/normality guarantee','dependent solar windows, nine NREL overlapping pairs',
                     'completed-only delay cohorts differ; missing completions not imputed','no raw-ledger audit replay in this analysis'])
    (out/'VALIDATION.json').write_text(json.dumps(r.validation,indent=2)+'\n')
    shutil.copyfile(__file__,out/'prepare_report_figures.py')
    requirements=Path('requirements.txt')
    if requirements.exists():shutil.copyfile(requirements,out/'requirements.txt')
    (out/'INDEX.md').write_text('''# EE541 report figure/evidence package

Use the five `main/` figures for a 5–7-page report. `supporting/` contains revised
copies of all 20 original plots; `supporting_extra/` adds absolute noise-outcome
responses. Every figure has vector PDF, 300-dpi PNG and a plotted-data CSV.
`FIGURE_INDEX.csv` maps source tables, analysis functions, images and captions.

Read `CAPTIONS.md`, `TABLE_NOTES.md`, `FINDINGS.md` and `VALIDATION.json` before interpreting results.
`tables/` retains paired comparisons, cohorts/throughput/rejection, common-score
weight comparisons, forecast errors, runtime/solver evidence and offline gaps.
`inputs/` contains small saved input tables/configurations/audit reports and a
runtime-metadata capsule; no raw slot/packet/offline-plan ledgers or solar downloads.
The stored audits were completed previously, not replayed by this script.
Production hashes were checked before/after the read-only analysis.

The script imports no simulator/optimizer. For a fresh replot from the compact
capsule: `python prepare_report_figures.py --input inputs --out replotted --zip replotted.zip`.
Runtime metadata is reused in capsule mode; hashes then refer to the capsule,
not an independent recheck of the omitted production ledgers. No experiments
are rerun. Adaptive penalty updates remain out of scope. This is figure/evidence
material, not the final project report.
''')
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for p in sorted(out.rglob('*')):
            if p.is_file():z.write(p,p.relative_to(out).as_posix())
    with zipfile.ZipFile(archive) as z:assert z.testzip() is None
    print(json.dumps(dict(output=str(out),zip=str(archive),bytes=archive.stat().st_size,
        mib=archive.stat().st_size/1024**2,figures=26,validation='passed'),indent=2),flush=True)


if __name__=='__main__':main()
