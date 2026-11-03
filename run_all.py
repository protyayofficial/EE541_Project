#!/usr/bin/env python3
"""Run all EE541 experiments and save complete artifacts, logs, and a review ZIP.

Examples:
 python run_all.py --mode smoke
 python run_all.py --mode full
 python run_all.py --mode full --seeds 3 --slots 60

WARNING: --clean deletes the results directory only after verifying the project root.
"""
import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent
REQUIRED=('src/scheduling.py','research_experiments.py','solver_accuracy.py','run_experiments.py')


def execute(name,args,results):
    folder=results/name
    folder.mkdir(parents=True,exist_ok=True)
    print('\n===',name,'===',flush=True)
    start=time.time()
    with (folder/'run.log').open('w') as log:
        proc=subprocess.Popen([sys.executable,*args],cwd=ROOT,
              stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
              text=True,bufsize=1)
        for line in proc.stdout:
            print(line,end='',flush=True)
            log.write(line)
        code=proc.wait()
    elapsed=time.time()-start
    record={'name':name,'command':[sys.executable,*args],
            'return_code':code,'duration_seconds':round(elapsed,3)}
    (folder/'run_status.json').write_text(json.dumps(record,indent=2))
    if code:
        raise RuntimeError(f'{name} failed (exit {code}). See {folder/"run.log"}')
    return record


def make_package(results):
    archive=ROOT/'EE541_results_for_review.zip'
    if archive.exists():archive.unlink()
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for f in sorted(results.rglob('*')):
            if f.is_file():z.write(f,f.relative_to(ROOT))
    print('Review archive:',archive, f'({archive.stat().st_size/1024:.0f} KB)')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--mode',choices=['smoke','full','package'],default='smoke')
    parser.add_argument('--clean',action='store_true',help='Delete earlier generated results before running')
    parser.add_argument('--seeds',type=int,default=10)
    parser.add_argument('--slots',type=int,default=120)
    parser.add_argument('--horizon',type=int,default=10)
    args=parser.parse_args()
    if not all((ROOT/f).is_file() for f in REQUIRED):
        raise RuntimeError('Run from a complete EE541 project copy')
    results=ROOT/'results'
    if args.clean and results.exists():shutil.rmtree(results)
    results.mkdir(exist_ok=True)
    if args.mode=='package':make_package(results);return
    with (results/'environment.txt').open('w') as f:
        f.write(f'Python: {sys.version}\nPlatform: {platform.platform()}\n')
        subprocess.run([sys.executable,'-m','pip','freeze'],stdout=f,stderr=subprocess.STDOUT,check=True)
    records=[]
    try:
        records.append(execute('tests',['-m','unittest','discover','-s','tests','-v'],results))
        if args.mode=='smoke':
            records.append(execute('smoke', ['research_experiments.py','--study','multiseed',
                '--backend','cvxpy','--predictor','causal','--seeds','2','--slots','15',
                '--horizon','5','--out','results/smoke'],results))
        else:
            records.append(execute('baseline',['run_experiments.py','--slots',str(args.slots),
                '--backend','cvxpy','--seed','7'],results))
            # Baseline runner has fixed output location; move its files after completion.
            for f in results.glob('*_cvxpy.*'):
                if f.is_file():shutil.move(str(f),str(results/'baseline'/f.name))
            for study in ['multiseed','forecast','horizon','stress','diagnostics']:
                cmd=['research_experiments.py','--study',study,'--backend','cvxpy',
                     '--seeds',str(args.seeds),'--slots',str(args.slots),
                     '--horizon',str(args.horizon),'--out',f'results/{study}']
                if study not in ('forecast','diagnostics'):
                    cmd += ['--predictor','causal']
                records.append(execute(study,cmd,results))
            records.append(execute('solver_accuracy',['solver_accuracy.py',
                '--horizon','12','--out','results/solver_accuracy'],results))
    finally:
        (results/'run_manifest.json').write_text(json.dumps(records,indent=2))
        make_package(results)
    print('\nAll requested stages completed. Upload EE541_results_for_review.zip')

if __name__=='__main__':main()
