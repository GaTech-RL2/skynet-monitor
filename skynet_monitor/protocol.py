"""Version 1 progress.json reader and bounded discovery for Slurm jobs."""
import datetime
import json
import math
import os
from pathlib import Path
import stat
import time


def read_regular_json(path):
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > 65536:
            raise ValueError('JSON must be a regular file <= 64 KiB')
        return json.loads(handle.read(65537))


def validate(data, job_id, scoped=False, now=None):
    now = time.time() if now is None else now
    if not isinstance(data, dict) or data.get('schema_version', 1) != 1:
        raise ValueError('Unsupported progress schema')
    identity = data.get('job_id')
    if identity is not None and str(identity) != job_id:
        raise ValueError('Progress belongs to a different job')
    if identity is None and not scoped:
        raise ValueError('Shared progress paths require job_id')
    for key in ['completed', 'total']:
        value = data.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(key + ' must be finite and numeric')
    if not 0 <= data['completed'] <= data['total'] or data['total'] <= 0:
        raise ValueError('Require 0 <= completed <= total and total > 0')
    stamp = datetime.datetime.fromisoformat(str(data.get('updated_at', '')).replace('Z', '+00:00'))
    if stamp.tzinfo is None or stamp.timestamp() > now + 120:
        raise ValueError('updated_at requires a timezone and must not be in the future')
    for key in ['unit', 'stage', 'attempt_id']:
        if key in data and (not isinstance(data[key], str) or len(data[key]) > 160):
            raise ValueError(key + ' must be a short string')
    kinds = {'training': 'Training', 'processing': 'Data processing', 'evaluation': 'Evaluation', 'other': 'Job'}
    if data.get('kind', 'other') not in kinds:
        raise ValueError('Unknown kind')
    if data.get('eta_mode', 'rate') not in {'rate', 'none'}:
        raise ValueError('Unknown eta_mode')
    return dict(step=data['completed'], target=data['total'], updated=stamp.timestamp(),
                unit=data.get('unit', 'items'), stage=data.get('stage', ''),
                attempt_id=data.get('attempt_id', ''), adapter='progress.json',
                kind=kinds[data.get('kind', 'other')], eta_mode=data.get('eta_mode', 'rate'))


def discover(job, workdir=None, registry=None):
    registry = Path(registry) if registry else Path.home() / '.local/state/skynet-monitor/jobs'
    candidates = [(registry / job['id'] / 'progress.json', True)]
    if workdir:
        root = Path(workdir)
        candidates.append((root / '.skynet-progress' / job['id'] / 'progress.json', True))
        if '/' not in job['name'] and job['name'] not in {'.', '..'}:
            candidates.append((root / 'runs' / job['name'] / 'progress.json', False))
        candidates.append((root / 'progress.json', False))
    errors = []
    for path, scoped in candidates:
        try:
            # Nonblocking open prevents a named pipe from hanging collection.
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            with os.fdopen(fd, 'rb') as handle:
                info = os.fstat(handle.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > 65536:
                    raise ValueError('Progress must be a regular file <= 64 KiB')
                data = json.loads(handle.read(65537))
            if isinstance(data, dict) and data.get('job_id') is not None and str(data['job_id']) != job['id']:
                if scoped:
                    raise ValueError('Progress belongs to a different job')
                continue
            result = validate(data, job['id'], scoped)
            result['source'] = str(path)
            return result, errors
        except FileNotFoundError:
            continue
        except (OSError, ValueError, TypeError, OverflowError) as e:
            errors.append(str(path) + ': ' + str(e))
    return None, errors
