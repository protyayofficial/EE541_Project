"""Independent reconstruction of the fixed supplementary protocols and outputs."""
import argparse
from dataclasses import asdict,replace
import hashlib
import json
import math
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import t as student_t
from final_evaluation import make_evaluation_trace
from src.auditing import audit_metrics,audit_packets,audit_packet_outputs,saved_config
from src.scheduling import Config


def independent_normal(scenario,origin,lead):
    encoded=json.dumps(['channel-forecast-lognormal-v1',scenario,int(origin),int(lead)],separators=(',',':')).encode()
    digest=hashlib.blake2b(encoded,digest_size=16).digest()
    first=((int.from_bytes(digest[:8],'big')>>11)+.5)/9007199254740992
    second=((int.from_bytes(digest[8:],'big')>>11)+.5)/9007199254740992
    return math.sqrt(-2*math.log(first))*math.cos(2*math.pi*second)


def audit_forecasts(frame,cfg,amplitude,scenario):
    """Reconstruct causal predictions/margins from reports, not hidden channels."""
    rho=cfg.channel_rho;v=cfg.channel_sigma**2/(1-rho*rho);center=v/2
    observation=None;observation_t=-1;arrivals=[];harvests=[];errors=[];previous=None
    multipliers={};evaluated={}
    for r in frame.sort_values('t').itertuples(index=False):
        if r.probe_available:observation=r.reported_gain;observation_t=r.t
        n=min(cfg.horizon,len(frame)-r.t);base=[]
        for lead in range(n):
            gap=r.t+lead-observation_t
            if observation is None:value=1.
            elif gap==0:value=observation
            else:value=math.exp(rho**gap*(math.log(observation)+center)+.5*v*(1-rho**(2*gap))-center)
            base.append(value)
        base=np.asarray(base);z=np.array([0.]+[independent_normal(scenario,r.t,k) for k in range(1,n)])
        mult=np.ones(n)
        if amplitude:mult[1:]=np.exp(amplitude*z[1:]-.5*amplitude**2)
        perturbed=base*mult
        if n>1:multipliers[(r.t,1)]=mult[1]
        a=float(np.clip((40.+sum(arrivals))/(8+len(arrivals)),0,10))
        h=float(np.mean(harvests[-12:])) if len(harvests)>=3 else (8.8+sum(harvests))/(8+len(harvests))
        margin=np.zeros(3)
        if r.mode=='adaptive_all':
            margin=[]
            for k,prior in enumerate((.38,1.,.25)):
                samples=[e[k] for e in errors if np.isfinite(e[k])]
                margin.append(max(0.,float(np.quantile(samples[-50:],.8))) if len(samples)>=12 else prior)
            margin=np.asarray(margin)
        planned=perturbed.copy();planned[1:]=np.maximum(1e-9,planned[1:]-margin[0])
        expected=dict(forecast_targets=r.t+np.arange(n),forecast_leads=np.arange(n),
            base_channel_forecasts=base,perturbed_channel_forecasts=perturbed,planned_channel_forecasts=planned,
            forecast_noise_z=z,forecast_multipliers=mult,base_arrival_forecasts=np.full(n,a),
            planned_arrival_forecasts=np.full(n,np.clip(a+margin[1],0,10)),base_harvest_forecasts=np.full(n,h),
            planned_harvest_forecasts=np.full(n,max(0,h-margin[2])))
        assert r.forecast_noise_model=='channel-forecast-lognormal-v1'
        assert r.forecast_perturbation==amplitude and r.forecast_scenario==scenario
        assert r.forecast_decision_origin_t==r.t
        assert r.forecast_issued_at_s==r.channel_report_end_s==r.decision_start_s
        assert r.channel_forecast_anchor_t==observation_t
        np.testing.assert_allclose([r.margin_gain,r.margin_arrival,r.margin_harvest],margin,rtol=1e-12,atol=1e-12)
        for name,values in expected.items():
            np.testing.assert_allclose(json.loads(getattr(r,name)),values,rtol=1e-12,atol=1e-12,err_msg=f'{r.t}: {name}')
        if r.probe_available:assert json.loads(r.perturbed_channel_forecasts)[0]==r.reported_gain
        if previous is not None:
            pg,pa,ph,pm=previous
            current=(pg-r.reported_gain if r.probe_available else np.nan,r.arrivals-pa,ph-r.harvest)
            np.testing.assert_allclose([r.raw_error_gain,r.raw_error_arrival,r.raw_error_harvest],current,rtol=1e-12,atol=1e-12,equal_nan=True)
            covered=[float(r.reported_gain>=max(1e-9,pg-pm[0])-1e-12) if r.probe_available else np.nan,
                     float(r.arrivals<=np.clip(pa+pm[1],0,10)+1e-12),float(r.harvest>=max(0,ph-pm[2])-1e-12)]
            np.testing.assert_allclose([r.covered_gain,r.covered_arrival,r.covered_harvest],covered,equal_nan=True)
            errors.append(current)
        previous=(perturbed[1],a,h,margin) if n>1 else None
        arrivals.append(r.arrivals);harvests.append(r.harvest)
        for name,values in (('base',base),('perturbed',perturbed),('planned',planned)):
            for lead in range(1,n):evaluated.setdefault((name,lead),[]).append((r.t+lead,values[lead]))
    # Actual future gains are consulted only here, after all causal reconstruction.
    truth=frame.sort_values('t').actual_gain.to_numpy();rows=[]
    for (kind,lead),predictions in evaluated.items():
        error=np.asarray([value-truth[target] for target,value in predictions])
        rows.append(dict(forecast_kind=kind,decision_lead=lead,samples=len(error),mae=np.abs(error).mean(),
                         rmse=np.sqrt(np.mean(error**2)),evaluation='post_run_true_gain_all_targets'))
    return multipliers,pd.DataFrame(rows)


