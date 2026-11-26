# Standard job progress (version 1)

The monitor discovers **your RUNNING Slurm jobs**. A valid standard progress
file supplies progress for any name/type, including evaluation and data processing. All running jobs appear by default; jobs
without standard progress may use the config/JSONL training adapter.
Queued jobs and non-Slurm processes are not shown.

## Recommended: report from your job

The installed writer needs only Python's standard library. Call it periodically
(for example every 30–60 seconds) from the job, after a successful unit of work:

```sh
python3 ~/.local/share/skynet-monitor/report_progress.py \
  --completed 804 --total 2066 --unit episodes \
  --stage processing --kind processing
```

It derives the identity from Slurm environment variables, including array task
IDs (`SLURM_ARRAY_JOB_ID_SLURM_ARRAY_TASK_ID`, e.g. `12345_7`), and atomically
replaces an owner-only file at:

`~/.local/state/skynet-monitor/jobs/<job_id>/progress.json`

This shared-home registry is visible from sky1 regardless of the job's working
directory. Each array task reports its own progress; do not write multiple
workers into one file. No change to the webpage is needed for future jobs.
For frequent updates, import the writer rather than spawning Python each time:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / '.local/share/skynet-monitor'))
from report_progress import report

report(completed=804, total=2066, unit='episodes',
       stage='processing', kind='processing', attempt_id='attempt-1')
```

Report **successful units completed**, not launched work. For a restarted or
different attempt, change `attempt_id`. Stage changes, target changes, unit
changes and counter rollback all reset the speed estimate. Updating a progress
file does not submit, restart or alter the Slurm job.

## File format

```json
{
  "schema_version": 1,
  "job_id": "12345_7",
  "completed": 804,
  "total": 2066,
  "unit": "episodes",
  "stage": "processing",
  "kind": "processing",
  "attempt_id": "attempt-1",
  "updated_at": "2026-11-19T02:33:00Z"
}
```

Required: `completed`, `total`, `updated_at`. Counters must be finite numbers,
with `0 <= completed <= total` and `total > 0`. Timestamp must be ISO 8601 with
a timezone and no more than two minutes in the future. `schema_version`
defaults to 1. `unit` defaults to `items`. `kind` is `training`, `processing`,
`evaluation` or `other`; default `other` preserves a known legacy category.
Unit, stage and attempt ID are optional strings up to 160 characters. Optional `eta_mode` is `rate` (default) or `none`; use `none` for unequal stage counters.

## Discovery and identity

For each running job, inspect these paths in order:

1. `~/.local/state/skynet-monitor/jobs/<job_id>/progress.json`
2. `<Slurm WorkDir>/.skynet-progress/<job_id>/progress.json`
3. `<Slurm WorkDir>/runs/<job_name>/progress.json`
4. `<Slurm WorkDir>/progress.json`

`job_id` may be omitted only in paths 1 and 2, which are already scoped by
job ID. Paths 3 and 4 **require** a matching `job_id` to prevent concurrent
jobs sharing a working directory from consuming each other's progress.
Every file must be a regular file <=64 KiB. Write a temporary file and rename
it over the destination; never leave a partially written JSON file.

First valid matching file wins. Malformed files are diagnosed; a later valid
file or legacy adapter can still supply progress. Files explicitly belonging
to another job in a shared directory are ignored. Standard progress overrides
the legacy adapter for that job. Existing jobs do not need modification.

## ETA and limitations

ETA uses observed counter changes over at least 30 seconds, with approximately
ten minutes of recent samples. It shows Estimating initially, resets when work
identity changes, and suppresses estimates after five minutes without counter
advancement or with stale timestamps. Reaching total while Slurm still reports
RUNNING is displayed as Finalizing. Speed samples reset on monitor restart.

The generic file is per-job progress, not automatic aggregation across array
workers. Pauses, variable work cost, validation,
queue changes and retries can change the estimate. Files may remain after job
completion; only current RUNNING jobs are read, with no historical-job display.
