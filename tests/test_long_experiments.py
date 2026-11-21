"""Long-episode design tests. Every generated solar sample here is artificial."""
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

import numpy as np
import pandas as pd

import final_evaluation
from final_solar_evaluation import MODES,planned_runs
from proposal_study import run
from src.auditing import audit_packets
from src.course_data import load_solar,load_umass,load_nrel,select_windows
from src.experiment import make_trace
from src.scheduling import Config


class LongExperimentTests(unittest.TestCase):
    def test_exact_matrix_defaults_and_distinct_policies(self):
        self.assertEqual(final_evaluation.DEFAULT_SLOTS,1000)
        self.assertEqual(Config().horizon,10)
        self.assertEqual(final_evaluation.HARVEST,(.6,1.2))
        self.assertEqual(final_evaluation.MODES,('greedy','nominal','fixed_margin','adaptive_harvest','adaptive_all'))
        original=('fixed','channel','greedy','nominal','fixed_margin','adaptive_harvest','adaptive_all')
        self.assertEqual(MODES[:7],original)
        self.assertEqual(MODES[7:],('fixed_fraction','adaptive_channel','adaptive_arrival'))
        matrix=pd.DataFrame(planned_runs())
        self.assertEqual(len(matrix),300)
        self.assertFalse(matrix.duplicated(['dataset','scenario_index','mode']).any())
        self.assertEqual(matrix.groupby(['dataset','scenario_index']).ngroups,30)
        for _,g in matrix.groupby(['dataset','scenario_index']):
            self.assertEqual(len(g),10)
            self.assertEqual(set(g['mode']),set(MODES))
            self.assertEqual(g.seed.nunique(),1)
        self.assertEqual(set(matrix.seed),set(range(7000,7010)))
        with self.assertRaises(ValueError):planned_runs(modes=('fixed','fixed'))

    def test_full_length_nrel_overlap_and_determinism(self):
        source=pd.Series(np.arange(8760,dtype=float))  # artificial hourly grid
        windows,meta=select_windows(source,1000,10,3600.,positional=True)
        again,again_meta=select_windows(source,1000,10,3600.,positional=True)
        self.assertEqual(meta,again_meta)
        self.assertEqual(len(windows),10)
        self.assertEqual(len({name for name,_ in windows}),10)
        self.assertEqual(meta['maximum_disjoint_windows'],8)
        self.assertEqual(meta['overlapping_pairs'],9)
        self.assertEqual(len(meta['pairwise_overlap']),45)
        self.assertEqual(meta['windows'][0]['start_position'],0)
        self.assertEqual(meta['windows'][-1]['end_position_exclusive'],8760)
        sets={}
        for (name,values),(other,repeat),record in zip(windows,again,meta['windows']):
            self.assertEqual(name,other)
            np.testing.assert_array_equal(values,repeat)
            self.assertEqual(len(values),1000)
            np.testing.assert_array_equal(values,source.iloc[record['start_position']:record['end_position_exclusive']])
            sets[name]=set(values)
        for pair in meta['pairwise_overlap']:
            count=len(sets[pair['window_a']] & sets[pair['window_b']])
            self.assertEqual(pair['overlap_samples'],count)
            self.assertEqual(pair['overlap_fraction'],count/1000.)
        self.assertEqual(sum(x['overlap_samples'] for x in meta['pairwise_overlap']),1240)
        json.dumps(meta)  # manifest is directly serializable

    def test_disjoint_windows_spread_over_available_range(self):
        source=pd.Series(np.zeros(12000),index=pd.date_range('2020-01-01',periods=12000,freq='min',tz='UTC'))
        windows,meta=select_windows(source,1000,10,60.)
        self.assertEqual(meta['selection_rule'],'spread_disjoint')
        self.assertEqual(meta['maximum_disjoint_windows'],12)
        self.assertEqual(meta['overlapping_pairs'],0)
        self.assertEqual(meta['windows'][-1]['end_position_exclusive'],12000)
        self.assertEqual(len(windows),10)
        self.assertTrue(all(len(x)==1000 and np.all(x==0.) for _,x in windows))

    def test_boundaries_missing_values_and_missing_timestamps(self):
        source=pd.Series(np.zeros(6),index=pd.date_range('2020-01-01',periods=6,freq='min'))
        windows,meta=select_windows(source,6,1,60.)
        self.assertEqual(len(windows[0][1]),6)
        self.assertEqual(meta['valid_starts'],1)
        for slots,count in ((7,1),(6,2),(0,1),(2,0),(2.5,1)):
            with self.assertRaises(ValueError):select_windows(source,slots,count,60.)
        for missing in (np.nan,np.inf,-np.inf):
            damaged=source.copy();damaged.iloc[3]=missing
            with self.assertRaises(ValueError):select_windows(damaged,6,1,60.)
        gapped=pd.Series(np.ones(12),index=pd.date_range('2020-01-01',periods=12,freq='min')).drop(pd.Timestamp('2020-01-01 00:06'))
        windows,meta=select_windows(gapped,4,2,60.)
        for record in meta['windows']:
            a=pd.Timestamp(record['start_timestamp']);b=pd.Timestamp(record['end_timestamp_exclusive'])
            self.assertEqual(b-a,pd.Timedelta(minutes=4))
        with self.assertRaises(ValueError):select_windows(gapped,7,1,60.)

    def test_arco_missing_minutes_are_not_nighttime_zeros(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'arco.csv'
            path.write_text('Date;Hour;PV sc Current\n01/01/2020;23:58:00;0\n01/01/2020;23:59:00;0\n02/01/2020;00:01:00;0\n')
            source=load_solar(path)
            self.assertEqual(source.iloc[0],0.)
            self.assertTrue(np.isnan(source.loc['2020-01-02 00:00']))
            with self.assertRaises(ValueError):select_windows(source,4,1,60.)

    def test_umass_daily_assembly_midnight_and_missing_panel(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'umass.tar.gz'
            origin=pd.Timestamp('2020-01-01 23:57',tz='UTC')
            with tarfile.open(path,'w:gz') as archive:
                for filename,minutes in (('second.csv',range(3,7)),('first.csv',range(3))):
                    data=''.join(f'{int((origin+pd.Timedelta(minutes=m)).timestamp())},0,0,0,0,{"" if m==5 else 0},3.3\n' for m in minutes).encode()
                    member=tarfile.TarInfo(filename);member.size=len(data);archive.addfile(member,io.BytesIO(data))
            source=load_umass(path)
            self.assertEqual(len(source),7)
            self.assertEqual(source.index.tz,origin.tz)
            self.assertTrue(np.isnan(source.iloc[5]))
            self.assertTrue((source.iloc[:5]==0.).all())
            windows,_=select_windows(source,5,1,60.)
            self.assertEqual(len(windows[0][1]),5)  # crosses midnight through both files
            with self.assertRaises(ValueError):select_windows(source,6,1,60.)

    def test_nrel_tmy_years_hour24_and_missing_hour(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'nrel.csv'
            path.write_text('ARTIFICIAL FIXTURE\nDate (MM/DD/YYYY),Time (HH:MM),GHI (W/m^2)\n01/31/1988,23:00,0\n01/31/1988,24:00,0\n02/01/1994,01:00,0\n02/01/1994,03:00,20\n')
            source=load_nrel(path)
            self.assertEqual(list(source.index),[742,743,744,745,746])
            self.assertTrue(np.isnan(source.loc[745]))
            windows,_=select_windows(source,3,1,3600.,positional=True)
            self.assertEqual(windows[0][0],'tmy_hour_index_742')
            with self.assertRaises(ValueError):select_windows(source,4,1,3600.,positional=True)

    def test_policy_order_resets_all_run_state_and_preserves_matching(self):
        cfg=Config(horizon=2);trace=make_trace(4,7000)
        fields=['queue_ids','queue_next_ids','attempted_ids','retry_numbers','received_ids','acknowledged_ids',
                'delivered_ids','E','E_next','gain','arrivals','harvest','energy','interval_end_s']
        first={mode:run(trace,cfg,mode) for mode in MODES}
        for mode in reversed(MODES):
            repeated=run(trace,cfg,mode)
            pd.testing.assert_frame_equal(first[mode][fields],repeated[fields])
            self.assertEqual(json.loads(repeated.queue_ids.iloc[0]),list(range(12)))
            self.assertEqual(repeated.E.iloc[0],7.)
            self.assertTrue(audit_packets(repeated,cfg))
            np.testing.assert_array_equal(repeated.arrivals,trace['arrival'])
            np.testing.assert_array_equal(repeated.gain,trace['gain'])
        self.assertNotEqual(first['fixed'].p.iloc[0],first['fixed_fraction'].p.iloc[0])


if __name__=='__main__':unittest.main()