def audit_derived(out,raw,forecast_rows):
    summary=pd.read_csv(out/'summary.csv',header=[0,1],index_col=[0,1,2])
    keys=['harvest_mean','study_value','mode']
    numeric=[c for c in raw.select_dtypes(include='number') if c not in ('seed',*keys)]
    expected_summary=raw.groupby(keys)[numeric].agg(['mean','std','count'])
    pd.testing.assert_frame_equal(summary,expected_summary,check_dtype=False,check_names=False,rtol=1e-10,atol=1e-9)
    fs=pd.read_csv(out/'forecast_summary.csv',header=[0,1],index_col=list(range(5)))
    want=forecast_rows.groupby(keys+['forecast_kind','decision_lead'])[['mae','rmse']].agg(['mean','std','count'])
    pd.testing.assert_frame_equal(fs,want,check_dtype=False,check_names=False,rtol=1e-10,atol=1e-9)
    metrics=['queue','drop_ratio','throughput','energy','terminal_queue','common_reference_cost','configured_objective_cost',
        'newly_completed_fraction','newly_unfinished_fraction','newly_admitted_packets','newly_acknowledged_packets',
        'outstanding_packets','future_channel_mae_lead1','future_channel_rmse_lead1','mean_initial_wait_s',
        'median_initial_wait_s','mean_ack_completion_delay_s','median_ack_completion_delay_s']
    baseline=.15 if raw.study.iloc[0]=='delay_energy' else 0.
    for name,by_policy in (('paired_vs_nominal.csv',True),('paired_vs_baseline.csv',False)):
        actual=pd.read_csv(out/name)
        if by_policy:
            count=raw.groupby(['harvest_mean','study_value']).ngroups*len(metrics)
        else:count=sum(g.study_value.nunique()-(baseline in set(g.study_value)) for _,g in raw.groupby(['harvest_mean','mode']))*(len(metrics)-1)
        assert len(actual)==count
        assert not actual.drop(columns=['delta','ci_low','ci_high','n','n_valid_pairs']).duplicated().any()
        for r in actual.itertuples(index=False):
            assert r.metric in metrics and (by_policy or r.metric!='configured_objective_cost')
            g=raw[raw.harvest_mean==r.harvest_mean]
            if by_policy:
                assert r.method=='adaptive_all'
                g=g[g.study_value==r.study_value];base=g[g['mode']=='nominal'];candidate=g[g['mode']=='adaptive_all']
            else:
                assert r.baseline_value==baseline
                g=g[g['mode']==r.mode];base=g[g.study_value==baseline];candidate=g[g.study_value==r.study_value]
            values=(candidate.set_index('seed')[r.metric]-base.set_index('seed')[r.metric]).dropna()
            n=len(values);mean=values.mean() if n else np.nan
            half=student_t.ppf(.975,n-1)*values.std(ddof=1)/np.sqrt(n) if n>=2 else np.nan
            assert r.n==r.n_valid_pairs==n
            np.testing.assert_allclose([r.delta,r.ci_low,r.ci_high],[mean,mean-half,mean+half],equal_nan=True,rtol=1e-9,atol=1e-8)


