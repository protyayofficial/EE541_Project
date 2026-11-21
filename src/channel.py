"""Correlated lognormal effective SNR per watt; one held gain per interval."""
from dataclasses import dataclass
import numpy as np

CHANNEL_MODEL_VERSION = 'correlated-lognormal-v1'
GAIN_FLOOR = 1e-9  # Planning margins only; never floor/cap generated or reported gains.
CHANNEL_THRESHOLD = .8  # Preserve the latest numerical baseline threshold.


@dataclass(frozen=True)
class ChannelModel:
    rho: float = .68
    sigma: float = .45
    mean_normalize: bool = True

    def __post_init__(self):
        if not np.isfinite(self.rho) or not 0 <= self.rho < 1:
            raise ValueError('channel rho must be finite and in [0,1)')
        if not np.isfinite(self.sigma) or self.sigma < 0:
            raise ValueError('channel sigma must be finite and nonnegative')
        if not isinstance(self.mean_normalize,(bool,np.bool_)):
            raise ValueError('channel mean_normalize must be boolean')
        try:variance=self.variance
        except OverflowError as exc:raise ValueError('channel log variance must be finite') from exc
        if not np.isfinite(variance):raise ValueError('channel log variance must be finite')

    @property
    def variance(self):return self.sigma**2/(1-self.rho**2)

    @property
    def center(self):return .5*self.variance if self.mean_normalize else 0.

    def settings(self):
        return dict(version=CHANNEL_MODEL_VERSION,distribution='correlated_lognormal',rho=self.rho,
                    sigma=self.sigma,mean_normalize=bool(self.mean_normalize),stationary_log_variance=self.variance,
                    initialization='stationary_normal' if self.mean_normalize else 'zero_log_state',
                    units='effective SNR per watt (1/W), not RSSI',feedback='accurate_numerical_gain',
                    random_stream='default_rng(SeedSequence([scenario_seed,42017])); independent of traffic/harvest/actions',
                    planning_gain_floor=GAIN_FLOOR)


def valid_gain(gain):
    gain=float(gain)
    if not np.isfinite(gain) or gain<=0:raise ValueError('channel gain must be positive and finite')
    return gain


def _positive_exp(values):
    try:
        with np.errstate(over='raise',under='ignore',invalid='raise'):
            result=np.exp(values)
    except FloatingPointError as exc:
        raise ValueError('channel exponent cannot be represented as a positive finite gain') from exc
    if np.any(~np.isfinite(result)) or np.any(result<=0):raise ValueError('invalid exponential channel gain')
    return result


def channel_sequence(n,seed,model=ChannelModel()):
    if not isinstance(n,(int,np.integer)) or n<0:raise ValueError('channel length must be a nonnegative integer')
    rng=np.random.default_rng(np.random.SeedSequence([int(seed),42017]))
    state=float(rng.normal(0,np.sqrt(model.variance))) if model.mean_normalize else 0.
    logs=np.empty(n)
    for t in range(n):
        state=model.rho*state+rng.normal(0,model.sigma)
        logs[t]=state-model.center
    return _positive_exp(logs)


def conditional_means(gain,leads,model=ChannelModel()):
    gain=valid_gain(gain);leads=np.asarray(leads)
    if np.any(~np.isfinite(leads)) or np.any(leads<0) or np.any(leads!=np.floor(leads)):
        raise ValueError('forecast leads must be nonnegative integers')
    r=model.rho**leads
    result=_positive_exp(r*(np.log(gain)+model.center)+.5*model.variance*(1-r*r)-model.center)
    return np.where(leads==0,gain,result)


def gain_at(trace,t):return valid_gain(trace['gain'][t])


def validate_trace_model(trace,cfg):
    for name in ('channel_rho','channel_sigma','channel_mean_normalize'):
        if name in trace and trace[name]!=getattr(cfg,name):
            raise ValueError(f'trace and controller disagree on {name}')


def condition_at(trace,t):
    """Optional descriptive label only; never used to obtain a gain."""
    return str(trace['condition'][t]) if 'condition' in trace else 'continuous'


def bound_gain(values):
    """A positive numerical floor for adjusted future planning inputs only."""
    values=np.asarray(values,dtype=float)
    if np.any(~np.isfinite(values)):raise ValueError('planning gain must be finite')
    return np.maximum(GAIN_FLOOR,values)
