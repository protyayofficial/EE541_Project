"""Online policies for the uncertainty-aware weighted convex MPC experiments.
All online methods use identical service/admission rules and observed inputs.
"""
import json
import time
import numpy as np
import pandas as pd
from src.scheduling import INITIAL_QUEUE,INITIAL_ENERGY,capacity,planner_action,solve_cvxpy,validate_packet_inputs
from src.forecasting import bound_arrivals,raw_forecasts
from src.radio import PacketRadio
from src.channel import CHANNEL_THRESHOLD,bound_gain,validate_trace_model
from src.packets import attach_packet_ledger
from src.forecast_noise import perturb_channel,NOISE_MODEL

METHODS=('greedy','fixed_fraction','nominal','fixed_margin','adaptive_channel','adaptive_arrival','adaptive_harvest','adaptive_all')

def margins(error_history,mode):
    if mode=='nominal':return np.zeros(3)
    if mode=='fixed_margin':return np.array([.38,1.,.25])
    # Signed channel-overprediction, arrival-underprediction, harvest-overprediction.
    # Prior fixed warm-up, then the last 50 raw one-step errors. Empirical, not guaranteed.
    samples=np.asarray(error_history,dtype=float).reshape(-1,3)
    result=np.array([max(0.,float(np.quantile(v[np.isfinite(v)][-50:],.8))) if np.isfinite(v).sum()>=12 else prior
                     for v,prior in zip(samples.T,(.38,1.,.25))])
    if mode=='adaptive_channel':result[1:]=0
    if mode=='adaptive_arrival':result[[0,2]]=0
    if mode=='adaptive_harvest':result[:2]=0
    return result

def apply_margins(g,a,h,m,mode):
    g=g.copy();a=a.copy();h=h.copy()
    g[1:]=bound_gain(g[1:]-(m[0] if mode!='nominal' else 0.))
    if mode!='nominal':
        a=a+m[1];h=np.maximum(0,h-m[2])
    return g,bound_arrivals(a),h

