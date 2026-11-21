"""Independent replay of delay ledgers from slot IDs and virtual event times."""
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd

PACKET_FIELDS=('packet_id','is_initial','offered_time_s','admission_time_s','first_attempt_time_s',
               'first_ack_time_s','attempt_count','status','rejection_reason','initial_wait_s',
               'ack_completion_delay_s','outstanding_age_s','initial_wait_unfinished',
               'ack_completion_unfinished','observation_end_s')


def replay_packet_table(frame):
    frame=frame.sort_values('t');assert len(frame)>0
    np.testing.assert_array_equal(frame.t,np.arange(len(frame)))
    expected={};pending_ids=set()
    def offer(i,initial,offered,admitted,reason=None):
        assert i not in expected
        expected[i]=dict(packet_id=i,is_initial=initial,offered_time_s=offered,admission_time_s=admitted,
                         first_attempt_time_s=np.nan,first_ack_time_s=np.nan,attempt_count=0,
                         status='outstanding' if np.isfinite(admitted) else 'rejected_before_admission',
                         rejection_reason=reason)
        if np.isfinite(admitted):pending_ids.add(i)
    for i in json.loads(frame.iloc[0].queue_ids):offer(i,True,np.nan,0.)
    for r in frame.itertuples(index=False):
        for i in json.loads(r.attempted_ids):
            p=expected[i];assert p['status']=='outstanding' and p['admission_time_s']<=r.data_start_s
            if np.isnan(p['first_attempt_time_s']):p['first_attempt_time_s']=r.data_start_s
            p['attempt_count']+=1
        for i in json.loads(r.acknowledged_ids):
            p=expected[i];assert p['status']=='outstanding'
            assert p['admission_time_s']<=p['first_attempt_time_s']<=r.ack_end_s
            p['first_ack_time_s']=r.ack_end_s;p['status']='acknowledged'
            pending_ids.remove(i)
        overflow=set(json.loads(r.overflow_ids));proactive=set(json.loads(r.proactive_ids))
        for i in json.loads(r.arrival_ids):
            rejected=i in overflow or i in proactive
            offer(i,False,r.interval_end_s,np.nan if rejected else r.interval_end_s,
                  'overflow' if i in overflow else 'proactive' if i in proactive else None)
        assert pending_ids==set(json.loads(r.queue_next_ids))
    end=float(frame.interval_end_s.iloc[-1])
    for p in expected.values():
        admission=p['admission_time_s'];pending=p['status']=='outstanding'
        p.update(initial_wait_s=p['first_attempt_time_s']-admission,
                 ack_completion_delay_s=p['first_ack_time_s']-admission,
                 outstanding_age_s=end-admission if pending else np.nan,
                 initial_wait_unfinished=pending and np.isnan(p['first_attempt_time_s']),
                 ack_completion_unfinished=pending,observation_end_s=end)
    return pd.DataFrame(list(expected.values()),columns=PACKET_FIELDS).sort_values('packet_id')


