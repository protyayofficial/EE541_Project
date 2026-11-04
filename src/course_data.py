"""Offline solar-proxy dataset readers for the EE541 course project."""
import tarfile
import numpy as np
import pandas as pd


def load_solar(path):
    raw=pd.read_csv(path,sep=';',decimal=',',encoding='utf-8-sig')
    dt=pd.to_datetime(raw['Date']+' '+raw['Hour'],format='%d/%m/%Y %H:%M:%S',errors='coerce')
    vals=pd.to_numeric(raw['PV sc Current'],errors='coerce').clip(lower=0)
    return pd.Series(vals.to_numpy(),index=dt).dropna().resample('1min').mean()

def sources(slots,windows):
    ar=load_solar('data/arco/dataset.csv');out=[]
    for j,day in enumerate(pd.date_range('2018-09-12','2018-10-03',freq='D')):
        start=day+pd.Timedelta(hours=[8,12,17,21][j%4]);part=ar.reindex(pd.date_range(start,periods=slots,freq='min'))
        if part.notna().all():out.append((str(start),part.to_numpy()*.01))
    yield 'arco',60.,out[:windows]
    # UMass Home C: format explicitly lists three panel currents in mA, timestamp UTC.
    items=[]
    with tarfile.open('data/umass/homeC-generation.tar.gz','r:gz') as tar:
        for f in tar.getmembers():
            if not f.name.endswith('.csv'):continue
            raw=pd.read_csv(tar.extractfile(f),header=None,usecols=[0,3,4,5],names=['t','p1','p2','p3'])
            raw['t']=pd.to_datetime(raw.t,unit='s',utc=True)
            arr=raw.set_index('t')[['p1','p2','p3']].apply(pd.to_numeric,errors='coerce').clip(lower=0).sum(axis=1,min_count=3).resample('1min').mean()
            if len(arr)<slots:continue
            date=arr.index[0].normalize();items.append((date,arr))
    items.sort(key=lambda x:x[0]);u=[]
    for j,(date,series) in enumerate(items):
        start=date+pd.Timedelta(hours=[8,12,17,21][j%4]);a=series.reindex(pd.date_range(start,periods=slots,freq='min'))
        if a.notna().all():u.append((str(start),a.to_numpy()*.1))
        if len(u)>=windows:break
    yield 'umass_home_c',60.,u
    # TMY3 is an artificially stitched representative year, not a chronological year.
    z=pd.read_csv('data/nrel/723170TYA.CSV',skiprows=1);v=pd.to_numeric(z['GHI (W/m^2)'],errors='coerce').clip(lower=0).to_numpy()
    # Hourly resolution: windows use distinct, nonoverlapping days in April.
    n=[]; start_idx=24*90
    for i in range(windows):
        ix=start_idx+i*max(slots,72);x=v[ix:ix+slots]
        if len(x)==slots and np.isfinite(x).all():n.append((f'tmy_hour_index_{ix}',x*.005))
    yield 'nrel_tmy3',3600.,n