def audit(directory):
    out=Path(directory);s=json.loads((out/'settings.json').read_text());cfg=saved_config(s)
    assert s['supplementary_version']=='supplementary-v1'
    assert s['forecast_noise']['version']=='channel-forecast-lognormal-v1'
    assert (cfg.channel_rho,cfg.channel_sigma,cfg.channel_mean_normalize)==(.68,.45,True)
    assert asdict(cfg)==asdict(replace(Config(),horizon=s['horizon']))
    study=s['study'];values={'delay_energy':[.15,15.,150.],'forecast_sensitivity':[0.,.25,.5]}[study]
    assert s['study_values']==values and s['modes']==['nominal','adaptive_all']
    assert s['seed_ids']==list(range(6000,6000+s['seeds'])) and 1<=s['seeds']<=10
    assert s['common_reference_weights']==dict(backlog=1.,drop=35.,energy=.15,terminal=6.)
    expected=[dict(study=study,harvest_mean=h,seed=seed,mode=mode,study_value=v,
                   energy_weight=v if study=='delay_energy' else .15,forecast_perturbation=v if study=='forecast_sensitivity' else 0.)
              for h in (.6,1.2) for seed in s['seed_ids'] for mode in ('nominal','adaptive_all') for v in values]
    if s['benchmark_case']:expected=[r for r in expected if r['harvest_mean']==.6 and r['seed']==6000 and r['mode']=='nominal' and r['study_value']==values[1]]
    matrix=pd.read_csv(out/'run_matrix.csv');raw=pd.read_csv(out/'per_seed.csv');slots=pd.read_csv(out/'per_slot.csv')
    keys=list(expected[0]);sort=['harvest_mean','seed','mode','study_value']
    want=pd.DataFrame(expected).sort_values(sort).reset_index(drop=True)
    for table in (matrix,raw):
        pd.testing.assert_frame_equal(table[keys].sort_values(sort).reset_index(drop=True),want,check_dtype=False)
    assert s['planned_policy_runs']==len(raw) and raw.run_id.nunique()==len(raw)
    recorded_forecasts=pd.read_csv(out/'forecast_errors.csv');all_forecasts=[]
    for row in raw.itertuples(index=False):
        frame=slots[slots.run_id==row.run_id].sort_values('t');assert len(frame)==s['slots']
        assert np.isfinite(frame.plan_violation).all() and (frame.plan_violation<=1e-4).all()
        config=replace(cfg,energy_weight=row.energy_weight)
        assert s['run_configs'][str(row.study_value)]==asdict(config)
        assert row.config_id==hashlib.sha256(json.dumps(asdict(config),sort_keys=True).encode()).hexdigest()
        for key in keys:assert (frame[key]==getattr(row,key)).all(),key
        trace=make_evaluation_trace(s['slots'],row.seed,row.harvest_mean,sigma=.45,mean_normalize=True,rho=.68)
        for name,column in (('gain','gain'),('arrival','arrivals'),('harvest','harvest')):
            np.testing.assert_allclose(frame[column],trace[name],rtol=1e-13,atol=1e-13)
        scenario=f'normalized:harvest={float(row.harvest_mean):g}:seed={int(row.seed)}'
        multipliers,errors=audit_forecasts(frame,config,row.forecast_perturbation,scenario)
        audit_packets(frame,config,expected_seed=row.seed,initial_state=s['initial_state'],channel_forecast_multipliers=multipliers)
        audit_metrics(frame,pd.Series(row._asdict()),config)
        common=frame.b.sum()+35*frame['drop'].sum()+.15*frame.energy.sum()+6*frame.b_next.iloc[-1]
        np.testing.assert_allclose(row.common_reference_cost,common)
        np.testing.assert_allclose(row.configured_objective_cost,row.realized_cost)
        admitted=row.newly_admitted_packets;completed=row.newly_acknowledged_packets
        np.testing.assert_allclose([row.newly_completed_fraction,row.newly_unfinished_fraction],
            [completed/admitted,(admitted-completed)/admitted] if admitted else [np.nan,np.nan],equal_nan=True)
        first=errors[(errors.forecast_kind=='perturbed')&(errors.decision_lead==1)].iloc[0]
        np.testing.assert_allclose([row.future_channel_mae_lead1,row.future_channel_rmse_lead1,row.future_channel_samples_lead1],
                                  [first.mae,first.rmse,first.samples],rtol=1e-12)
        error_meta={key:getattr(row,key) for key in keys}|dict(run_id=row.run_id)
        all_forecasts.append(errors.assign(**error_meta))
    expected_errors=pd.concat(all_forecasts,ignore_index=True)
    error_keys=['run_id','forecast_kind','decision_lead']
    pd.testing.assert_frame_equal(recorded_forecasts.sort_values(error_keys).reset_index(drop=True),
        expected_errors[recorded_forecasts.columns].sort_values(error_keys).reset_index(drop=True),check_dtype=False,rtol=1e-11,atol=1e-11)
    audit_packet_outputs(out,slots,raw);audit_derived(out,raw,expected_errors)
    result=dict(passed=True,study=study,policy_runs=len(raw),slots_per_run=s['slots'],
        checks='matrix, fixed config/weights, full trace reconstruction, causal forecast vectors, keyed noise, margins and errors, physical/packet/delay accounting, both costs, run summaries and valid paired counts',
        scope='execution and logged prediction checks; not an optimality or uncertainty-coverage guarantee; no independent packet repetitions')
    (out/'audit.json').write_text(json.dumps(result,indent=2)+'\n');return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('directory')
    print(json.dumps(audit(parser.parse_args().directory),indent=2))
