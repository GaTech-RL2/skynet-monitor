"""Dependency-free writer: import report() or invoke from a Slurm job."""
import argparse
import datetime
import json
import os
from pathlib import Path
import re
import tempfile
from protocol import validate


def report(completed, total, unit='items', stage='', kind='other', attempt_id='', job_id=None, output=None, eta_mode='rate'):
    if job_id is None:
        array, task = os.getenv('SLURM_ARRAY_JOB_ID'), os.getenv('SLURM_ARRAY_TASK_ID')
        job_id = array + '_' + task if array and task else os.getenv('SLURM_JOB_ID')
    if not job_id or not re.fullmatch(r'\d+(?:_\d+)?', job_id):
        raise ValueError('A Slurm job ID is required; use --job-id outside Slurm')
    data = dict(schema_version=1, job_id=job_id, completed=completed, total=total, unit=unit,
                stage=stage, kind=kind, attempt_id=attempt_id, eta_mode=eta_mode,
                updated_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
    validate(data, job_id)
    path = Path(output) if output else Path.home()/'.local/state/skynet-monitor/jobs'/job_id/'progress.json'
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix='.progress-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as handle:
            json.dump(data, handle, allow_nan=False)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--completed', type=float, required=True)
    parser.add_argument('--total', type=float, required=True)
    parser.add_argument('--unit', default='items')
    parser.add_argument('--stage', default='')
    parser.add_argument('--kind', choices=['training', 'processing', 'evaluation', 'other'], default='other')
    parser.add_argument('--attempt-id', default='')
    parser.add_argument('--job-id')
    parser.add_argument('--output')
    parser.add_argument('--eta-mode', choices=['rate', 'none'], default='rate')
    print(report(**vars(parser.parse_args())))
