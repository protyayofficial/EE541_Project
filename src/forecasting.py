"""Past-only forecasts shared by both online simulators."""
import numpy as np
from .channel import ChannelModel,conditional_means,_positive_exp

ARRIVAL_MIN = 0
ARRIVAL_MAX = 10
ARRIVAL_MEAN = 5.0
ARRIVAL_MODEL = dict(distribution='discrete_uniform', support=list(range(ARRIVAL_MIN,ARRIVAL_MAX+1)),
                     probabilities=[1./11]*11, mean=ARRIVAL_MEAN)


def bound_arrivals(values):
    """Clamp predictions to known support; actual custom traces are unchanged."""
    return np.clip(values, ARRIVAL_MIN, ARRIVAL_MAX)


def raw_forecasts(history,gain,horizon,*,t=None,model=ChannelModel()):
    """Conditional mean from current/past reports at their actual interval times."""
    pa=np.asarray(history['arrival'],float);ph=np.asarray(history['harvest'],float)
    if t is None:t=len(pa)
    if not np.isnan(gain) and not np.isfinite(gain):raise ValueError('invalid observed channel gain')
    if np.isfinite(gain):
        g=conditional_means(gain,np.arange(horizon),model)
    elif history['gain']:
        times=history.get('gain_times',list(range(len(history['gain']))))
        if len(times)!=len(history['gain']):raise ValueError('channel observations need matching times')
        gap=t-times[-1]
        if gap<=0:raise ValueError('past channel observation must precede current interval')
        g=conditional_means(history['gain'][-1],gap+np.arange(horizon),model)
    elif model.mean_normalize:
        g=np.ones(horizon)
    else:
        leads=t+1+np.arange(horizon)  # Zero initial log state at t=-1.
        g=_positive_exp(.5*model.variance*(1-model.rho**(2*leads)))
    a=np.full(horizon,bound_arrivals((8*ARRIVAL_MEAN+pa.sum())/(8+len(pa))))
    # Same causal predictor for all optimization variants.
    hmean=float(np.mean(ph[-12:])) if len(ph)>=3 else float((8.8+ph.sum())/(8+len(ph)))
    return g,a,np.full(horizon,hmean)

