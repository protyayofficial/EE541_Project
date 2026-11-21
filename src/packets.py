"""Observational packet ledger and run-level delay statistics (virtual seconds).

No scheduling inputs, random draws, or per-packet serialization within a burst.
"""
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import t as student_t

DELAY_MODEL='virtual-packet-delays-v1'
PACKET_COLUMNS=('packet_id','is_initial','offered_time_s','admission_time_s',
                'first_attempt_time_s','first_ack_time_s','attempt_count','status',
                'rejection_reason','initial_wait_s','ack_completion_delay_s',
                'outstanding_age_s','initial_wait_unfinished','ack_completion_unfinished',
                'observation_end_s')
DELAY_MEASURES=('mean_initial_wait_s','median_initial_wait_s',
                'mean_ack_completion_delay_s','median_ack_completion_delay_s')


class PacketLedger:
    def __init__(self,initial):
        self.records={i:self._record(i,True,None,0.) for i in range(initial)}

    @staticmethod
    def _record(packet_id,initial,offered,admission,reason=None):
        return dict(packet_id=packet_id,is_initial=initial,offered_time_s=offered,
                    admission_time_s=admission,first_attempt_time_s=None,first_ack_time_s=None,
                    attempt_count=0,status='outstanding' if admission is not None else 'rejected_before_admission',
                    rejection_reason=reason)

    def attempts(self,ids,time_s):
        for packet_id in ids:
            record=self.records[packet_id]
            assert record['status']=='outstanding' and time_s>=record['admission_time_s']
            if record['first_attempt_time_s'] is None:record['first_attempt_time_s']=float(time_s)
            record['attempt_count']+=1

    def acknowledge(self,ids,time_s):
        for packet_id in ids:
            record=self.records[packet_id]
            if record['first_ack_time_s'] is not None:continue
            assert record['first_attempt_time_s'] is not None and time_s>=record['first_attempt_time_s']
            record['first_ack_time_s']=float(time_s);record['status']='acknowledged'

    def arrive(self,ids,overflow,proactive,time_s):
        rejected={i:'overflow' for i in overflow}|{i:'proactive' for i in proactive}
        for packet_id in ids:
            assert packet_id not in self.records
            reason=rejected.get(packet_id)
            self.records[packet_id]=self._record(packet_id,False,float(time_s),
                                                 None if reason else float(time_s),reason)

    def snapshot(self,end_s):
        result=[]
        for record in self.records.values():
            r=record.copy();admission=r['admission_time_s'];attempt=r['first_attempt_time_s'];ack=r['first_ack_time_s']
            r.update(initial_wait_s=None if attempt is None else attempt-admission,
                     ack_completion_delay_s=None if ack is None else ack-admission,
                     outstanding_age_s=float(end_s)-admission if r['status']=='outstanding' else None,
                     initial_wait_unfinished=r['status']=='outstanding' and attempt is None,
                     ack_completion_unfinished=r['status']=='outstanding',observation_end_s=float(end_s))
            result.append(r)
        return result


def attach_packet_ledger(frame,radio):
    """Keep the existing slot-DataFrame API; serializable attrs survive copies."""
    frame.attrs['packet_ledger']=radio.queue.ledger.snapshot(radio.now_s)
    frame.attrs['packet_run']=dict(mode=str(frame['mode'].iloc[0]) if len(frame) else '',
        seed=radio.receiver.seed,slot_seconds=radio.cfg.slot_seconds,horizon=radio.cfg.horizon,
        data_max=radio.cfg.data_max,channel_rho=radio.cfg.channel_rho,
        channel_sigma=radio.cfg.channel_sigma,mean_normalize=radio.cfg.channel_mean_normalize,
        episode_slots=len(frame),initial_queue=int(frame.b.iloc[0]) if len(frame) else len(radio.queue.ids),
        initial_energy=float(frame.E.iloc[0]) if len(frame) else 0.,
        config_id=hashlib.sha256(json.dumps(asdict(radio.cfg),sort_keys=True).encode()).hexdigest())
    return frame


def packet_table(frame):
    if 'packet_ledger' not in frame.attrs:
        from .packet_audit import replay_packet_table
        return replay_packet_table(frame)
    return pd.DataFrame.from_records(frame.attrs['packet_ledger'],columns=PACKET_COLUMNS)


def delay_metrics(packets):
    """Primary means are completed observations among non-initial admissions."""
    new=packets[(~packets.is_initial.astype(bool)) & packets.admission_time_s.notna()]
    outstanding=packets[packets.status=='outstanding'];initial=packets[packets.is_initial.astype(bool)]
    result=dict(newly_admitted_packets=len(new),newly_attempted_packets=int(new.first_attempt_time_s.notna().sum()),
                newly_acknowledged_packets=int(new.first_ack_time_s.notna().sum()),
                outstanding_packets=len(outstanding),newly_outstanding_packets=int((new.status=='outstanding').sum()),
                admitted_never_attempted_packets=int((packets.admission_time_s.notna() & packets.first_attempt_time_s.isna()).sum()),
                rejected_arrivals=int((packets.status=='rejected_before_admission').sum()),
                initial_packets=len(initial),initial_attempted_packets=int(initial.first_attempt_time_s.notna().sum()),
                initial_acknowledged_packets=int(initial.first_ack_time_s.notna().sum()),
                initial_outstanding_packets=int((initial.status=='outstanding').sum()),
                initial_never_attempted_packets=int(initial.first_attempt_time_s.isna().sum()),
                newly_never_attempted_packets=int(new.first_attempt_time_s.isna().sum()))
    for column,prefix in (('initial_wait_s','initial_wait'),('ack_completion_delay_s','ack_completion_delay')):
        values=pd.to_numeric(new[column].dropna(),errors='raise')
        result['mean_'+prefix+'_s']=float(values.mean()) if len(values) else np.nan
        result['median_'+prefix+'_s']=float(values.median()) if len(values) else np.nan
        result[prefix+'_samples']=len(values)
        result[prefix+'_unfinished_packets']=int(new[column].isna().sum())
    for cohort,prefix in ((outstanding,'outstanding'),(new[new.status=='outstanding'],'new_outstanding')):
        values=pd.to_numeric(cohort.outstanding_age_s,errors='raise')
        for stat in ('mean','median','max'):
            result[stat+'_'+prefix+'_age_s']=float(getattr(values,stat)()) if len(values) else np.nan
    return result


def run_delay_metrics(frame):return delay_metrics(packet_table(frame))


def paired_stats(values):
    """Run-level paired differences; no eligible pairs or n<2 CI => missing."""
    values=pd.Series(values).dropna();n=len(values)
    mean=float(values.mean()) if n else np.nan
    half=float(student_t.ppf(.975,n-1)*values.std(ddof=1)/np.sqrt(n)) if n>=2 else np.nan
    return dict(n=n,n_valid_pairs=n,delta=mean,ci_low=mean-half,ci_high=mean+half)


def append_packet_run(frame,directory,identifiers):
    """Append one finished run once, with stable full scenario identifiers."""
    identity=frame.attrs['packet_run']|identifiers
    run_id=hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    packets=packet_table(frame).assign(**identity,run_id=run_id)
    path=Path(directory)/'per_packet.csv'
    packets.to_csv(path,mode='a',header=not path.exists(),index=False)
    return run_id
