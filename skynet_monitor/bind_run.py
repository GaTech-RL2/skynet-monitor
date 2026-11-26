"""Bind a Slurm job to an explicit config/metrics run without modifying training."""
import argparse
import json
import os
from pathlib import Path
import re
import tempfile


def bind(config, job_id=None):
    if job_id is None:
        array, task = os.getenv('SLURM_ARRAY_JOB_ID'), os.getenv('SLURM_ARRAY_TASK_ID')
        job_id = array + '_' + task if array and task else os.getenv('SLURM_JOB_ID')
    if not job_id or not re.fullmatch(r'\d+(?:_\d+)?',job_id):
        raise ValueError('A Slurm job ID is required')
    config=Path(config).resolve()
    data=json.loads(config.read_text())
    run_id=data.get('id')
    if not isinstance(run_id,str) or not run_id or '/' in run_id or run_id in {'.','..'}:
        raise ValueError('Invalid config run id')
    if config.parent.name!='configs':raise ValueError('Expected configs/<run>.json layout')
    if type(data.get('steps')) is not int or data['steps']<=0:raise ValueError('Invalid step target')
    target=Path.home()/'.local/state/skynet-monitor/jobs'/job_id/'run.json'
    target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd,tmp=tempfile.mkstemp(prefix='.run-',dir=target.parent)
    try:
        with os.fdopen(fd,'w') as f:json.dump(dict(job_id=job_id,config=str(config),run_id=run_id),f)
        os.replace(tmp,target)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
    return target


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True)
    parser.add_argument('--job-id')
    print(bind(**vars(parser.parse_args())))
