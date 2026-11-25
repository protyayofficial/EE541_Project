#!/usr/bin/env bash
# Production is opt-in. --smoke uses short real-input workflows in /tmp.
set -euo pipefail
ee541_project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$ee541_project_root"
export MPLCONFIGDIR="${MPLCONFIGDIR:-/tmp/ee541-matplotlib}"
export PYTHONUNBUFFERED=1
exec python -B - "$@" <<'PY'
import argparse
import fcntl
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import sys
import traceback
import uuid

PROJECT=Path.cwd()
PYTHON=Path(sys.executable)
LAUNCHER=PROJECT/'scripts/run_experiments.sh'


def utc():return datetime.now(timezone.utc).isoformat(timespec='seconds')


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def preflight(output=None,readiness_record=None):
    import cvxpy as cp
    import numpy as np
    import pandas as pd
    import final_evaluation as synthetic
    import final_solar_evaluation as solar
    import supplementary_studies as supplementary
    from src.scheduling import Config, INITIAL_QUEUE, INITIAL_ENERGY
    from src.forecasting import ARRIVAL_MODEL
    from src.course_data import SOURCE_FILES, SOURCE_SHA256, SOURCE_INTERVALS, SOURCE_SCALES, evaluation_sources
    expected=dict(buffer_max=32.,energy_max=12.,power_max=3.,data_max=5.,tau=1.,slot_seconds=5.,
        bandwidth_hz=3000.,packet_bits=256.,bit_error_probability=9.89e-6,
        probe_seconds=.3,channel_report_seconds=.3,decision_seconds=1.,ack_seconds=1.,update_seconds=1.,
        probe_energy=.2,channel_report_energy=0.,ack_energy=0.,noise_psd=1e-9,
        drop_weight=35.,energy_weight=.15,terminal_weight=6.,horizon=10,segments=12,
        channel_rho=.68,channel_sigma=.45,channel_mean_normalize=True)
    assert asdict(Config())==expected, 'current Config differs from intended production configuration'
    assert (INITIAL_QUEUE,INITIAL_ENERGY)==(12,7.)
    assert ARRIVAL_MODEL['support']==list(range(11)) and ARRIVAL_MODEL['mean']==5.
    np.testing.assert_allclose(ARRIVAL_MODEL['probabilities'],np.full(11,1/11))
    assert {'CLARABEL','SCS'}<=set(cp.installed_solvers()), 'required solvers unavailable'
    assert synthetic.DEFAULT_SLOTS==1000 and synthetic.SIGMAS==(.2,.45,.8) and synthetic.HARVEST==(.6,1.2)
    assert synthetic.MODES==('greedy','nominal','fixed_margin','adaptive_harvest','adaptive_all')
    assert solar.MODES==('fixed','channel','greedy','nominal','fixed_margin','adaptive_harvest','adaptive_all',
                         'fixed_fraction','adaptive_channel','adaptive_arrival')
    assert supplementary.POLICIES==('nominal','adaptive_all') and supplementary.HARVEST==(.6,1.2)
    assert supplementary.VALUES=={'delay_energy':(.15,15.,150.),'forecast_sensitivity':(0.,.25,.5)}
    matrices=[synthetic.planned_runs(),synthetic.planned_runs(mean_normalize=True),solar.planned_runs(),
              supplementary.planned_runs('delay_energy'),supplementary.planned_runs('forecast_sensitivity')]
    for rows,count,start in zip(matrices,(300,300,300,120,120),(5000,6000,7000,6000,6000)):
        frame=pd.DataFrame(rows)
        assert len(frame)==count and not frame.duplicated().any()
        assert set(frame.seed)==set(range(start,start+10)), 'driver seed contract changed'
    assert pd.DataFrame(matrices[1]).groupby(['harvest_mean','channel_sigma','seed']).ngroups==60
    assert pd.DataFrame(matrices[2]).groupby(['dataset','scenario_index']).ngroups==30
    assert SOURCE_INTERVALS=={'arco':60.,'umass_home_c':60.,'nrel_tmy3':3600.}
    assert SOURCE_SCALES=={'arco':.01,'umass_home_c':.1,'nrel_tmy3':.005}
    for name,file in SOURCE_FILES.items():assert digest(file)==SOURCE_SHA256[name], f'input checksum mismatch: {file}'
    sources=list(evaluation_sources(slots=1000, count=10))
    assert len(sources)==3
    for name,seconds,windows,_ in sources:
        assert seconds==SOURCE_INTERVALS[name] and len(windows)==10
        assert all(len(values)==1000 and np.isfinite(values).all() for _,values in windows)
    if readiness_record is not None:
        approved=json.loads(readiness_record.read_text())
        assert approved['ready_for_authorized_production']
        for file,sha in approved['source_sha256'].items():
            assert digest(PROJECT/file)==sha, f'code changed since passed readiness checks: {file}'
    files={str(p.relative_to(PROJECT)):digest(p) for p in PROJECT.glob('*.py')}
    files.update({str(p.relative_to(PROJECT)):digest(p) for p in (PROJECT/'src').glob('*.py')})
    files[str(LAUNCHER.relative_to(PROJECT))]=digest(LAUNCHER)
    if readiness_record is not None:
        files[str(readiness_record)]=digest(readiness_record)
    files.update({file:digest(file) for file in SOURCE_FILES.values()})
    result=dict(passed=True,time=utc(),config=expected,initial_queue=12,initial_energy=7.,
        seed_ranges=dict(original=[5000,5009],normalized=[6000,6009],solar=[7000,7009],supplementary=[6000,6009]),
        production_counts=dict(main_online=900,delay_energy=120,forecast_sensitivity=120,offline=90,solver_checks=12),
        real_windows=30,input_checksums=SOURCE_SHA256,source_and_input_hashes=files,
        readiness_record=str(readiness_record) if readiness_record else None,
        readiness_sha256=digest(readiness_record) if readiness_record else None)
    if output:(output/'preflight.json').write_text(json.dumps(result,indent=2)+'\n')
    print('PASS: configuration, seed and matrix contracts, 3 input checksums and 30 real 1000-slot windows')
    return result


