"""Read-only inventory of the current user’s running Slurm jobs."""
import concurrent.futures
import datetime
import getpass
import json
import os
from pathlib import Path
import re
import subprocess
import sys


def run(args, timeout=15):
    p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError(p.stderr.strip()[-800:] or 'Command failed')
    return p.stdout


def processes(raw, node):
    rows = []
    for line in raw.splitlines():
        a = line.strip().split(None, 7)
        if len(a) == 8:
            rows.append(dict(node=node, pid=a[0], ppid=a[1], state=a[2], cpu=a[3],
                             memory=a[4], elapsed=a[5], started=a[6], command=a[7]))
    return rows


def is_training(name):
    """Conservative job-name classification; site patterns can be overridden."""
    include = os.environ.get('SKYNET_TRAIN_INCLUDE', r'train|finetun|(?:^|[-_])ft\d*|(?:^|[-_])scratch')
    exclude = os.environ.get('SKYNET_TRAIN_EXCLUDE', r'smoke|audit|gate|eval|rollout|export|preprocess|summary|score|prepare')
    return bool(re.search(include, name, re.I)) and not re.search(exclude, name, re.I)


def job_kind(name):
    return 'Training' if is_training(name) else 'Job'


def allocated_gpu(info):
    """Use actual allocations only, never requested GPUs or node inventory."""
    match = re.search(r'(?:^|\s)AllocTRES=(\S+)', info)
    if not match or match[1] in {'(null)', 'N/A'}:
        return 'Unknown'
    resources = dict(item.split('=', 1) for item in match[1].split(',') if '=' in item)
    typed = [(key[len('gres/gpu:'):].upper(), int(value))
             for key, value in resources.items()
             if key.startswith('gres/gpu:') and value.isdigit() and int(value) > 0]
    total = resources.get('gres/gpu')
    if typed:
        labels = [f'{model} × {count}' for model, count in sorted(typed)]
        if total and total.isdigit() and int(total) > sum(count for _, count in typed):
            labels.append(f'Unknown GPU × {int(total) - sum(count for _, count in typed)}')
        return ', '.join(labels)
    if total and total.isdigit() and int(total) > 0:
        return f'GPU × {total} (model unknown)'
    return 'CPU only'


def training_progress(job):
    """Read the exact run's config/metrics; never load a checkpoint or infer a target from its name."""
    try:
        binding = Path.home()/'.local/state/skynet-monitor/jobs'/job['id']/'run.json'
        from protocol import read_regular_json
        try:
            bound = read_regular_json(binding)
        except FileNotFoundError:
            bound = None
        if bound is not None:
            if not isinstance(bound, dict) or bound.get('job_id') != job['id']:
                return dict(error='Run binding identity mismatch')
            config_path = Path(bound['config'])
            run_id = bound['run_id']
            if not config_path.is_absolute() or config_path.parent.name != 'configs':
                return dict(error='Invalid bound config path')
            root = config_path.parent.parent
        else:
            info = run(['scontrol', 'show', 'job', job['id'], '-o'])
            match = re.search(r'(?:^|\s)WorkDir=(.*?)(?=\s\w+=|$)', info)
            if not match:return dict(error='No supported run directory')
            root, run_id = Path(match[1]), job['name']
            config_path = root / 'configs' / (run_id + '.json')
            if not config_path.is_file():
                from chain_progress import discover_config
                submitted = run(['scontrol', 'write', 'batch_script', job['id'], '-'])
                config_path, run_id = discover_config(submitted, root)
                root = config_path.parent.parent
        if not isinstance(run_id,str) or not run_id or '/' in run_id or run_id in {'.', '..'}:
            return dict(error='Invalid run identity')
        config = read_regular_json(config_path)
        if config.get('id') != run_id:
            return dict(error='Run identity mismatch')
        target = config.get('steps')
        if not isinstance(target, int) or target <= 0:
            return dict(error='No step target in config')
        metrics = root / 'runs' / run_id / 'metrics.jsonl'
        with metrics.open('rb') as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 65536))
            raw = f.read(65536)
            modified = os.fstat(f.fileno()).st_mtime
        # Ignore an incomplete trailing record while training is writing it.
        lines = raw.split(b'\n')[:-1]
        for line in reversed(lines):
            try:
                record = json.loads(line)
                step = record.get('step')
                if isinstance(step, int) and step >= 0:
                    return dict(step=step, target=target, updated=modified,
                                source=str(metrics), loss=record.get('loss'), unit='steps')
            except (ValueError, AttributeError):
                continue
        return dict(error='Waiting for metrics')
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.TimeoutExpired) as e:
        return dict(error='Progress unavailable: ' + str(e))


def main():
    user = getpass.getuser()
    if len(sys.argv) > 1:
        job = sys.argv[1]
        if not re.fullmatch(r'\d+(?:_\d+)?', job):
            raise ValueError('Invalid job ID')
        info = run(['scontrol', 'show', 'job', job, '-o'])
        if not re.search(r'UserId=' + re.escape(user) + r'\(', info):
            raise ValueError('Job is not owned by current user')
        logs = []
        seen = set()
        for field in ['StdOut', 'StdErr']:
            m = re.search(r'(?:^|\s)' + field + r'=(.*?)(?=\s\w+=|$)', info)
            if not m or m[1] in seen:
                continue
            path = m[1]
            seen.add(path)
            try:
                with open(path, 'rb') as f:
                    f.seek(0, 2)
                    f.seek(max(0, f.tell() - 48000))
                    content = f.read(48000).decode('utf-8', errors='replace')
                logs.append(dict(path=path, text=content))
            except OSError as e:
                logs.append(dict(path=path, text=str(e)))
        print(json.dumps(dict(info=info, logs=logs)))
        return
    from protocol import discover
    from gpu_telemetry import attach
    errors, jobs = [], []
    raw = run(['squeue', '--array', '-u', user, '-h', '-t', 'RUNNING',
               '-o', '%i|%j|%T|%M|%l|%D|%N|%P|%r'])
    for line in raw.splitlines():
        fields = line.split('|')
        if len(fields) != 9:
            continue
        job = dict(zip(['id','name','state','elapsed','limit','nodes','node','partition','reason'], fields))
        if job['state'] != 'RUNNING':continue
        info, workdir = '', None
        try:
            info = run(['scontrol', 'show', 'job', job['id'], '-o'])
            match = re.search(r'(?:^|\s)WorkDir=(.*?)(?=\s\w+=|$)', info)
            workdir = match[1] if match else None
        except Exception as exc:
            errors.append(dict(job=job['id'],error=str(exc)))
        standard, warnings = discover(job, workdir)
        job['kind'] = standard['kind'] if standard else job_kind(job['name'])
        if os.getenv('SKYNET_TRAINING_ONLY') == '1' and not standard and not is_training(job['name']):
            continue
        job['gpu'] = allocated_gpu(info)
        identity = re.search(r'(?:^|\s)JobId=(\d+)', info)
        job['gpu_job_id'] = identity[1] if identity else job['id']
        job['progress'] = standard or training_progress(job)
        if warnings:job['progress_warning'] = '; '.join(warnings)
        jobs.append(job)
    if os.getenv('SKYNET_GPU_TELEMETRY', '1') == '1':
        attach(jobs)
    print(json.dumps(dict(user=user,timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                         jobs=jobs,errors=errors)))


if __name__ == '__main__':
    main()
