"""Fixed supplementary protocols, causal noise, paired metrics and CLI audits."""
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import numpy as np
import pandas as pd
from audit_supplementary import audit,audit_forecasts
from final_evaluation import make_evaluation_trace,planned_runs as main_runs
from final_solar_evaluation import planned_runs as solar_runs
from proposal_study import run
from src.auditing import audit_packets,audit_packet_ledger
from src.forecast_noise import standard_normal,perturb_channel
from src.packets import packet_table,run_delay_metrics
from src.scheduling import Config
from supplementary_studies import VALUES,planned_runs,run_case,reference_cost,scenario_key,comparison_tables


class SupplementaryTests(unittest.TestCase):
    def test_fixed_matrices_and_main_design_preserved(self):
        for study in VALUES:
            matrix=pd.DataFrame(planned_runs(study))
            self.assertEqual(len(matrix),120)
            self.assertFalse(matrix.duplicated(['harvest_mean','seed','mode','study_value']).any())
            self.assertEqual(set(matrix.seed),set(range(6000,6010)))
            self.assertEqual(set(matrix['mode']),{'nominal','adaptive_all'})
            self.assertTrue((matrix.groupby(['harvest_mean','seed','mode']).size()==3).all())
            self.assertEqual(len(planned_runs(study,benchmark_case=True)),1)
        self.assertEqual(VALUES['delay_energy'],(.15,15.,150.))
        self.assertEqual(VALUES['forecast_sensitivity'],(0.,.25,.5))
        self.assertEqual(len(main_runs())+len(main_runs(mean_normalize=True))+len(solar_runs()),900)
        self.assertEqual((Config().data_max,Config().horizon,Config().energy_weight),(5.,10,.15))

    def test_keyed_noise_reproducibility_amplitude_and_mean(self):
        scenario=scenario_key(.6,6000);base=np.array([.9,1.1,1.2,1.3])
        first,z,m=perturb_channel(base,.25,scenario,7)
        again,z2,m2=perturb_channel(base,.5,scenario,7)
        np.testing.assert_array_equal(z,z2)
        np.testing.assert_allclose(np.log(m[1:]),.25*z[1:]-.5*.25**2)
        np.testing.assert_allclose(np.log(m2[1:]),.5*z[1:]-.5*.5**2)
        self.assertEqual(first[0],base[0]);self.assertEqual(again[0],base[0])
        self.assertEqual(standard_normal(scenario,7,2),z[2])
        self.assertNotEqual(standard_normal(scenario,7,2),standard_normal(scenario,8,2))
        # Distribution check is independent of policy/receiver execution.
        values=np.array([standard_normal('distribution-check',t,1) for t in range(12000)])
        self.assertLess(abs(values.mean()),.04)
        self.assertLess(abs(values.std()-1),.04)
        self.assertLess(abs(np.exp(.5*values-.125).mean()-1),.025)
        np.testing.assert_array_equal(perturb_channel(base,0,scenario,7)[0],base)
        for invalid in (-1,np.nan,np.inf):
            with self.assertRaises(ValueError):perturb_channel(base,invalid,scenario,7)

    def test_exact_zero_baseline_and_no_future_information(self):
        trace=make_evaluation_trace(16,6000,.6);cfg=Config(horizon=4)
        timing={'solve_ms','solver_runtime_s','decision_runtime_s','solver_budget_exceeded','decision_budget_exceeded'}
        for mode in ('nominal','adaptive_all'):
            baseline=run(trace,cfg,mode)
            measured=run(trace,cfg,mode,forecast_perturbation=0.,forecast_scenario='test',log_forecasts=True)
            columns=[c for c in baseline if c not in timing]
            a=baseline[columns].copy();b=measured[columns].copy();a.attrs={};b.attrs={}
            pd.testing.assert_frame_equal(a,b,check_exact=True)
            pd.testing.assert_frame_equal(packet_table(baseline),packet_table(measured),check_exact=True)
        altered={k:np.array(v,copy=True) if isinstance(v,np.ndarray) else v for k,v in trace.items()}
        altered['gain'][1:]*=9;altered['arrival'][1:]=10;altered['harvest'][1:]=0
        a=run(trace,cfg,'nominal',forecast_perturbation=.5,forecast_scenario='causal')
        b=run(altered,cfg,'nominal',forecast_perturbation=.5,forecast_scenario='causal')
        for field in ('p','attempted_ids','reported_gain','base_channel_forecasts','perturbed_channel_forecasts','forecast_noise_z'):
            self.assertEqual(a.iloc[0][field],b.iloc[0][field])

    def test_policy_order_matched_inputs_and_perturbed_adaptive_history(self):
        cfg=Config(horizon=4);trace=make_evaluation_trace(20,6002,1.2);scenario=scenario_key(1.2,6002)
        first={mode:run(trace,cfg,mode,forecast_perturbation=.5,forecast_scenario=scenario) for mode in ('nominal','adaptive_all')}
        for mode in ('adaptive_all','nominal'):
            frame=run(trace,cfg,mode,forecast_perturbation=.5,forecast_scenario=scenario)
            for field in ('gain','arrivals','harvest','forecast_noise_z','attempted_ids','received_ids','queue_next_ids','E_next'):
                pd.testing.assert_series_equal(frame[field],first[mode][field])
            mult,_=audit_forecasts(frame,cfg,.5,scenario)
            self.assertTrue(audit_packets(frame,cfg,channel_forecast_multipliers=mult))
            self.assertTrue(audit_packet_ledger(frame,packet_table(frame),run_delay_metrics(frame)))
        adaptive=first['adaptive_all']
        for t in range(1,len(adaptive)):
            if adaptive.probe_available.iloc[t]:
                self.assertAlmostEqual(adaptive.raw_error_gain.iloc[t],json.loads(adaptive.perturbed_channel_forecasts.iloc[t-1])[1]-adaptive.reported_gain.iloc[t])
        for field in ('gain','arrivals','harvest','forecast_noise_z'):
            pd.testing.assert_series_equal(first['nominal'][field],first['adaptive_all'][field])

    def test_missed_probes_do_not_shift_keys_or_current_report(self):
        cfg=Config(horizon=4);trace=make_evaluation_trace(30,6000,.6)
        trace['harvest'][:]=0;trace['harvest'][20]=5.
        scenario=scenario_key(.6,6000)
        frame=run(trace,cfg,'adaptive_all',forecast_perturbation=.25,forecast_scenario=scenario)
        self.assertTrue((~frame.probe_available).any())
        self.assertTrue(frame.probe_available.iloc[21:].any())
        multipliers,_=audit_forecasts(frame,cfg,.25,scenario)
        self.assertTrue(audit_packets(frame,cfg,channel_forecast_multipliers=multipliers))
        for r in frame.itertuples(index=False):
            z=json.loads(r.forecast_noise_z)
            if len(z)>1:self.assertEqual(z[1],standard_normal(scenario,r.t,1))
            if r.probe_available:self.assertEqual(json.loads(r.planned_channel_forecasts)[0],r.reported_gain)
            else:self.assertTrue(np.isnan(r.reported_gain));self.assertEqual(r.attempted,0)

    def test_constant_weight_costs_and_matching_across_settings(self):
        actual=None
        for value in VALUES['delay_energy']:
            case=planned_runs('delay_energy',seeds=1)[int(VALUES['delay_energy'].index(value))]
            frame,stats,_=run_case(case,slots=5,horizon=3)
            expected=frame.b.sum()+35*frame['drop'].sum()+value*frame.energy.sum()+6*frame.b_next.iloc[-1]
            self.assertAlmostEqual(stats['configured_objective_cost'],expected)
            self.assertAlmostEqual(stats['common_reference_cost'],reference_cost(frame))
            columns=['actual_gain','arrivals','harvest']
            current=frame[columns].copy();current.attrs={}
            if actual is not None:pd.testing.assert_frame_equal(actual,current)
            actual=current
        row=dict(study='delay_energy',harvest_mean=.6,study_value=.15,mode='nominal',seed=6000,**stats)
        empty=row|dict(mode='adaptive_all',mean_initial_wait_s=np.nan,mean_ack_completion_delay_s=np.nan)
        a,b=comparison_tables(pd.DataFrame([row,empty]))
        wait=a[a.metric=='mean_initial_wait_s'].iloc[0]
        self.assertEqual(wait.n_valid_pairs,0);self.assertTrue(np.isnan(wait.delta))

    def test_cli_plan_smoke_analysis_audits_plots_and_corruption(self):
        repo=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix='ee541_supplementary_smoke_') as directory:
            def cli(script,*args):
                result=subprocess.run([sys.executable,'-B',str(repo/script),*map(str,args)],cwd=repo,
                    env=os.environ|dict(MPLCONFIGDIR='/tmp/ee541-matplotlib'),capture_output=True,text=True,timeout=80)
                self.assertEqual(result.returncode,0,result.stdout[-1000:]+result.stderr[-2500:])
            for study in VALUES:
                out=Path(directory)/study
                cli('supplementary_studies.py',study,'--plan-only','--out',out)
                self.assertEqual(len(pd.read_csv(out/'run_matrix.csv')),120)
                self.assertFalse((out/'per_packet.csv').exists())
                # Separate short configuration; keep the full plan untouched.
                out=Path(directory)/(study+'_short')
                cli('supplementary_studies.py',study,'--seeds',2,'--slots',4,'--horizon',3,'--plan-only','--out',out)
                cli('supplementary_studies.py',study,'--seeds',2,'--slots',4,'--horizon',3,'--out',out)
                cli('analyze_supplementary.py',out);cli('audit_supplementary.py',out)
                raw=pd.read_csv(out/'per_seed.csv');slots=pd.read_csv(out/'per_slot.csv');packets=pd.read_csv(out/'per_packet.csv')
                self.assertEqual(len(raw),24);self.assertEqual(raw.run_id.nunique(),24)
                self.assertFalse(packets.duplicated(['run_id','packet_id']).any())
                self.assertTrue(slots.attempted.between(0,5).all())
                self.assertTrue((out/'delay_energy.png').exists());self.assertTrue((out/'channel_forecast_errors.png').exists())
                for _,group in slots.groupby('run_id'):self.assertEqual(group.energy_weight.nunique(),1)
                for filename,column in (('per_seed.csv','common_reference_cost'),('paired_vs_nominal.csv','n_valid_pairs'),
                                        ('per_packet.csv','first_attempt_time_s')):
                    path=out/filename;original=path.read_bytes();bad=pd.read_csv(path)
                    index=bad[column].first_valid_index();self.assertIsNotNone(index)
                    bad.loc[index,column]+=1;bad.to_csv(path,index=False)
                    with self.subTest(study=study,corrupt=column),self.assertRaises(AssertionError):audit(out)
                    path.write_bytes(original)
                path=out/'per_slot.csv';original=path.read_bytes();bad=pd.read_csv(path)
                vector=json.loads(bad.loc[0,'forecast_noise_z']);vector[1]+=1
                bad.loc[0,'forecast_noise_z']=json.dumps(vector);bad.to_csv(path,index=False)
                with self.assertRaises(AssertionError):audit(out)
                path.write_bytes(original)


if __name__=='__main__':unittest.main()