def solver_audit(root):
    import numpy as np
    import pandas as pd
    data=pd.read_csv(root/'solver/solver_results.csv')
    assert len(data)==12 and not data.duplicated(['case','solver']).any()
    assert set(data.case)==set(range(6)) and set(data.solver)=={'CLARABEL','SCS'}
    assert (data.status=='optimal').all() and np.isfinite(data.objective).all()
    assert np.isfinite(data.primal_violation).all() and (data.primal_violation<=1e-4).all()
    comparison=pd.read_csv(root/'solver/solver_comparison.csv')
    assert len(comparison)==6 and (comparison.relative_objective_difference<=1e-3).all()
    result=dict(passed=True,solves=12,checks='complete six-by-two matrix; optimal status; finite objectives; residual <=1e-4; relative agreement <=1e-3')
    (root/'solver/audit.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))


def completion_audit(root,seeds,windows,slots,horizon):
    import pandas as pd
    for folder,count,start in (('sweep',30*seeds,5000),('sweep_normalized',30*seeds,6000),
            ('solar',30*windows,7000),('supplementary/delay_energy',12*seeds,6000),
            ('supplementary/forecast_sensitivity',12*seeds,6000)):
        directory=root/folder;s=json.loads((directory/'settings.json').read_text())
        assert s['slots']==slots and s['horizon']==horizon
        assert s['seed_ids']==list(range(start,start+(windows if folder=='solar' else seeds)))
        name='per_window.csv' if folder=='solar' else 'per_seed.csv'
        raw=pd.read_csv(directory/name);assert len(raw)==count and raw.run_id.nunique()==count
        assert s['planned_policy_runs']==count and json.loads((directory/'audit.json').read_text())['passed']
        assert (directory/'per_packet.csv').is_file()
        assert list(directory.glob('*.png')), f'missing automatic study plots: {folder}'
    assert json.loads((root/'solar/source_audit.json').read_text())['passed']
    offline=pd.read_csv(root/'offline/per_instance.csv');assert len(offline)==6*seeds+3*windows
    assert (offline.status=='optimal').all() and json.loads((root/'offline/audit.json').read_text())['passed']
    assert (root/'figures/one_step_coverage.png').is_file() and (root/'figures/solar_paired_cost.png').is_file()
    assert json.loads((root/'solver/audit.json').read_text())['passed']
    print('PASS: all saved counts, seed ranges, episode lengths, audits and automatic plots')


def stages(root,seeds,windows,slots,horizon,readiness_record=None):
    def command(script,*args):return [str(PYTHON),'-B',script,*map(str,args)]
    common=['--slots',slots,'--horizon',horizon]
    synth=['--seeds',seeds,'--rho',.68,'--sigma',.20,.45,.80,*common]
    return [
        ('preflight',lambda:preflight(root,readiness_record),'check configuration, input checksums and 30 full windows'),
        ('solar_validate',command('final_solar_evaluation.py','--validate-only','--windows',windows,*common,'--out',root/'solar'),''),
        ('solver_checks',command('solver_crosscheck.py','--out',root/'solver'),''),
        ('solver_audit',lambda:solver_audit(root),'validate all 12 recorded solves; failures are fatal'),
        ('sweep',command('final_evaluation.py',*synth,'--seed-start',5000,'--out',root/'sweep'),''),
        ('sweep_audit',command('audit_final_evaluation.py',root/'sweep'),''),
        ('sweep_normalized',command('final_evaluation.py','--mean-normalize',*synth,'--seed-start',6000,'--out',root/'sweep_normalized'),''),
        ('normalized_audit',command('audit_final_evaluation.py',root/'sweep_normalized'),''),
        ('solar',command('final_solar_evaluation.py','--windows',windows,*common,'--out',root/'solar'),''),
        ('solar_action_audit',command('audit_comparison.py',root/'solar'),''),
        ('solar_source_audit',command('audit_final_solar.py',root/'solar'),''),
        ('delay_energy',command('supplementary_studies.py','delay_energy','--seeds',seeds,*common,'--out',root/'supplementary/delay_energy'),''),
        ('delay_energy_analysis_plots',command('analyze_supplementary.py',root/'supplementary/delay_energy'),''),
        ('delay_energy_audit',command('audit_supplementary.py',root/'supplementary/delay_energy'),''),
        ('forecast_sensitivity',command('supplementary_studies.py','forecast_sensitivity','--seeds',seeds,*common,'--out',root/'supplementary/forecast_sensitivity'),''),
        ('forecast_analysis_plots',command('analyze_supplementary.py',root/'supplementary/forecast_sensitivity'),''),
        ('forecast_audit',command('audit_supplementary.py',root/'supplementary/forecast_sensitivity'),''),
        ('offline_references',command('offline_reference.py','--root',root),''),
        ('offline_audit',command('audit_offline.py',root/'offline'),''),
        ('main_figures',command('plot_final_figures.py','--root',root),''),
        ('completion_audit',lambda:completion_audit(root,seeds,windows,slots,horizon),'check exact counts, saved seed ranges, lengths, audits and plots')]


def pipeline(root,work):
    """Sequential runner; retain every log and partial output on any failure."""
    root.mkdir(parents=True,exist_ok=False);(root/'logs').mkdir()
    shutil.copyfile(LAUNCHER,root/'launcher.sh')
    state=dict(status='running',started_at=utc(),pid=os.getpid(),output_root=str(root),current_stage=None,
        stages=[dict(stage=name,status='pending',log=f'logs/{i:02d}_{name}.log',
                     command=cmd if isinstance(cmd,list) else description)
                for i,(name,cmd,description) in enumerate(work,1)])
    for row in state['stages']:(root/row['log']).touch()
    def save():
        temporary=root/'status.tmp';temporary.write_text(json.dumps(state,indent=2)+'\n');temporary.replace(root/'status.json')
    def event(row):
        with (root/'status.tsv').open('a') as handle:
            handle.write(f"{utc()}\t{row['stage']}\t{row['status']}\t{row.get('exit_code','')}\n")
    child=None;fingerprints=None;current=None
    def interrupt(signum,frame):
        if child is not None and child.poll() is None:
            try:os.killpg(child.pid,signum)
            except ProcessLookupError:pass
        raise KeyboardInterrupt(signum)
    previous={s:signal.signal(s,interrupt) for s in (signal.SIGINT,signal.SIGTERM)}
    save()
    try:
        for row,(name,cmd,_) in zip(state['stages'],work):
            current=row;state['current_stage']=name;row.update(status='running',started_at=utc());save();event(row)
            print(f"{utc()} START {name} log={root/row['log']}",flush=True)
            with (root/row['log']).open('a') as log:
                if fingerprints:
                    for file,sha in fingerprints.items():
                        if digest(PROJECT/file)!=sha:raise RuntimeError(f'input/code changed during pipeline: {file}')
                if callable(cmd):
                    with redirect_stdout(log),redirect_stderr(log):result=cmd()
                    if name=='preflight':fingerprints=result['source_and_input_hashes']
                    code=0
                else:
                    child=subprocess.Popen(cmd,cwd=PROJECT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                    code=child.wait();child=None
                if code:raise subprocess.CalledProcessError(code,cmd)
            row.update(status='completed',ended_at=utc(),exit_code=0);save();event(row)
            print(f'{utc()} DONE {name}',flush=True)
        state.update(status='completed',ended_at=utc(),current_stage=None);save()
        (root/'COMPLETED').write_text(utc()+'\n');print(f'COMPLETED: {root}',flush=True);return 0
    except BaseException as exc:
        interrupted=isinstance(exc,KeyboardInterrupt)
        code=128+int(exc.args[0]) if interrupted and exc.args else getattr(exc,'returncode',1)
        if code<0:code=128-code
        if child is not None and child.poll() is None:
            try:child.wait(timeout=30)
            except subprocess.TimeoutExpired:
                try:os.killpg(child.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                child.wait()
        if current:
            current.update(status='interrupted' if interrupted else 'failed',ended_at=utc(),exit_code=code,error=str(exc))
            with (root/current['log']).open('a') as log:
                log.write(f'\nLAUNCHER ERROR: {exc!r}\n')
                traceback.print_exception(type(exc),exc,exc.__traceback__,file=log)
            event(current)
        state.update(status='interrupted' if interrupted else 'failed',ended_at=utc(),exit_code=code,error=str(exc));save()
        (root/'FAILED').write_text(f"{utc()} stage={state['current_stage']} exit={code}\n")
        print(f"FAILED: stage={state['current_stage']} exit={code}; all logs/partial outputs preserved at {root}",file=sys.stderr,flush=True)
        return code
    finally:
        for sig,handler in previous.items():signal.signal(sig,handler)


def main():
    parser=argparse.ArgumentParser(description='Default: checked plan only. --run explicitly executes sequentially; no resume/overwrite.')
    mode=parser.add_mutually_exclusive_group();mode.add_argument('--plan-only',action='store_true');mode.add_argument('--run',action='store_true')
    parser.add_argument('--smoke',action='store_true',help='4-slot, two-seed/window real-input workflow; production definitions unchanged')
    parser.add_argument('--output-parent',type=Path,help='parent only; launcher always creates a new timestamped child')
    parser.add_argument('--readiness-record',type=Path,help='optional prior source-provenance record to verify')
    args=parser.parse_args()
    readiness_record=args.readiness_record.expanduser().resolve() if args.readiness_record else None
    seeds=windows=2 if args.smoke else 10;slots=4 if args.smoke else 1000;horizon=10
    parent=(args.output_parent or (Path('/tmp') if args.smoke else PROJECT/'results')).expanduser().resolve()
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    root=parent/f"{'ee541_smoke' if args.smoke else 'final_evaluation_continuous_1000'}_{stamp}_{os.getpid()}_{uuid.uuid4().hex[:6]}"
    print(f'OUTPUT_ROOT={root}',flush=True)
    print(f'WORKING_DIRECTORY={PROJECT}',flush=True)
    print(f"MODE={'RUN' if args.run else 'PLAN ONLY'}{' (SMOKE)' if args.smoke else ''}",flush=True)
    print(f'Episodes: {slots} slots; online horizon: {horizon}; solver instances: 10 slots',flush=True)
    print(f'Seeds: original 5000–{4999+seeds}; normalized/supplementary 6000–{5999+seeds}; solar 7000–{6999+windows}',flush=True)
    print('Solar/supplementary starts are fixed driver contracts, checked before execution and against saved settings.',flush=True)
    print(f'Counts: main online {60*seeds+30*windows} (original {30*seeds} + normalized {30*seeds} + solar {30*windows}); delay–energy {12*seeds}; forecast-sensitivity {12*seeds}; offline references {6*seeds+3*windows}; solver checks 12',flush=True)
    work=stages(root,seeds,windows,slots,horizon,readiness_record)
    print('Sequential stages (each failure stops the pipeline):',flush=True)
    for i,(name,cmd,description) in enumerate(work,1):
        if isinstance(cmd,list):
            displayed=[]
            for value in cmd:
                if value.startswith(str(root)):displayed.append('"${OUTPUT_ROOT}'+value[len(str(root)):]+'"')
                else:displayed.append(shlex.quote('python' if value==str(PYTHON) else value))
            description=' '.join(displayed)
        else:description=f'[internal: {description}]'
        print(f'{i:02d} {name}: {description}',flush=True)
    if not args.run:
        preflight(readiness_record=readiness_record)
        print('PLAN ONLY: no output directory created; no policy, solver or offline runs executed. Use --run to allocate a fresh root and execute.',flush=True)
        return 0
    if args.smoke:return pipeline(root,work)
    # Cross-process/namespace lock prevents duplicate production launches. Never
    # infer a stale running batch is safe to restart from PID visibility alone.
    with (PROJECT/'results/.production_experiments.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('another production launcher holds the experiment lock')
        for status_file in (PROJECT/'results').glob('final_evaluation_continuous_1000_*/status.json'):
            if json.loads(status_file.read_text()).get('status')=='running':
                raise RuntimeError(f'existing batch is marked running; reconcile before restart: {status_file}')
        return pipeline(root,work)


if __name__=='__main__':sys.exit(main())
PY
