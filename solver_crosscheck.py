"""Compare independent solvers on identical proposal instances; save failures."""
import argparse,json,time
from dataclasses import replace
from pathlib import Path
import numpy as np,pandas as pd
from src.scheduling import Config,solve_cvxpy,verify_plan
from src.experiment import make_trace

def run(out):
    out.mkdir(parents=True,exist_ok=True);rows=[];cfg=replace(Config(),horizon=10)
    for case,(seed,b,e,arrival,harvest) in enumerate([(91,12,7,2.,1.2),(92,25,3,3.,.4),(93,0,0,2.,0.),(94,31,1,4.,.3),(95,15,12,3.,2.),(96,10,4,2.5,.8)]):
        tr=make_trace(10,seed=seed,arrival_mean=arrival,harvest_mean=harvest);g=tr['gain'];a=np.minimum(tr['arrival'],10);h=tr['harvest']
        for solver in ('CLARABEL','SCS'):
            start=time.perf_counter()
            try:
                sol=solve_cvxpy(b,e,g,a,h,cfg,solver_preference=solver)
                row={'case':case,'solver':solver,'status':sol['status'],'objective':sol['objective'],
                    'primal_violation':max(verify_plan(sol,b,e,g,a,h,cfg).values()),'elapsed_s':time.perf_counter()-start,'error':''}
            except Exception as exc:
                row={'case':case,'solver':solver,'status':'failed','objective':np.nan,'primal_violation':np.nan,'elapsed_s':time.perf_counter()-start,'error':str(exc)}
            rows.append(row)
    raw=pd.DataFrame(rows);raw.to_csv(out/'solver_results.csv',index=False)
    a=raw[raw.solver=='CLARABEL'].set_index('case');b=raw[raw.solver=='SCS'].set_index('case')
    both=a[['status','objective','primal_violation']].add_suffix('_clarabel').join(b[['status','objective','primal_violation']].add_suffix('_scs'))
    both['absolute_objective_difference']=(both.objective_clarabel-both.objective_scs).abs()
    both['relative_objective_difference']=both.absolute_objective_difference/np.maximum(1.,both.objective_clarabel.abs())
    both.to_csv(out/'solver_comparison.csv');(out/'settings.json').write_text(json.dumps({'cases':6,'horizon':10,'objective':'submitted weighted objective','note':'primal feasibility and cross-solver agreement; neither alone certifies optimality'},indent=2))
    print(both.to_string());return raw

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--out',default='results/final_evaluation/solver');args=ap.parse_args();run(Path(args.out))
