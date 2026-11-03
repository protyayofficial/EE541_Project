"""SCS numerical accuracy/convergence diagnostic against CLARABEL reference.

These plots describe SOLVER behavior on a fixed convex instance, not an online
controller's regret or convergence theorem. Requires CVXPY and SCS installed.
"""
import argparse
from pathlib import Path
import time
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from src.scheduling import Config,verify_plan
from src.experiment import make_trace

def solve_instance(cp, solver, eps, b0, e0, g, l, H, cfg):
    n=len(g)
    p=cp.Variable(n,nonneg=True);d=cp.Variable(n,nonneg=True)
    b=cp.Variable(n+1);E=cp.Variable(n+1)
    o=cp.Variable(n,nonneg=True);w=cp.Variable(n,nonneg=True)
    constraints=[b[0]==b0,E[0]==e0,b>=0,b<=cfg.buffer_max,
       E>=0,E<=cfg.energy_max,p<=cfg.power_max,d<=cfg.data_max,
       d<=b[:-1],o<=l,p*cfg.tau<=E[:-1],
       b[1:]==b[:-1]-d+l-o,E[1:]==E[:-1]-p*cfg.tau+H-w,
       d<=cfg.rate_scale*cp.log1p(cp.multiply(g,p))/np.log(2)]
    objective=cp.Minimize(cp.sum(b[:-1])+cfg.drop_weight*cp.sum(o)
       +cfg.energy_weight*cfg.tau*cp.sum(p)+cfg.terminal_weight*b[-1])
    prob=cp.Problem(objective,constraints)
    assert prob.is_dcp()
    kwargs={'verbose':False}
    if solver=='SCS':kwargs.update(eps=eps,max_iters=30000)
    tic=time.perf_counter();prob.solve(solver=solver,**kwargs)
    elapsed=time.perf_counter()-tic
    if prob.status not in ('optimal','optimal_inaccurate'):
        raise RuntimeError(f'{solver} eps {eps}: {prob.status}')
    sol={k:np.asarray(x.value) for k,x in [('p',p),('d',d),('b',b),('E',E),('o',o),('w',w)]}
    return dict(solver=solver,tolerance=eps,objective=float(prob.value),
        max_violation=max(verify_plan(sol,b0,e0,g,l,H,cfg).values()),
        elapsed_sec=elapsed,iterations=prob.solver_stats.num_iters,
        status=prob.status)

def main():
    import cvxpy as cp
    parser=argparse.ArgumentParser()
    parser.add_argument('--horizon',type=int,default=12)
    parser.add_argument('--out',default='results/research')
    args=parser.parse_args()
    if 'SCS' not in cp.installed_solvers():raise RuntimeError('SCS is not installed: pip install scs')
    cfg=Config();trace=make_trace(args.horizon,seed=119)
    g=trace['gain'];l=trace['arrival'];H=trace['harvest']
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    rows=[]
    if 'CLARABEL' in cp.installed_solvers():
        try:
            reference=solve_instance(cp,'CLARABEL',np.nan,12.,7.,g,l,H,cfg)
            rows.append(reference)
            ref_obj=reference['objective'] if reference['status']=='optimal' and reference['max_violation']<=1e-4 else None
            if ref_obj is None: print('CLARABEL reference not numerically certified; objective-gap plot will be omitted')
        except Exception as exc:
            print(f'CLARABEL reference unavailable: {exc}')
            ref_obj=None
    else:ref_obj=None
    for tol in [1e-2,3e-3,1e-3,3e-4,1e-4,1e-5]:
        try:
            rows.append(solve_instance(cp,'SCS',tol,12.,7.,g,l,H,cfg))
        except Exception as exc:
            print(f'SCS at tolerance {tol:g} failed: {exc}')
            rows.append(dict(solver='SCS',tolerance=tol,objective=np.nan,
                max_violation=np.nan,elapsed_sec=np.nan,iterations=np.nan,status=str(exc)))
    df=pd.DataFrame(rows)
    df['objective_gap_to_clarabel']=np.nan if ref_obj is None else abs(df.objective-ref_obj)
    df.to_csv(out/'solver_accuracy.csv',index=False)
    scs=df[df.solver=='SCS']
    for metric,ylabel in [('max_violation','Maximum constraint violation'),
                          ('objective_gap_to_clarabel','Absolute objective gap vs CLARABEL'),
                          ('iterations','SCS iterations')]:
        if metric=='objective_gap_to_clarabel' and ref_obj is None:continue
        fig,ax=plt.subplots(figsize=(7,4.2))
        ax.plot(scs.tolerance,np.maximum(scs[metric],1e-12),marker='o')
        ax.set_xscale('log');ax.invert_xaxis()
        ax.set_yscale('log');ax.set(xlabel='Requested SCS tolerance (smaller is tighter)',ylabel=ylabel)
        ax.grid(alpha=.25);fig.tight_layout();fig.savefig(out/f'solver_{metric}.png',dpi=200);plt.close(fig)
    print(df.to_string(index=False))

if __name__=='__main__':main()
