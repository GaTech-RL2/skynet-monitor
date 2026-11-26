# Connect your training to Skynet Monitor

## 1. Install once per user

Follow [README.md installation and SSH tunnel instructions](README.md#install-on-skynet)
on your usual login node. Use your own account, host and printed port. Check:

```bash
systemctl --user status skynet-monitor
squeue -u "$USER" -t RUNNING
```

Open the dashboard through the tunnel and sign in with your generated access
key. All your RUNNING Slurm jobs appear by default, even without progress.
There is no special training submission service: keep using your usual `sbatch`.
The monitor does not choose GPUs, activate your environment or launch training.

## 2. Choose an integration

| Your training setup | What to do |
| --- | --- |
| Any framework with a training loop or callback | Recommended: report completed steps from Python as below |
| Existing `configs/<job-name>.json` and `runs/<job-name>/metrics.jsonl` | Use the legacy adapter described in README; Slurm WorkDir must be the campaign root |
| Wrapper with literal CAMPAIGN_ROOT/RUN_ID or explicit --config | Automatic static discovery, with the same config/metrics layout; see README limits |
| Dynamic chain, arrays, sourced environment, multiple stages | Use standard progress in each actual worker/stage; do not rely on shell parsing |

A `--config` flag alone is not enough for arbitrary frameworks: the legacy
adapter requires JSON `id` and positive integer `steps`, plus matching JSONL
metrics with `step`. Standard reporting has no such directory requirement.

## 3. Add reporting once to your trainer

Add the import/setup before your existing training loop. The installed module
and shared home must be readable on compute nodes. In containers, mount that
location or vendor `report_progress.py` and `protocol.py` together.

```python
import os
import sys
import time
import warnings
from pathlib import Path

sys.path.insert(0, str(Path.home() / '.local/share/skynet-monitor'))
try:
    from report_progress import report
except ImportError:
    report = None

last_report = float('-inf')
# Requeue changes this automatically; include your own attempt identifier when
# restarting a stage within the same Slurm allocation.
attempt = os.environ.get('SLURM_RESTART_COUNT', '0')

def monitor_progress(completed, total, *, is_primary, stage='train'):
    global last_report
    if report is None or not is_primary:
        return
    now = time.monotonic()
    if now - last_report < 30 and completed != total:
        return
    last_report = now
    try:
        report(completed=completed, total=total, unit='steps',
               stage=stage, kind='training', attempt_id=attempt)
    except (OSError, ValueError) as exc:
        warnings.warn(f'Monitor progress unavailable: {exc}')
```

Inside your existing loop, **after a successful optimizer update**, call:

```python
monitor_progress(global_step, total_steps, is_primary=is_global_rank_zero)
```

Adapt those three variables to your framework. For single-process training,
pass `is_primary=True`. For distributed training, use global rank zero, not
local rank zero; multiple writers must not overwrite the same job record.
Report the restored global step when resuming, rather than resetting it to zero.
For gradient accumulation, count optimizer updates consistently with the target.
You can also call this from a framework callback after each training step.
No framework dependency is added to the monitor.

## 4. Submit normally

Keep your existing resource directives, environment setup and training command.
For example, if your existing batch script is `train.sbatch`:

```bash
sbatch train.sbatch
```

Do not add `--job-id` to the trainer: the writer reads Slurm identity, including
array indices. Every future submission of this instrumented trainer gets its
own progress file automatically. Array tasks report independently; this does
not aggregate an entire array or dependent-job chain into one ETA.

For several stages inside one job, report distinct `stage` values and each
stage's completed/total counts. ETA then describes the current stage. Do not
count unequal stages as equal work; use `eta_mode='none'` if no meaningful rate
exists. Different Slurm jobs in a dependency chain appear only while RUNNING.

## 5. Verify before calling it done

1. Confirm the job is RUNNING using `squeue`; queued jobs are intentionally absent.
2. On the login node inspect your file (replace JOB_ID; arrays use `12345_7`):
   `cat ~/.local/state/skynet-monitor/jobs/JOB_ID/progress.json`.
3. Confirm `completed`, `total`, stage and job identity match the actual trainer;
   observe at least two advancing updates. Do not inject fake counters into a
   real job's registry as a test.
4. Refresh the dashboard. ETA needs advancing samples spanning at least 30
   seconds; stale/no-advance progress suppresses it. A successful import alone
   does not prove integration.
5. If the row is missing, check the account, RUNNING state and training-only
   filter. If progress is missing, check shared-home/container visibility,
   reporting exceptions and [schema rules](PROGRESS.md). If GPU readings alone
   are missing, see README's telemetry limitations.

Monitor collection continues remotely after disconnecting your laptop when
user-service persistence is configured. Viewing still requires a working SSH
tunnel. Never share private SSH keys or the dashboard access key in a repository.

## Prompt to give your coding agent

> Read https://github.com/GaTech-RL2/skynet-monitor (AGENTS.md, README.md,
> TRAINING.md and PROGRESS.md). Inspect my existing Slurm launcher and trainer.
> Install a monitor under my own account and integrate standard progress once
> into the loop/callback, with one writer per job and actual completed steps.
> Preserve my environment, resource settings, checkpoints and resume behavior.
> Do not restart existing jobs or launch additional training without my request.
> Verify service access and, when an authorized job runs, advancing progress and
> ETA. Tell me what is verified and what still needs a running job.
