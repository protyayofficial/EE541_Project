"""Five-packet actions, virtual packet timestamps, censoring and output audits."""
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
from final_evaluation import evaluate
from proposal_study import run,METHODS
from src.experiment import run_policy,make_trace,summarize
from src.scheduling import Config,execute_packets,planner_action,solve_cvxpy,solve_lp,verify_plan
from src.radio import PacketRadio,PacketQueue,reception_uniform
from src.packets import PacketLedger,packet_table,delay_metrics,run_delay_metrics,append_packet_run,paired_stats
from src.auditing import audit_packets,audit_packet_ledger,audit_packet_outputs


def trace(arrivals,gain=1.,harvest=1.):
    n=len(arrivals)
    return dict(seed=91,gain=np.full(n,gain),arrival=np.asarray(arrivals),harvest=np.full(n,harvest))


class FivePacketDelayTests(unittest.TestCase):
    def test_five_successes_and_exact_shannon_attempt_energy(self):
        cfg=Config(bit_error_probability=0.);self.assertEqual(cfg.data_max,5.)
        radio=PacketRadio(5,cfg);radio.probe(7.,1.)
        r=radio.execute(5.,3.,7.,10,0.)
        self.assertEqual((r['attempted'],r['acknowledged']),(5,5))
        self.assertEqual(json.loads(r['acknowledged_ids']),list(range(5)))
        required=np.expm1(np.log(2)*5*cfg.packet_bits/(cfg.bandwidth_hz*cfg.tau))
        self.assertAlmostEqual(r['data_energy'],required*cfg.tau)
        self.assertAlmostEqual(r['energy'],.2+required)
        records=pd.DataFrame(radio.queue.ledger.snapshot(5.))
        np.testing.assert_allclose(records.loc[:4,'first_attempt_time_s'],1.6)
        np.testing.assert_allclose(records.loc[:4,'first_ack_time_s'],3.6)
        self.assertTrue(records.loc[:4,'is_initial'].all())
        self.assertTrue(records.loc[5:,'first_attempt_time_s'].isna().all())
        self.assertTrue(audit_packet_ledger(pd.DataFrame([r|dict(t=0)]),records,delay_metrics(records)))

    def test_partial_five_acks_retry_priority_and_duplicate_ack_timestamps(self):
        cfg=Config();radio=PacketRadio(5,cfg);radio.probe(7.,1.)
        outcome=lambda seed,i,retry:1. if i in (1,3) and retry==0 else 0.
        with patch('src.radio.reception_uniform',side_effect=outcome):r=radio.execute(5.,3.,7.,2,0.)
        self.assertEqual(json.loads(r['acknowledged_ids']),[0,2,4])
        self.assertEqual(radio.queue.ids,[1,3,5,6])
        radio.probe(r['E_next'],1.)
        with patch('src.radio.reception_uniform',side_effect=outcome):r2=radio.execute(2.,3.,r['E_next'],0,0.)
        self.assertEqual(json.loads(r2['attempted_ids']),[1,3])
        before=radio.queue.ledger.records[1].copy()
        self.assertEqual(before['attempt_count'],2)
        self.assertEqual(before['first_attempt_time_s'],1.6)
        self.assertEqual(before['first_ack_time_s'],8.6)
        self.assertEqual(radio.queue.acknowledge([1,1,3],time_s=13.6),[])
        self.assertEqual(radio.queue.ledger.records[1],before)
        received,new=radio.receiver.receive([1],[2],3.,1.,cfg)
        self.assertEqual(received,[1]);self.assertEqual(new,[])
        self.assertEqual(len(radio.receiver.delivered),5)

    def test_failed_five_attempts_are_charged_and_energy_limits_reduce_action(self):
        cfg=Config(bit_error_probability=1.)
        radio=PacketRadio(8,cfg);radio.probe(7.,1.)
        r=radio.execute(5.,3.,7.,0,0.)
        self.assertEqual((r['attempted'],r['received'],r['acknowledged']),(5,0,0))
        self.assertGreater(r['data_energy'],0.)
        self.assertAlmostEqual(r['E_next'],7.-r['energy'])
        p2=np.expm1(np.log(2)*2/cfg.rate_scale)
        for energy,max_action in ((.19,0),(.2,0),(.2+p2*.999,1),(.2+p2*1.001,2)):
            radio=PacketRadio(8,cfg);radio.probe(energy,1.)
            r=radio.execute(5.,3.,energy,0,10.)
            self.assertLessEqual(r['attempted'],max_action)
            self.assertLessEqual(r['energy'],energy)
        radio=PacketRadio(8,cfg);radio.probe(7.,.1)
        r=radio.execute(5.,3.,7.,0,0.)
        self.assertEqual(r['attempted'],4)  # A5 exceeds the configured power cap.

    def test_five_packet_roundoff_safeguard_and_both_planning_bounds(self):
        cfg=Config(horizon=3)
        for solve in (solve_cvxpy,solve_lp):
            sol=solve(12.,7.,[1.]*3,[5.]*3,[1.]*3,cfg)
            self.assertLess(max(verify_plan(sol,12.,7.,[1.]*3,[5.]*3,[1.]*3,cfg).values()),1e-4)
            self.assertTrue((sol['d']<=cfg.data_max+1e-6).all())
            self.assertGreater(sol['d'][0],4.99)
        required=np.expm1(np.log(2)*5/cfg.rate_scale)
        sol=dict(d=np.array([5.-1e-9]),p=np.array([required-1e-10]))
        d,p=planner_action(sol,12,6.8,1.,cfg)
        self.assertEqual(execute_packets(d,p,12,6.8,1.,cfg)[0],5)
        d,p=planner_action(sol,12,np.nextafter(required,0.),1.,cfg)
        self.assertLessEqual(execute_packets(d,p,12,np.nextafter(required,0.),1.,cfg)[0],4)

    def test_overflow_is_after_actual_five_packet_ack_departures(self):
        cfg=Config();radio=PacketRadio(32,cfg);radio.probe(7.,1.)
        with patch('src.radio.reception_uniform',side_effect=lambda seed,i,retry:0. if i<3 else 1.):
            r=radio.execute(5.,3.,7.,10,0.)
        self.assertEqual(r['acknowledged'],3)
        self.assertEqual(r['forced_drop'],7)
        self.assertEqual(r['b_next'],32)
        p=pd.DataFrame(radio.queue.ledger.snapshot(5.))
        self.assertEqual((p.status=='rejected_before_admission').sum(),7)
        rejected=p[p.status=='rejected_before_admission']
        self.assertTrue(rejected[['admission_time_s','initial_wait_s','ack_completion_delay_s']].isna().all().all())
        self.assertTrue((rejected.offered_time_s==5.).all())

    def test_deterministic_wait_ack_and_retry_timing_example(self):
        for failure,expected in ((False,3.6),(True,8.6)):
            cfg=Config(horizon=2)
            outcome=lambda seed,i,retry:1. if failure and retry==0 else 0.
            with patch('src.radio.reception_uniform',side_effect=outcome),patch('src.auditing.reception_uniform',side_effect=outcome):
                df=run_policy(trace([1,0,0]),'greedy',cfg,b0=0)
                self.assertTrue(audit_packets(df,cfg))
            p=packet_table(df).iloc[0]
            self.assertEqual(p.admission_time_s,5.)
            self.assertEqual(p.first_attempt_time_s,6.6)
            self.assertAlmostEqual(p.initial_wait_s,1.6)
            self.assertAlmostEqual(p.ack_completion_delay_s,expected)
            self.assertEqual(p.first_ack_time_s,13.6 if failure else 8.6)
            self.assertEqual(p.attempt_count,2 if failure else 1)
            stats=run_delay_metrics(df)
            self.assertAlmostEqual(stats['mean_initial_wait_s'],1.6)
            self.assertAlmostEqual(stats['mean_ack_completion_delay_s'],expected)
            self.assertTrue(audit_packet_ledger(df,packet_table(df),stats))

    def test_initial_exclusion_rejections_and_terminal_admissions(self):
        cfg=Config(bit_error_probability=0.)
        df=run_policy(trace([2,1,100]),'greedy',cfg,b0=2)
        packets=packet_table(df);stats=run_delay_metrics(df)
        self.assertEqual(stats['initial_packets'],2)
        self.assertEqual(stats['initial_acknowledged_packets'],2)
        self.assertEqual(stats['newly_admitted_packets'],35)
        self.assertEqual(stats['newly_attempted_packets'],3)
        self.assertEqual(stats['newly_acknowledged_packets'],3)
        self.assertEqual(stats['outstanding_packets'],32)
        self.assertEqual(stats['rejected_arrivals'],68)
        self.assertAlmostEqual(stats['mean_initial_wait_s'],1.6)
        self.assertAlmostEqual(stats['mean_ack_completion_delay_s'],3.6)
        self.assertTrue(packets[packets.is_initial].offered_time_s.isna().all())
        self.assertTrue((packets[packets.is_initial].admission_time_s==0.).all())
        self.assertTrue((packets[packets.status=='outstanding'].outstanding_age_s==0.).all())
        self.assertTrue(audit_packets(df,cfg))
        self.assertTrue(audit_packet_ledger(df,packets,stats))

    def test_no_completed_observations_and_unfinished_ages(self):
        cfg=Config(bit_error_probability=1.)
        df=run_policy(trace([2,0,0]),'greedy',cfg,b0=0)
        packets=packet_table(df);stats=run_delay_metrics(df)
        self.assertEqual(stats['newly_admitted_packets'],2)
        self.assertEqual(stats['initial_wait_samples'],2)
        self.assertEqual(stats['ack_completion_delay_samples'],0)
        self.assertTrue(np.isnan(stats['mean_ack_completion_delay_s']))
        self.assertTrue((packets.outstanding_age_s==10.).all())
        self.assertTrue(packets.first_ack_time_s.isna().all())
        self.assertTrue(packets.ack_completion_unfinished.all())
        self.assertFalse(packets.initial_wait_unfinished.any())
        self.assertTrue(audit_packet_ledger(df,packets,stats))
        with self.assertRaises(AssertionError):
            audit_packet_ledger(df,packets,stats|{'mean_ack_completion_delay_s':0.})
        never=run_policy(trace([2]),'greedy',Config(),b0=0)
        self.assertTrue(np.isnan(run_delay_metrics(never)['mean_initial_wait_s']))
        self.assertTrue(packet_table(never).initial_wait_unfinished.all())
        self.assertEqual(run_delay_metrics(never)['admitted_never_attempted_packets'],2)

    def test_solar_seconds_and_same_burst_timestamps(self):
        for seconds in (60.,3600.):
            cfg=Config(slot_seconds=seconds,bit_error_probability=0.)
            df=run_policy(trace([5,0]),'greedy',cfg,b0=0)
            packets=packet_table(df)
            self.assertTrue((packets.admission_time_s==seconds).all())
            np.testing.assert_allclose(packets.first_attempt_time_s,seconds+1.6)
            np.testing.assert_allclose(packets.first_ack_time_s,seconds+3.6)
            np.testing.assert_allclose(packets.initial_wait_s,1.6)
            np.testing.assert_allclose(packets.ack_completion_delay_s,3.6)
            self.assertEqual(packets.first_attempt_time_s.nunique(),1)
            self.assertTrue(audit_packet_ledger(df,packets,run_delay_metrics(df)))
            with patch('src.radio.reception_uniform',side_effect=lambda seed,i,retry:1. if retry==0 else 0.):
                retry=run_policy(trace([1,0,0]),'greedy',cfg,b0=0)
            self.assertAlmostEqual(packet_table(retry).ack_completion_delay_s.iloc[0],seconds+3.6)

    def test_empty_packet_run_exports_and_no_eligible_pair_statistics(self):
        df=run_policy(trace([0,0]),'greedy',Config(),b0=0)
        stats=run_delay_metrics(df)
        self.assertEqual(stats['initial_packets'],0)
        self.assertTrue(np.isnan(stats['mean_initial_wait_s']))
        self.assertTrue(np.isnan(stats['mean_outstanding_age_s']))
        self.assertTrue(audit_packet_ledger(df,packet_table(df),stats))
        pair=paired_stats([np.nan,np.nan]);self.assertEqual(pair['n_valid_pairs'],0)
        self.assertTrue(np.isnan(pair['delta']) and np.isnan(pair['ci_low']))
        with tempfile.TemporaryDirectory() as directory:
            run_id=append_packet_run(df,directory,dict(experiment='test'))
            slots=df.assign(run_id=run_id)
            self.assertTrue(audit_packet_outputs(directory,slots,pd.DataFrame([stats|dict(run_id=run_id)])))

    def test_export_identifiers_and_independent_audit_reject_corruption(self):
        cfg=Config(bit_error_probability=0.);tr=trace([2,0,0])
        a=run_policy(tr,'greedy',cfg,b0=0);b=run_policy(tr,'fixed',cfg,b0=0)
        combined=summarize(pd.concat([a,b]),cfg)
        np.testing.assert_allclose(combined.mean_initial_wait_s,1.6)
        with tempfile.TemporaryDirectory() as directory:
            rows=[];slots=[]
            for df in (a,b):
                mode=df['mode'].iloc[0];run_id=append_packet_run(df,directory,dict(experiment='test',mode=mode))
                rows.append(run_delay_metrics(df)|dict(run_id=run_id,mode=mode));slots.append(df.assign(run_id=run_id))
            packets=pd.read_csv(Path(directory)/'per_packet.csv')
            self.assertEqual(packets.run_id.nunique(),2)
            self.assertFalse(packets.duplicated(['run_id','packet_id']).any())
            self.assertTrue(audit_packet_outputs(directory,pd.concat(slots),pd.DataFrame(rows)))
            read=pd.read_csv
            def tiny_chunks(*args,**kwargs):
                if 'chunksize' in kwargs:kwargs['chunksize']=1
                return read(*args,**kwargs)
            with patch('src.packet_audit.pd.read_csv',side_effect=tiny_chunks):
                self.assertTrue(audit_packet_outputs(directory,pd.concat(slots),pd.DataFrame(rows)))
            bad_rows=pd.DataFrame(rows);bad_rows.loc[0,'mean_initial_wait_s']=0.
            with self.assertRaises(AssertionError):audit_packet_outputs(directory,pd.concat(slots),bad_rows)
        expected=run_delay_metrics(a)
        for column in ('first_attempt_time_s','first_ack_time_s','attempt_count','admission_time_s','initial_wait_s','ack_completion_delay_s'):
            bad=packet_table(a).copy();bad.loc[0,column]+=1
            with self.subTest(column=column),self.assertRaises(AssertionError):audit_packet_ledger(a,bad,expected)
        bad=expected|{'mean_initial_wait_s':0.}
        with self.assertRaises(AssertionError):audit_packet_ledger(a,packet_table(a),bad)

    def test_complete_metadata_identity_and_same_policy_scenario_separation(self):
        df=run_policy(trace([1,0]),'greedy',Config(bit_error_probability=0.),b0=0)
        with tempfile.TemporaryDirectory() as directory:
            rows=[];slots=[]
            for window in ('artificial_a','artificial_b'):
                identity=dict(experiment='test',dataset='artificial',window=window,mode='greedy',seed=91,
                              margin_scale=.30000000000000004)
                run_id=append_packet_run(df,directory,identity)
                rows.append(run_delay_metrics(df)|identity|dict(run_id=run_id))
                slots.append(df.assign(**identity,run_id=run_id))
            runs=pd.DataFrame(rows);trajectories=pd.concat(slots)
            path=Path(directory)/'per_packet.csv'
            original=pd.read_csv(path,float_precision='round_trip')
            self.assertEqual(len(original),2)  # One packet per run, overlapping IDs.
            self.assertEqual(original.run_id.nunique(),2)
            read=pd.read_csv
            def tiny_chunks(*args,**kwargs):
                if 'chunksize' in kwargs:kwargs['chunksize']=1
                return read(*args,**kwargs)
            with patch('src.packet_audit.pd.read_csv',side_effect=tiny_chunks):
                self.assertTrue(audit_packet_outputs(directory,trajectories,runs))
            for key,value in (('horizon',999),('data_max',4.),('channel_rho',.5),
                              ('channel_sigma',.8),('mean_normalize',False),
                              ('config_id','corrupted'),('experiment','wrong_experiment'),
                              ('window','artificial_b'),('run_id',runs.run_id.iloc[1])):
                bad=original.copy();bad.loc[0,key]=value;bad.to_csv(path,index=False)
                with self.subTest(key=key),self.assertRaises(AssertionError):
                    audit_packet_outputs(directory,trajectories,runs)
            original.to_csv(path,index=False)
            self.assertTrue(audit_packet_outputs(directory,trajectories,runs))

    def test_consistency_summary_counts_valid_delay_runs(self):
        import consistency_study
        from src.radio import simulation_settings
        with tempfile.TemporaryDirectory(prefix='ee541_artificial_consistency_') as directory:
            root=Path(directory);out=root/'output'
            original=root/'results/proposal_final';original.mkdir(parents=True)
            (original/'settings.json').write_text(json.dumps({'dataset_sha256':{}}))
            windows=[('artificial_empty',np.ones(60)),('artificial_admitted',np.ones(60))]
            def generated(slots,seed,**kwargs):
                return trace(np.zeros(slots,dtype=int) if seed==1800 else np.ones(slots,dtype=int))|dict(seed=seed)
            before=Path.cwd()
            try:
                os.chdir(root)
                with patch('sys.argv',['consistency_study.py','--out',str(out)]),\
                     patch.object(consistency_study,'FILES',()),\
                     patch.object(consistency_study,'ALL',('nominal','nominal_forced')),\
                     patch.object(consistency_study,'fresh_windows',return_value=[('artificial',60.,windows)]),\
                     patch.object(consistency_study,'make_trace',side_effect=generated),\
                     patch('sys.stdout',io.StringIO()):
                    consistency_study.main()
            finally:os.chdir(before)
            summary=pd.read_csv(out/'summary.csv',header=[0,1],index_col=[0,1])
            runs=pd.read_csv(out/'per_window.csv');slots=pd.read_csv(out/'per_slot.csv')
            for metric in ('mean_initial_wait_s','mean_ack_completion_delay_s'):
                self.assertTrue((summary[(metric,'count')]==1).all())
                self.assertEqual(runs[metric].notna().sum(),2)
            pairs=pd.read_csv(out/'paired.csv');delay=pairs[pairs.metric=='mean_ack_completion_delay_s']
            selected=delay[delay.fix=='nominal_forced'].iloc[0]
            self.assertEqual(selected.n_valid_pairs,1)
            self.assertTrue(np.isnan(selected.ci_low))
            self.assertTrue(audit_packet_outputs(out,slots,runs))
            cfg=Config(slot_seconds=60.)
            for _,group in slots.groupby('run_id'):
                self.assertTrue(audit_packets(group,cfg,initial_state=simulation_settings(cfg)['initial_state']))

    def test_bookkeeping_never_changes_randomness_or_actions(self):
        class NoLedger:
            def __init__(self,*a):pass
            def attempts(self,*a):pass
            def acknowledge(self,*a):pass
            def arrive(self,*a):pass
            def snapshot(self,*a):return []
        tr=make_trace(4,7000);cfg=Config(horizon=2)
        for runner in (lambda mode:run(tr,cfg,mode),lambda mode:run_policy(tr,mode,cfg)):
            for mode in ('greedy','fixed','nominal'):
                with patch('src.radio.reception_uniform',wraps=reception_uniform) as draws:tracked=runner(mode)
                self.assertEqual(draws.call_count,int(tracked.attempted.sum()))
                with patch('src.radio.PacketLedger',NoLedger),patch('src.radio.reception_uniform',wraps=reception_uniform) as draws:
                    untracked=runner(mode)
                self.assertEqual(draws.call_count,int(untracked.attempted.sum()))
                fields=['p','attempted_ids','retry_numbers','received_ids','acknowledged_ids','queue_next_ids','E_next']
                x,y=tracked[fields].copy(),untracked[fields].copy();x.attrs={};y.attrs={}
                pd.testing.assert_frame_equal(x,y)
        with patch('numpy.random.default_rng',side_effect=AssertionError('bookkeeping drew randomness')):
            ledger=PacketLedger(0);ledger.arrive([0],[],[],5.);ledger.attempts([0],6.6);ledger.acknowledge([0],8.6)
            self.assertEqual(ledger.snapshot(10.)[0]['attempt_count'],1)


if __name__=='__main__':unittest.main()
