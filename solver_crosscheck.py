"""Compare independent solvers on identical proposal instances; save failures."""
import argparse,json,time
from dataclasses import replace
from pathlib import Path
import numpy as np,pandas as pd
from src.scheduling import Config,solve_cvxpy,verify_plan
from src.radio import simulation_settings
from src.experiment import make_trace
from final_evaluation import DEFAULT_ROOT

def run(out):
    out.mkdir(parents=True,exist_ok=True);rows=[];cfg=replace(Config(),horizon=10)
    cases=[(91,12,7,1.2),(92,25,3,.4),(93,0,0,0.),(94,31,1,.3),(95,15,12,2.),(96,10,4,.8)]
    for case,(seed,b,e,harvest) in enumerate(cases):
        tr=make_trace(10,seed=seed,harvest_mean=harvest);g=tr['gain'];a=tr['arrival'];h=tr['harvest']
        for solver in ('CLARABEL','SCS'):
            start=time.perf_counter()
            try:
                sol=solve_cvxpy(b,e,g,a,h,cfg,solver_preference=solver)
                row={'case':case,'seed':seed,'initial_queue':b,'initial_energy':e,'harvest_mean':harvest,'solver':solver,'status':sol['status'],'objective':sol['objective'],
                    'primal_violation':max(verify_plan(sol,b,e,g,a,h,cfg).values()),'elapsed_s':time.perf_counter()-start,'error':''}
            except Exception as exc:
                row={'case':case,'seed':seed,'initial_queue':b,'initial_energy':e,'harvest_mean':harvest,'solver':solver,'status':'failed','objective':np.nan,'primal_violation':np.nan,'elapsed_s':time.perf_counter()-start,'error':str(exc)}
            rows.append(row)
    raw=pd.DataFrame(rows);raw.to_csv(out/'solver_results.csv',index=False)
    a=raw[raw.solver=='CLARABEL'].set_index('case');b=raw[raw.solver=='SCS'].set_index('case')
    both=a[['status','objective','primal_violation']].add_suffix('_clarabel').join(b[['status','objective','primal_violation']].add_suffix('_scs'))
    both['absolute_objective_difference']=(both.objective_clarabel-both.objective_scs).abs()
    both['relative_objective_difference']=both.absolute_objective_difference/np.maximum(1.,both.objective_clarabel.abs())
    both.to_csv(out/'solver_comparison.csv');(out/'settings.json').write_text(json.dumps(simulation_settings(cfg)|{'cases':6,'case_inputs':[dict(seed=seed,initial_queue=b,initial_energy=e,harvest_mean=h) for seed,b,e,h in cases],'horizon':10,'objective':'submitted weighted objective','note':'primal feasibility and cross-solver agreement; neither alone certifies optimality'},indent=2))
    print(both.to_string());return raw

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--out',default=DEFAULT_ROOT+'/solver');args=ap.parse_args();run(Path(args.out))
