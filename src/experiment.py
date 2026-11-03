"""Synthetic trace and causal receding-horizon policies."""
import time
import numpy as np
import pandas as pd
from .scheduling import Config, capacity, solve_lp, solve_cvxpy, verify_plan


def make_trace(n=160, seed=7, arrival_mean=2.5, harvest_mean=1.1, forecast_noise=.4):
    rng=np.random.default_rng(seed)
    gain=np.empty(n)
    z=0.0
    for i in range(n):
        z=.68*z + rng.normal(0,.43)
        gain[i]=np.exp(z)
    arrival=rng.poisson(arrival_mean,size=n).astype(float)
    harvest=rng.gamma(shape=2,scale=harvest_mean/2,size=n)
    # Controlled synthetic *forecast error model*: future real values are perturbed.
    # This is an experimental forecasting oracle, not a deployable predictor.
    # The current channel is overridden with its actual observation in run_policy.
    rngf=np.random.default_rng(seed+901)
    horizon=21
    fg=np.zeros((n,horizon)); fl=np.zeros_like(fg); fH=np.zeros_like(fg)
    for t in range(n):
        sl=np.minimum(np.arange(t,t+horizon),n-1)
        fg[t]=np.clip(gain[sl]*np.exp(rngf.normal(0,forecast_noise,horizon)),.03,9)
        fl[t]=np.maximum(0,arrival[sl] + rngf.normal(0,forecast_noise*2,horizon))
        fH[t]=np.maximum(0,harvest[sl] + rngf.normal(0,forecast_noise*.7,horizon))
    return dict(gain=gain,arrival=arrival,harvest=harvest,
                forecast_gain=fg,forecast_arrival=fl,forecast_harvest=fH)


def _margins(history, mode):
    """One-step *observed* over-prediction residuals; no future labels used."""
    if mode=='nominal':return 0.,0.,0.
    if mode=='robust':return .38,1.0,.25
    if mode in ('adaptive','adaptive_risk'):
        if len(history)<8:return .38,1.,.25
        a=np.array(history[-40:])
        # Calibrated on past residuals; not distribution-free under drift.
        return tuple(np.maximum(0,np.quantile(a,.8,axis=0)))
    raise ValueError(mode)


def run_policy(trace, mode, cfg=Config(), backend='lp', b0=12.,e0=7., allow_proactive=True):
    n=len(trace['gain']); b=float(b0); E=float(e0)
    records=[]; residual_history=[]; solve=solve_lp if backend=='lp' else solve_cvxpy
    for t in range(n):
        gain, arrival, harvest=[float(trace[k][t]) for k in ('gain','arrival','harvest')]
        p=0.; d_plan=0.; o_plan=0.; solution_time=0.; feas=0.; solver_status='heuristic'; solver_name='none'
        if mode in ('nominal','robust','adaptive','adaptive_risk'):
            m=min(cfg.horizon,n-t)
            ghat=trace['forecast_gain'][t,:m].copy()
            lhat=trace['forecast_arrival'][t,:m].copy()
            Hhat=trace['forecast_harvest'][t,:m].copy()
            mg,ml,mH=_margins(residual_history,mode)
            if mode == 'adaptive_risk':
                # Backlog-responsive calibration heuristic: reduce conservatism
                # when queue pressure increases; not a certified robust policy.
                factor=max(.30, 1.0-.70*b/cfg.buffer_max)
                mg,ml,mH=(factor*mg, factor*ml, factor*mH)
            if mode != 'nominal':
                ghat[1:]=np.maximum(.01, ghat[1:]-mg)
                lhat=np.maximum(0,lhat+ml)
                Hhat=np.maximum(0,Hhat-mH)
            # Current observed channel, and current slot arrival/harvest are unknown.
            ghat[0]=gain
            tic=time.perf_counter()
            sol=solve(b,E,ghat,lhat,Hhat,cfg)
            solution_time=time.perf_counter()-tic
            feas=max(verify_plan(sol,b,E,ghat,lhat,Hhat,cfg).values())
            solver_status=str(sol.get('status','unknown'))
            solver_name=str(sol.get('solver','lp'))
            p=float(np.clip(sol['p'][0],0,min(cfg.power_max,E/cfg.tau)))
            d_plan=float(sol['d'][0]);o_plan=float(sol['o'][0])
        elif mode=='greedy':
            p=min(cfg.power_max,E/cfg.tau)
            d_plan=min(cfg.data_max,b,capacity(p,gain,cfg))
        elif mode=='fixed':
            p=min(1.2,cfg.power_max,E/cfg.tau)
            d_plan=min(cfg.data_max,b,capacity(p,gain,cfg))
        elif mode=='channel':
            p=min(cfg.power_max,E/cfg.tau,2.4 if gain>1.1 else .45)
            d_plan=min(cfg.data_max,b,capacity(p,gain,cfg))
        else:raise ValueError(mode)
        # Physical execution, protects against solver tolerances/forecast mismatch.
        d=max(0,min(d_plan,b,cfg.data_max,float(capacity(p,gain,cfg))))
        # o_plan is a planned rejection of current arrivals, which may differ
        # from forecast arrivals: apply at most actual arrivals.
        proactive=min(max(0,o_plan),arrival) if allow_proactive else 0.0
        drop=max(proactive, b-d+arrival-cfg.buffer_max,0)
        drop=min(drop,arrival)
        b_next=b-d+arrival-drop
        energy_pre=E-cfg.tau*p+harvest
        spill=max(0,energy_pre-cfg.energy_max)
        E_next=energy_pre-spill
        records.append(dict(t=t,mode=mode,gain=gain,arrivals=arrival,harvest=harvest,
                            b=b,E=E,p=p,d=d,drop=drop,proactive=proactive,
                            spill=spill,throughput_bps=d*cfg.packet_bits/cfg.slot_seconds,
                            solve_s=solution_time,plan_feas=feas,solver_status=solver_status,solver_name=solver_name))
        # At time t, we can now compare the one-step forecast made at t-1
        # to t's realization. No future observations leak into margin updates.
        if t>0:
            residual_history.append((
                max(0,float(trace['forecast_gain'][t-1,1])-gain),
                max(0,arrival-float(trace['forecast_arrival'][t-1,1])),
                max(0,float(trace['forecast_harvest'][t-1,1])-harvest)))
        b,E=b_next,E_next
        if b < -1e-7 or b>cfg.buffer_max+1e-7 or E< -1e-7 or E>cfg.energy_max+1e-7:
            raise AssertionError('Physical state violated capacity constraints')
    return pd.DataFrame.from_records(records)


def summarize(df,cfg=Config()):
    out=[]
    for mode,group in df.groupby('mode',sort=False):
        arrivals=group.arrivals.sum()
        out.append(dict(mode=mode,average_queue=group.b.mean(),
                        rejection_ratio=group['drop'].sum()/arrivals if arrivals else 0,
                        throughput_bps=group.throughput_bps.mean(),
                        energy_J=(group.p*cfg.tau).sum(),
                        mean_solve_ms=group.solve_s.mean()*1000,
                        max_planned_violation=group.plan_feas.max(),
                        inaccurate_fraction=float((group.solver_status=='optimal_inaccurate').mean()),
                        solver_failure_count=0))
    return pd.DataFrame(out)