def run(trace,cfg,mode,margin_scale=1.0,*,forecast_perturbation=0.,forecast_scenario=None,log_forecasts=False):
    if mode not in (*METHODS, 'fixed', 'channel', 'adaptive_guard50', 'adaptive_guard75', 'nominal_forced', 'adaptive_forced', 'adaptive_arrival_forced', 'adaptive_harvest_forced'):
        raise ValueError(f'unknown method: {mode}')
    if not np.isfinite(margin_scale) or margin_scale < 0:
        raise ValueError('margin_scale must be finite and nonnegative')
    if not np.isfinite(forecast_perturbation) or forecast_perturbation<0:
        raise ValueError('forecast perturbation must be finite and nonnegative')
    record_forecasts=log_forecasts or forecast_perturbation!=0
    scenario=str(forecast_scenario if forecast_scenario is not None else f"seed:{trace.get('seed',0)}")
    validate_packet_inputs(trace['arrival'],INITIAL_QUEUE,cfg)
    validate_trace_model(trace,cfg)
    E=INITIAL_ENERGY;history={'gain':[],'gain_times':[],'arrival':[],'harvest':[]};errors=[];prev=None;rows=[]
    radio=PacketRadio(INITIAL_QUEUE,cfg,trace.get('seed',0),trace=trace)
    for t in range(len(trace['gain'])):
        arrival=int(trace['arrival'][t]);harvest=float(trace['harvest'][t]);horizon=min(cfg.horizon,len(trace['gain'])-t)
        b=len(radio.queue.ids)
        gain,available=radio.probe(E,t=t)
        decision_start=time.perf_counter()
        # Affordable probe/report stages still execute if later ACK cost blocks data.
        rawg,rawa,rawh=raw_forecasts(history,gain,horizon,t=t,model=cfg.channel_model)
        if record_forecasts:
            baseg=rawg.copy()
            forecast_time_s=radio.now_s
            rawg,noise_z,noise_multiplier=perturb_channel(rawg,forecast_perturbation,scenario,t)
        anchor=t if radio.controls['report_available'] else (history['gain_times'][-1] if history['gain_times'] else -1)
        forced_modes={'nominal_forced':'nominal','adaptive_forced':'adaptive_all',
                      'adaptive_arrival_forced':'adaptive_arrival','adaptive_harvest_forced':'adaptive_harvest'}
        prediction_mode=forced_modes.get(mode,mode)
        if mode in ('adaptive_guard50','adaptive_guard75'):
            m=margins(errors,'adaptive_harvest')
            threshold=.5 if mode=='adaptive_guard50' else .75
            if E >= threshold*cfg.energy_max:m*=0.
        else:
            m=margins(errors,prediction_mode) if mode not in ('greedy','fixed_fraction','fixed','channel') else np.zeros(3)
        if mode.startswith('adaptive_'):
            m=m*margin_scale
        g,a,h=apply_margins(rawg,rawa,rawh,m,prediction_mode)
        max_power=min(cfg.power_max,available/cfg.tau)
        max_attempts=min(b,cfg.data_max,float(capacity(max_power,gain,cfg))) if radio.exchange else 0.
        unavoidable=max(0.,b+a[0]-cfg.buffer_max-cfg.success_probability*max_attempts)
        drop_cap=min(float(a[0]),unavoidable+1e-6) if mode in forced_modes else None
        solver_runtime=0.;v=0.;status='heuristic';solver='none';planned_reject=0.;p=0.;d=0.
        if not radio.exchange:
            status='no_control_energy'
        elif mode=='greedy':
            p=max_power if b else 0.;d=min(b,cfg.data_max,float(capacity(p,gain,cfg)))
        elif mode in ('fixed','channel'):
            target=1.2 if mode=='fixed' else (2.4 if gain>=CHANNEL_THRESHOLD else .45)
            p=min(cfg.power_max,target,available/cfg.tau) if b else 0.
            d=min(b,cfg.data_max,float(capacity(p,gain,cfg)))
        elif mode=='fixed_fraction':
            p=min(cfg.power_max,(1.1/cfg.energy_max)*available/cfg.tau) if b else 0.;d=min(b,cfg.data_max,float(capacity(p,gain,cfg)))
        else:
            solver_start=time.perf_counter()
            sol=solve_cvxpy(b,E,g,a,h,cfg,first_slot_drop_cap=drop_cap)
            solver_runtime=time.perf_counter()-solver_start
            v=float(sol['max_violation']);status=sol['status'];solver=sol['solver'];planned_reject=float(sol['o'][0])
            d,p=planner_action(sol,b,available,gain,cfg)
        decision_runtime=time.perf_counter()-decision_start
        covered=(np.nan,np.nan,np.nan);errs=(np.nan,np.nan,np.nan)
        if prev is not None:
            pg,pa,ph,mg,ma,mh,origin,target,previous_anchor=prev
            assert target==t
            errs=(pg-gain if radio.controls['report_available'] else np.nan,arrival-pa,ph-harvest)
            covered=(float(gain>=bound_gain(pg-mg)-1e-12) if radio.controls['report_available'] else np.nan,
                     float(arrival<=bound_arrivals(pa+ma)+1e-12),float(harvest>=max(0,ph-mh)-1e-12))
        def update_history():
            nonlocal prev
            if prev is not None:errors.append(errs)
            prev=(rawg[1],rawa[1],rawh[1],*m,t,t+1,anchor) if horizon>1 else None
            if radio.controls['report_available']:
                history['gain'].append(gain);history['gain_times'].append(t)
            history['arrival'].append(arrival);history['harvest'].append(harvest)
        error_origin=prev[6] if prev is not None else np.nan
        error_anchor=prev[8] if prev is not None else np.nan
        action=radio.execute(d,p,E,arrival,harvest,fixed_power=mode in ('fixed','channel','fixed_fraction'),
                             on_update=update_history,solver_runtime_s=solver_runtime,
                             decision_runtime_s=decision_runtime)
        rows.append(dict(t=t,mode=mode,**action,
          planned_rejection=planned_reject,predicted_unavoidable_rejection=unavoidable,
          planned_excess_rejection=max(0.,planned_reject-unavoidable),solve_ms=solver_runtime*1000,
          plan_violation=v,solver_status=status,solver_name=solver,margin_gain=m[0],margin_arrival=m[1],margin_harvest=m[2],
          channel_forecast_anchor_t=anchor,forecast_origin_t=error_origin,forecast_target_t=t if np.isfinite(error_origin) else np.nan,
          forecast_channel_lead=t-error_anchor if np.isfinite(error_anchor) else np.nan,
          forecast_current_gain=rawg[0],forecast_next_gain=rawg[1] if horizon>1 else np.nan,
          raw_error_gain=errs[0],raw_error_arrival=errs[1],raw_error_harvest=errs[2],covered_gain=covered[0],covered_arrival=covered[1],covered_harvest=covered[2]))
        if record_forecasts:
            rows[-1].update(forecast_perturbation=float(forecast_perturbation),forecast_scenario=scenario,
                            forecast_noise_model=NOISE_MODEL,forecast_decision_origin_t=t,
                            forecast_issued_at_s=forecast_time_s)
            for name,values in dict(forecast_targets=t+np.arange(horizon),forecast_leads=np.arange(horizon),
                 base_channel_forecasts=baseg,perturbed_channel_forecasts=rawg,planned_channel_forecasts=g,
                 forecast_noise_z=noise_z,forecast_multipliers=noise_multiplier,
                 base_arrival_forecasts=rawa,planned_arrival_forecasts=a,
                 base_harvest_forecasts=rawh,planned_harvest_forecasts=h).items():
                rows[-1][name]=json.dumps(values.tolist())
        E=action['E_next']
    frame=attach_packet_ledger(pd.DataFrame(rows),radio)
    if record_forecasts:
        frame.attrs['packet_run'].update(forecast_perturbation=float(forecast_perturbation),
                                        forecast_scenario=scenario,forecast_noise_model=NOISE_MODEL)
    return frame
