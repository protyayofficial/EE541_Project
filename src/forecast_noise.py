"""Keyed standard normals for controlled future-channel forecast sensitivity.

Independent of radio/traffic RNGs. Policy, perturbation amplitude and observed
probe count are deliberately absent from the key.
"""
import hashlib
import json
import math
import numpy as np

NOISE_MODEL='channel-forecast-lognormal-v1'


def standard_normal(scenario,origin,lead):
    if origin<0 or int(origin)!=origin or lead<1 or int(lead)!=lead:
        raise ValueError('forecast origin/lead must be nonnegative/positive integers')
    key=json.dumps([NOISE_MODEL,str(scenario),int(origin),int(lead)],separators=(',',':')).encode()
    digest=hashlib.blake2b(key,digest_size=16).digest()
    u=[((int.from_bytes(digest[i:i+8],'big')>>11)+.5)/2**53 for i in (0,8)]
    return math.sqrt(-2*math.log(u[0]))*math.cos(2*math.pi*u[1])


def perturb_channel(base,amplitude,scenario,origin):
    if not np.isfinite(amplitude) or amplitude<0:
        raise ValueError('forecast perturbation must be finite and nonnegative')
    base=np.asarray(base,float)
    z=np.array([0.]+[standard_normal(scenario,origin,k) for k in range(1,len(base))])
    multiplier=np.ones(len(base))
    with np.errstate(over='raise',invalid='raise',under='ignore'):
        if amplitude:multiplier[1:]=np.exp(amplitude*z[1:]-.5*amplitude**2)
        result=base.copy() if not amplitude else base*multiplier
    if np.any(~np.isfinite(result)) or np.any(result<=0):
        raise ValueError('perturbed forecasts must remain positive and finite')
    return result,z,multiplier
