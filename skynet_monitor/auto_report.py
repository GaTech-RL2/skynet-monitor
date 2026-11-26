"""Fail-open sidecar for existing jobs; never signals or waits on the workload."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
from report_progress import report
def read_json(path):
    try:return json.loads(Path(path).read_text())
    except (OSError, ValueError):return {}


def training_sample(config_path):
    config = read_json(config_path)
    root = config_path.parent.parent
    path = root / 'runs' / config['id'] / 'metrics.jsonl'
    with path.open('rb') as handle:
        handle.seek(0, 2)
        handle.seek(max(0, handle.tell() - 65536))
        lines = handle.read(65536).split(b'\n')[:-1]
    for line in reversed(lines):
        try:
            row = json.loads(line)
            step = row['step']
            if isinstance(step, int) and 0 <= step <= config['steps']:
                return dict(completed=step, total=config['steps'], unit='steps', stage='training', kind='training')
        except (ValueError, KeyError, TypeError):
            continue
    return None


def process_identity(pid):
    """Linux start time distinguishes a live PID from a reused PID."""
    try:
        value = Path('/proc') / str(pid) / 'stat'
        if Path('/proc').exists():
            fields = value.read_text().rsplit(')', 1)[1].split()
            return None if fields[0] == 'Z' else fields[19]
        os.kill(pid, 0)
        return str(pid)
    except (OSError, IndexError):
        return None


def watch(pid, sample, interval=30, output=None):
    identity = process_identity(pid)
    if identity is None:
        return
    attempt = os.getenv('SLURM_RESTART_COUNT', '0') + ':' + str(pid) + ':' + identity
    last, next_sample, warned = None, 0, False
    while process_identity(pid) == identity:
        if time.monotonic() >= next_sample:
            next_sample = time.monotonic() + interval
            try:
                data = sample()
                # No heartbeat disguised as progress: preserve the time of the last advance.
                if data and data != last:
                    report(**data, attempt_id=attempt, output=output)
                    last = data
            except Exception as exc:
                if not warned:
                    print('Progress sidecar waiting/unavailable: ' + str(exc), file=sys.stderr)
                    warned = True
        time.sleep(min(interval, 2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--interval', type=float, default=30)
    parser.add_argument('--output')
    args = parser.parse_args()
    if args.interval <= 0:parser.error('Interval must be positive')
    watch(args.pid, lambda: training_sample(args.config), args.interval, args.output)