def audit_packet_ledger(frame,packets,summary=None):
    frame=frame.sort_values('t')
    want=replay_packet_table(frame)
    assert not packets.packet_id.duplicated().any()
    assert set(packets.packet_id)==set(want.packet_id)
    got=packets.sort_values('packet_id')
    for name in want.columns:
        assert name in got
        if name in ('status','rejection_reason'):
            np.testing.assert_array_equal(got[name].astype(object).fillna('').to_numpy(),want[name].astype(object).fillna('').to_numpy(),err_msg=name)
        else:
            np.testing.assert_allclose(pd.to_numeric(got[name]).to_numpy(dtype=float),
                                       pd.to_numeric(want[name]).to_numpy(dtype=float),rtol=1e-12,atol=1e-9,equal_nan=True,err_msg=name)
    if summary is not None:
        new=want[(want.is_initial==False)&want.admission_time_s.notna()]
        initial=want[want.is_initial==True];pending=want[want.status=='outstanding']
        stats=dict(newly_admitted_packets=len(new),newly_attempted_packets=int(new.first_attempt_time_s.notna().sum()),
                   newly_acknowledged_packets=int(new.first_ack_time_s.notna().sum()),outstanding_packets=len(pending),
                   newly_outstanding_packets=int((new.status=='outstanding').sum()),
                   admitted_never_attempted_packets=int((want.admission_time_s.notna()&want.first_attempt_time_s.isna()).sum()),
                   rejected_arrivals=int((want.status=='rejected_before_admission').sum()),
                   initial_packets=len(initial),initial_attempted_packets=int(initial.first_attempt_time_s.notna().sum()),
                   initial_acknowledged_packets=int(initial.first_ack_time_s.notna().sum()),
                   initial_outstanding_packets=int((initial.status=='outstanding').sum()),
                   initial_never_attempted_packets=int(initial.first_attempt_time_s.isna().sum()),
                   newly_never_attempted_packets=int(new.first_attempt_time_s.isna().sum()))
        for name,prefix in (('initial_wait_s','initial_wait'),('ack_completion_delay_s','ack_completion_delay')):
            observed=np.asarray(new[name].dropna(),float)
            stats['mean_'+prefix+'_s']=float(np.mean(observed)) if len(observed) else np.nan
            stats['median_'+prefix+'_s']=float(np.median(observed)) if len(observed) else np.nan
            stats[prefix+'_samples']=len(observed)
            stats[prefix+'_unfinished_packets']=len(new)-len(observed)
        for cohort,prefix in ((pending,'outstanding'),(new[new.status=='outstanding'],'new_outstanding')):
            ages=np.asarray(cohort.outstanding_age_s,float)
            for label,fn in (('mean',np.mean),('median',np.median),('max',np.max)):
                stats[label+'_'+prefix+'_age_s']=float(fn(ages)) if len(ages) else np.nan
        for name,value in stats.items():
            assert name in summary, f'missing delay summary {name}'
            np.testing.assert_allclose(summary[name],value,rtol=1e-10,atol=1e-9,equal_nan=True,err_msg=name)
        assert len(want)==len(initial)+int(frame.arrivals.sum())
        assert len(pending)==int(frame.b_next.iloc[-1])
        assert int((want.status=='acknowledged').sum())==int(frame.acknowledged.sum())
    return True


def audit_packet_outputs(directory,slots,runs):
    """Stream appended packet runs, bounding memory independently of study size."""
    path=Path(directory)/'per_packet.csv'
    assert 'run_id' in runs and 'run_id' in slots
    assert not runs.run_id.duplicated().any()
    metadata=runs.set_index('run_id');slot_groups=slots.groupby('run_id',sort=False)
    assert set(slot_groups.groups)==set(metadata.index)
    seen=set();carry=None
    def check(group):
        if group.empty:return
        run_id=group.run_id.iloc[0];assert run_id in metadata.index and run_id not in seen
        row=metadata.loc[run_id];trajectory=slot_groups.get_group(run_id)
        identity={}
        for key in group.columns:
            if key in PACKET_FIELDS or key=='run_id':continue
            assert group[key].nunique(dropna=False)==1, f'inconsistent packet metadata: {key}'
            value=group[key].iloc[0]
            identity[key]=value.item() if isinstance(value,np.generic) else value
            if key in row.index:assert value==row[key],key
            if key in trajectory:assert (trajectory[key]==value).all(),key
        digest=hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        assert digest==run_id, 'packet metadata does not match run_id'
        audit_packet_ledger(trajectory,group,row);seen.add(run_id)
    # Round-trip metadata floats exactly: they contribute to the stored run ID.
    with pd.read_csv(path,chunksize=100000,float_precision='round_trip') as reader:
        for chunk in reader:
            if carry is not None:chunk=pd.concat([carry,chunk],ignore_index=True)
            last=chunk.run_id.iloc[-1] if len(chunk) else None
            for run_id,group in chunk.groupby('run_id',sort=False):
                if run_id!=last:check(group)
            carry=chunk[chunk.run_id==last].copy() if last is not None else None
    if carry is not None:check(carry)
    for run_id in set(metadata.index)-seen:
        trajectory=slot_groups.get_group(run_id)
        assert trajectory.b.iloc[0]==0 and trajectory.arrivals.sum()==0
        audit_packet_ledger(trajectory,pd.read_csv(path,nrows=0),metadata.loc[run_id])
    return True
