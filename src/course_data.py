"""Offline solar-proxy dataset readers for the EE541 course project."""
import tarfile
import numpy as np
import pandas as pd

SOURCE_INTERVALS={'arco':60.,'umass_home_c':60.,'nrel_tmy3':3600.}
SOURCE_FILES={'arco':'data/arco/dataset.csv','umass_home_c':'data/umass/homeC-generation.tar.gz',
              'nrel_tmy3':'data/nrel/723170TYA.CSV'}
SOURCE_SCALES={'arco':.01,'umass_home_c':.1,'nrel_tmy3':.005}
SOURCE_SHA256={'arco':'9c9d66ef8d9d6507623186067d8f7e3e06dc1029c9e2f2f02f4e55a32418e2a8',
               'umass_home_c':'f47cca12cfe82a95a427142757f82e033a722dcf49a12d6f20ecf31fc8453454',
               'nrel_tmy3':'1e96f84638ce98e6b29002bc45a27aa69bb29b0ed0368d3b52b7b1f81610c6c9'}
WINDOW_SELECTION='consecutive-valid-v1'


def load_solar(path):
    raw=pd.read_csv(path,sep=';',decimal=',',encoding='utf-8-sig')
    dt=pd.to_datetime(raw['Date']+' '+raw['Hour'],format='%d/%m/%Y %H:%M:%S',errors='coerce')
    vals=pd.to_numeric(raw['PV sc Current'],errors='coerce').replace([np.inf,-np.inf],np.nan).clip(lower=0)
    return pd.Series(vals.to_numpy(),index=dt).loc[dt.notna().to_numpy()].sort_index().resample('1min').mean()


def load_umass(path):
    """Assemble daily files on their UTC minute grid, preserving missing data.

    Sum/count aggregation before combining files bounds memory for second-level
    source data and correctly weights partial minutes split across files.
    A row needs all three panel readings. Missing rows/panels are never zero-filled.
    """
    pieces=[]
    with tarfile.open(path,'r:gz') as tar:
        for member in sorted(tar.getmembers(),key=lambda x:x.name):
            if not member.isfile() or not member.name.endswith('.csv'):continue
            raw=pd.read_csv(tar.extractfile(member),header=None,usecols=[0,3,4,5],names=['t','p1','p2','p3'])
            stamps=pd.to_datetime(pd.to_numeric(raw.t,errors='coerce'),unit='s',utc=True,errors='coerce')
            panels=raw[['p1','p2','p3']].apply(pd.to_numeric,errors='coerce').replace([np.inf,-np.inf],np.nan).clip(lower=0)
            values=pd.Series(panels.sum(axis=1,min_count=3).to_numpy(),index=stamps)
            values=values.loc[stamps.notna().to_numpy()].sort_index()
            if len(values):pieces.append(values.resample('1min').agg(['sum','count']))
    if not pieces:raise ValueError('UMass archive contains no timestamped panel readings')
    totals=pd.concat(pieces).groupby(level=0).sum()
    return (totals['sum']/totals['count']).resample('1min').asfreq()


def load_nrel(path):
    """Hourly TMY order, not a chronological year; missing hours stay missing.

    Normalize month/day/hour onto a non-leap template, ignoring stitched source
    years. Index 0 is Jan 1 01:00 (hour-ending convention). Minimal deterministic
    test fixtures without date/time columns use their explicit row positions.
    """
    raw=pd.read_csv(path,skiprows=1)
    values=pd.to_numeric(raw['GHI (W/m^2)'],errors='coerce').replace([np.inf,-np.inf],np.nan).clip(lower=0)
    if not len(raw):raise ValueError('NREL contains no hourly samples')
    if 'Date (MM/DD/YYYY)' not in raw or 'Time (HH:MM)' not in raw:
        return pd.Series(values.to_numpy(),index=pd.RangeIndex(len(values)))
    date=raw['Date (MM/DD/YYYY)'].astype(str).str.replace(r'\d{4}$','2001',regex=True)
    days=pd.to_datetime(date,format='%m/%d/%Y',errors='coerce')
    hours=pd.to_timedelta(raw['Time (HH:MM)'].astype(str)+':00',errors='coerce')
    if days.isna().any() or hours.isna().any() or (hours<pd.Timedelta(0)).any() or (hours>pd.Timedelta(days=1)).any():
        raise ValueError('NREL contains invalid TMY date/hour labels')
    index=((days+hours-pd.Timestamp('2001-01-01 01:00'))/pd.Timedelta(hours=1)).to_numpy()
    if np.any(index!=np.floor(index)) or np.any(np.diff(index)<=0):
        raise ValueError('NREL TMY hour labels must increase on the hourly template')
    index=index.astype(int)
    return pd.Series(values.to_numpy(),index=index).reindex(pd.RangeIndex(index[0],index[-1]+1))


