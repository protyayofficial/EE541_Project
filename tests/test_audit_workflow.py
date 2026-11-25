"""Audit regressions and small CLI workflows using explicitly artificial data."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from final_evaluation import evaluate,make_evaluation_trace
from scheduling_policies import margins,run
from src.auditing import audit_packets,audit_metrics,trajectory_config
from src.experiment import _margins,run_policy,summarize
from src.radio import simulation_settings
from src.scheduling import Config,execute_packets,planner_action,solve_lp,solve_cvxpy,verify_plan


class AuditRegressionTests(unittest.TestCase):
    def test_live_forecast_errors_and_mature_margins_use_past_only(self):
        cfg=Config(horizon=3)
        trace=make_evaluation_trace(20,84,1.1);trace['harvest'][:]=2.
        df=run(trace,cfg,'adaptive_all')
        errors=[]
        for t in range(1,len(df)):
            past=t-1
            a=np.clip((40.+trace['arrival'][:past].sum())/(8+past),0.,10.)
            h=(8.8+2.*past)/(8+past) if past<3 else 2.
            v=.45**2/(1-.68**2)
            predicted=np.exp(.68*(np.log(trace['gain'][t-1])+.5*v)+.5*.45**2-.5*v)
            expected=np.array([predicted-trace['gain'][t],trace['arrival'][t]-a,h-2.])
            np.testing.assert_allclose(df.loc[t,['raw_error_gain','raw_error_arrival','raw_error_harvest']].to_numpy(dtype=float),expected)
            if t>=13:
                previous=np.asarray(errors[-50:])
                np.testing.assert_allclose(df.loc[t,['margin_gain','margin_arrival','margin_harvest']].to_numpy(dtype=float),
                                           np.maximum(0.,np.quantile(previous,.8,axis=0)))
            errors.append(expected)
        np.testing.assert_array_equal(margins([(100.,100.,100.)]*20+[(0.,0.,0.)]*50,'adaptive_all'),0.)
        np.testing.assert_array_equal(_margins([(100.,100.,100.)]*20+[(0.,0.,0.)]*40,'adaptive'),0.)

    def test_solver_roundoff_does_not_drop_a_whole_feasible_packet(self):
        cfg=Config(horizon=3,data_max=3.)
        required=float(np.expm1(np.log(2)*3/cfg.rate_scale))
        sol=dict(d=np.array([3.-1e-9]),p=np.array([required-1e-10]))
        d,p=planner_action(sol,12,6.8,1.,cfg)
        self.assertEqual(execute_packets(d,p,12,6.8,1.,cfg)[0],3)
        # A genuine fraction still floors, and even one ulp of energy shortfall
        # must not fund the normalized action.
        sol['d'][0]=2.7
        d,p=planner_action(sol,12,6.8,1.,cfg)
        self.assertEqual(execute_packets(d,p,12,6.8,1.,cfg)[0],2)
        sol['d'][0]=3.-1e-9
        budget=np.nextafter(required,0.)
        d,p=planner_action(sol,12,budget,1.,cfg)
        self.assertLessEqual(execute_packets(d,p,12,budget,1.,cfg)[0],2)
        trace=make_evaluation_trace(8,13,1.1)
        for df in (run(trace,cfg,'nominal'),run_policy(trace,'nominal',cfg,backend='cvxpy')):
            np.testing.assert_array_equal(df.attempted,3)
            self.assertTrue(audit_packets(df,cfg))

    def test_nonfinite_plans_inputs_and_invalid_configuration_are_rejected(self):
        cfg=Config(horizon=2)
        s=solve_lp(12.,7.,[.6,.8],[3.,3.],[1.,1.],cfg)
        for key in ('p','d','b','E','o','w','u'):
            for invalid in (np.nan,np.inf,-np.inf):
                corrupted={k:np.array(v,copy=True) if isinstance(v,np.ndarray) else v for k,v in s.items()}
                corrupted[key][0]=invalid
                with self.assertRaises(ValueError):verify_plan(corrupted,12.,7.,[.6,.8],[3.,3.],[1.,1.],cfg)
        with self.assertRaises(ValueError):verify_plan(s,np.nan,7.,[.6,.8],[3.,3.],[1.,1.],cfg)
        for solve in (solve_lp,solve_cvxpy):
            with self.assertRaises(ValueError):solve(12.,7.,[np.inf],[3.],[1.],cfg)
            with self.assertRaises(ValueError):solve(12.,7.,[],[],[],cfg)
        for kwargs in ({'energy_weight':np.nan},{'drop_weight':-1.},{'horizon':0},
                       {'segments':0},{'buffer_max':32.5}):
            with self.assertRaises(ValueError):Config(**kwargs)

    def test_independent_metrics_and_corrupted_accounting_are_rejected(self):
        cfg=Config(horizon=2)
        trace=make_evaluation_trace(5,81,.6)
        df=run(trace,cfg,'greedy')
        row=pd.Series(evaluate(df,cfg))
        self.assertTrue(audit_metrics(df,row,cfg))
        for metric in ('queue','energy','throughput','terminal_queue','realized_cost','acknowledged'):
            changed=row.copy();changed[metric]+=1.
            with self.assertRaises(AssertionError):audit_metrics(df,changed,cfg)
        self.assertTrue(audit_packets(df,cfg,expected_seed=81,initial_state=simulation_settings(cfg)['initial_state']))
        changed=df.copy();changed.loc[1,'reception_seed']=82
        with self.assertRaises(AssertionError):audit_packets(changed,cfg)
        changed=df.copy();changed['slot_seconds']=60.
        with self.assertRaises(AssertionError):audit_packets(changed,cfg)
        with self.assertRaises(AssertionError):audit_packets(df,cfg,initial_state=dict(queue_packets=12,energy_joules=6.))
        with self.assertRaises(AssertionError):audit_packets(df.iloc[:0],cfg)
        legacy=run_policy(trace,'greedy',cfg)
        stats=summarize(legacy,cfg).iloc[0]
        self.assertAlmostEqual(stats.energy_J,float(np.sum(legacy.data_energy+legacy.control_energy)))
        self.assertAlmostEqual(stats.throughput_bps,float(np.sum(legacy.delivered)*256/(len(legacy)*5)))

    def test_solar_intervals_and_dcp_are_explicit(self):
        settings=simulation_settings(Config())|{'dataset_slot_seconds':{'arco':60.,'nrel_tmy3':3600.}}
        self.assertEqual(trajectory_config(settings,'arco').slot_seconds,60.)
        self.assertEqual(trajectory_config(settings,'nrel_tmy3').slot_seconds,3600.)
        import cvxpy as cp
        original=cp.Problem.solve
        checks=[]
        def checked(problem,*args,**kwargs):
            checks.append(problem.is_dcp())
            return original(problem,*args,**kwargs)
        with patch.object(cp.Problem,'solve',checked):
            s=solve_cvxpy(12.,.1,[.6,.6],[3.,3.],[1.,1.],Config(horizon=2))
        self.assertTrue(checks and all(checks))
        self.assertLess(max(verify_plan(s,12.,.1,[.6,.6],[3.,3.],[1.,1.]).values()),1e-4)


def fixture_data(root):
    """Tiny format-compatible inputs, never presented as the real solar datasets."""
    for folder in ('arco','umass','nrel'):(root/'data'/folder).mkdir(parents=True)
    rows=[]
    for day in pd.to_datetime(['2018-08-01','2018-08-02','2018-09-12','2018-09-13']):
        for hour in (6,8,10,12,14,17,19,21):
            for minute in range(4):
                stamp=day+pd.Timedelta(hours=hour,minutes=minute)
                rows.append((stamp.strftime('%d/%m/%Y'),stamp.strftime('%H:%M:%S'),str(80+minute)))
    pd.DataFrame(rows,columns=['Date','Hour','PV sc Current']).to_csv(root/'data/arco/dataset.csv',sep=';',index=False)
    with tarfile.open(root/'data/umass/homeC-generation.tar.gz','w:gz') as archive:
        for j,day in enumerate(pd.date_range('2013-01-01',periods=32,tz='UTC')):
            start=day+pd.Timedelta(hours=(8,12,17,21)[j%4])
            data=''.join(f'{int((start+pd.Timedelta(minutes=m)).timestamp())},0,0,4,5,{6+m},3.3\n' for m in range(4)).encode()
            member=tarfile.TarInfo(f'{j:02d}.csv');member.size=len(data)
            archive.addfile(member,io.BytesIO(data))
    path=root/'data/nrel/723170TYA.CSV'
    path.write_text('ARTIFICIAL TEST FIXTURE\nGHI (W/m^2)\n'+'\n'.join(str(100+i%24) for i in range(5000))+'\n')


class EntryPointSmokeTests(unittest.TestCase):
    def test_small_experiments_loaders_audits_and_figures(self):
        repo=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix='ee541_smoke_') as directory:
            root=Path(directory);fixture_data(root);out=root/'outputs'
            def cli(script,*args,success=True):
                result=subprocess.run([sys.executable,'-B',str(repo/script),*map(str,args)],cwd=root,
                                      env=os.environ|{'MPLCONFIGDIR':'/tmp/ee541-matplotlib'},
                                      capture_output=True,text=True,timeout=50)
                if success:self.assertEqual(result.returncode,0,f'{script}: {result.stdout[-1000:]}\n{result.stderr[-2000:]}')
                else:self.assertNotEqual(result.returncode,0)
                return result
            cli('final_evaluation.py','--seeds',2,'--slots',3,'--horizon',2,'--out',out/'sweep')
            cli('verify_synthetic_results.py',out/'sweep')
            matrix_path=out/'sweep/run_matrix.csv';matrix_original=matrix_path.read_bytes()
            corrupt=pd.read_csv(matrix_path);corrupt.loc[0,'mode']='wrong_policy'
            corrupt.to_csv(matrix_path,index=False)
            cli('verify_synthetic_results.py',out/'sweep',success=False)
            matrix_path.write_bytes(matrix_original)
            cli('final_evaluation.py','--mean-normalize','--seeds',2,'--slots',3,'--horizon',2,'--out',out/'sweep_normalized')
            cli('verify_synthetic_results.py',out/'sweep_normalized')
            cli('final_solar_evaluation.py','--validate-only','--windows',2,'--slots',3,'--horizon',2,'--out',out/'solar')
            self.assertTrue((out/'solar/run_matrix.csv').exists())
            self.assertFalse((out/'solar/per_slot.csv').exists())
            self.assertFalse((out/'solar/partial_slots.csv').exists())
            cli('final_solar_evaluation.py','--windows',2,'--slots',3,'--horizon',2,'--out',out/'solar')
            cli('verify_solar_actions.py',out/'solar')
            cli('verify_solar_sources.py',out/'solar')
            settings=json.loads((out/'solar/settings.json').read_text())
            self.assertEqual(settings['dataset_slot_seconds'],dict(arco=60.,umass_home_c=60.,nrel_tmy3=3600.))
            self.assertEqual(settings['planned_policy_runs'],60)
            self.assertEqual(len(settings['modes']),10)
            matrix=pd.read_csv(out/'solar/run_matrix.csv')
            self.assertEqual(len(matrix),60)
            self.assertFalse(matrix.duplicated(['dataset','window','mode']).any())
            self.assertTrue((matrix.groupby(['dataset','window']).size()==10).all())
            self.assertEqual(len(pd.read_csv(out/'solar/per_slot.csv')),180)
            for group in ('sweep','sweep_normalized','solar'):
                packets=pd.read_csv(out/group/'per_packet.csv')
                self.assertFalse(packets.duplicated(['run_id','packet_id']).any())
                self.assertTrue({'initial_wait_s','ack_completion_delay_s','outstanding_age_s'}<=set(packets))
                runs=pd.read_csv(out/group/('per_window.csv' if group=='solar' else 'per_seed.csv'))
                self.assertEqual(packets.run_id.nunique(),len(runs))
                pairs=pd.read_csv(out/group/'paired_vs_nominal.csv')
                delays=pairs[pairs.metric=='mean_ack_completion_delay_s']
                self.assertTrue((delays.n==delays.n_valid_pairs).all())
                self.assertTrue((delays.n<=2).all())
                self.assertEqual((out/group/'per_slot.csv').read_bytes(),(out/group/'partial_slots.csv').read_bytes())
            settings_path=out/'solar/settings.json';original=settings_path.read_text()
            settings['window_manifest']['arco']['pairwise_overlap'][0]['overlap_samples']+=1
            settings_path.write_text(json.dumps(settings))
            failed=cli('verify_solar_sources.py',out/'solar',success=False)
            self.assertIn('manifest mismatch',failed.stderr)
            settings_path.write_text(original)
            cli('offline_reference.py','--root',out)
            cli('verify_offline_reference.py',out/'offline')
            offline=pd.read_csv(out/'offline/per_instance.csv')
            self.assertEqual(len(offline),18)
            self.assertFalse((offline.status=='failed').any())
            cli('plot_final_figures.py','--root',out)
            self.assertTrue((out/'figures/one_step_coverage.png').exists())
            cli('solver_crosscheck.py','--out',out/'solver')
            solver=pd.read_csv(out/'solver/solver_results.csv')
            self.assertEqual(len(solver),12)
            self.assertFalse((solver.status=='failed').any())


if __name__=='__main__':unittest.main()
