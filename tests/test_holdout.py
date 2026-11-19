import unittest
from pathlib import Path
from guard_proposal import windows_for
from tune_proposal import study_windows
from robust_selection_study import windows_for as minimax_windows
from consistency_study import fresh_windows
import pandas as pd

class HoldoutTests(unittest.TestCase):
    @unittest.skipUnless(Path('results/proposal_minimax/per_window.csv').is_file() and all(Path(f).is_file() for f in ('data/arco/dataset.csv','data/umass/homeC-generation.tar.gz','data/nrel/723170TYA.CSV')), 'earlier results or datasets unavailable')
    def test_consistency_windows_exclude_previous_experiments(self):
        prior=[pd.read_csv(f) for f in ('results/proposal_final/per_window.csv','results/proposal_tuned/per_window.csv','results/proposal_guarded/per_window.csv','results/proposal_minimax/per_window.csv')]
        for name,_,new in fresh_windows(60):
            previous=set().union(*(set(frame[frame.dataset==name].window) for frame in prior))
            self.assertFalse(previous.intersection(w for w,_ in new),name)
            self.assertEqual(len(new),4)

    @unittest.skipUnless(Path('results/proposal_guarded/per_window.csv').is_file() and all(Path(f).is_file() for f in ('data/arco/dataset.csv','data/umass/homeC-generation.tar.gz','data/nrel/723170TYA.CSV')), 'earlier results or datasets unavailable')
    def test_minimax_test_windows_exclude_all_previous_comparisons(self):
        prior=[pd.read_csv(f) for f in ('results/proposal_final/per_window.csv','results/proposal_tuned/per_window.csv','results/proposal_guarded/per_window.csv')]
        for name,_,dev,new in minimax_windows(60):
            previous=set().union(*(set(frame[frame.dataset==name].window) for frame in prior))
            self.assertFalse(previous.intersection(w for w,_ in new),name)
            self.assertFalse(set(w for w,_ in dev).intersection(w for w,_ in new))
            self.assertEqual(len(new),4)

    @unittest.skipUnless(all(Path(f).is_file() for f in ('data/arco/dataset.csv','data/umass/homeC-generation.tar.gz','data/nrel/723170TYA.CSV')), 'datasets not downloaded')
    def test_guard_windows_are_disjoint_from_previous_study(self):
        previous={name:set(w for w,_ in test) for name,_,_,test in study_windows(60)}
        for name,_,dev,new in windows_for(60):
            self.assertEqual(len(dev),6);self.assertEqual(len(new),4)
            self.assertFalse(previous[name].intersection(w for w,_ in new))
            self.assertFalse(set(w for w,_ in dev).intersection(w for w,_ in new))
if __name__=='__main__':unittest.main()