def select_windows(series,slots,count,seconds,*,positional=False):
    """Select distinct full windows without filling, tiling or resampling values.

    Prefer spread-out members of an earliest-finish maximum disjoint set. If
    that set is too small, use equally spaced ranks of all valid starts.
    """
    if any(not isinstance(x,(int,np.integer)) or x<1 for x in (slots,count)):
        raise ValueError('slots and window count must be positive integers')
    if not np.isfinite(seconds) or seconds<=0:raise ValueError('source interval must be positive')
    if not series.index.is_unique or not series.index.is_monotonic_increasing:
        raise ValueError('source timestamps/positions must be sorted and unique')
    values=series.to_numpy(dtype=float);n=len(values)
    if n<slots:raise ValueError(f'{n} source samples cannot supply a {slots}-slot window')
    if not positional and not isinstance(series.index,pd.DatetimeIndex):
        raise ValueError('timestamped sources require a DatetimeIndex')
    delta=np.diff(series.index.to_numpy() if positional else series.index.as_unit('ns').asi8)
    step=1 if positional else int(seconds*1e9)
    broken=np.r_[False,delta!=step]
    invalid=np.r_[0,np.cumsum(~np.isfinite(values))]
    gaps=np.r_[0,np.cumsum(broken)]
    starts=np.arange(n-slots+1)
    valid=starts[(invalid[starts+slots]==invalid[starts]) & (gaps[starts+slots]==gaps[starts+1])]
    disjoint=[];end=-1
    for start in valid:
        if start>=end:disjoint.append(int(start));end=int(start)+slots
    if len(valid)<count:
        raise ValueError(f'only {len(valid)} valid distinct starts for {count} windows of {slots} slots')
    pool=disjoint if len(disjoint)>=count else valid
    selected=np.asarray(pool)[np.linspace(0,len(pool)-1,count,dtype=int)]
    windows=[];records=[]
    for j,start in enumerate(selected):
        start=int(start);stop=start+slots
        label=f'tmy_hour_index_{series.index[start]}' if positional else str(series.index[start])
        windows.append((label,values[start:stop].copy()))
        records.append(dict(window=label,scenario_index=j,seed=7000+j,start_position=start,
                            end_position_exclusive=stop,length=slots,
                            source_start=str(series.index[start]),source_last=str(series.index[stop-1]),
                            start_timestamp=None if positional else str(series.index[start]),
                            end_timestamp_exclusive=None if positional else str(series.index[stop-1]+pd.Timedelta(seconds=seconds))))
    overlaps=[]
    for i,a in enumerate(records):
        for b in records[i+1:]:
            shared=max(0,min(a['end_position_exclusive'],b['end_position_exclusive'])-max(a['start_position'],b['start_position']))
            overlaps.append(dict(window_a=a['window'],window_b=b['window'],overlap_samples=shared,
                                 overlap_fraction=shared/slots))
    metadata=dict(selection_version=WINDOW_SELECTION,source_samples=n,valid_samples=int(np.isfinite(values).sum()),
                  valid_starts=len(valid),maximum_disjoint_windows=len(disjoint),
                  selection_rule='spread_disjoint' if len(disjoint)>=count else 'spread_valid_starts_overlap_required',
                  slot_seconds=seconds,windows=records,pairwise_overlap=overlaps,
                  overlapping_pairs=sum(x['overlap_samples']>0 for x in overlaps),
                  position_definition='loaded source grid; absent timestamps/hours remain missing; end positions exclusive',
                  dependence='shared observations and common source/season; windows are not independent solar records')
    return windows,metadata


def evaluation_sources(slots,count):
    """Final solar study only; older source/window experiments keep their lengths."""
    for name,loader in (('arco',load_solar),('umass_home_c',load_umass),('nrel_tmy3',load_nrel)):
        series=loader(SOURCE_FILES[name])
        try:
            windows,metadata=select_windows(series,slots,count,SOURCE_INTERVALS[name],positional=name=='nrel_tmy3')
        except ValueError as exc:
            raise ValueError(f'{name}: {exc}') from exc
        windows=[(label,values*SOURCE_SCALES[name]) for label,values in windows]
        metadata['energy_conversion_factor']=SOURCE_SCALES[name]
        if name=='nrel_tmy3':metadata['time_basis']='TMY hourly template; stitched months, not a chronological year'
        yield name,SOURCE_INTERVALS[name],windows,metadata
