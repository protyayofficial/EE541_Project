import unittest
from dataclasses import replace
import numpy as np
from src.scheduling import Config
from src.experiment import make_trace,run_policy
from research_experiments import causal_forecasts

class ResearchTests(unittest.TestCase):
    def test_causal_forecast_ignores_future(self):
        x=make_trace(25,seed=31)
        y={k:v.copy() for k,v in x.items()}
        y['arrival'][18:]+=100
        a=causal_forecasts(x,21)
        b=causal_forecasts(y,21)
        self.assertTrue(np.allclose(a['forecast_arrival'][:19],b['forecast_arrival'][:19]))
    def test_no_proactive_drops_mode(self):
        cfg=replace(Config(),horizon=4)
        trace=causal_forecasts(make_trace(12,seed=19),21)
        df=run_policy(trace,'adaptive_risk',cfg,'lp',allow_proactive=False)
        self.assertTrue((df.proactive==0).all())
        self.assertTrue((df['drop']<=df.arrivals+1e-8).all())
        self.assertTrue((df.b<=cfg.buffer_max+1e-8).all())

if __name__=='__main__':unittest.main()
