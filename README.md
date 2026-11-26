# Skynet Monitor

A small, self-hosted dashboard for **your running Slurm jobs**. Designed for
Skynet users; configurable for other Linux Slurm clusters. Python standard
library only, with an English interface and no frontend build step.

- Automatically discovers the current Linux user's running jobs and array tasks.
- Progress, recent-rate ETA, elapsed time, nodes, partitions and bounded log tails.
- Allocated GPU model/count, sampled GPU utilization and task-attributed VRAM.
- Generic `progress.json` reporting for training, processing or evaluation.
- Optional config/JSONL adapter and training sidecar for existing workflows.
- A per-user systemd service keeps collecting after your laptop disconnects.

This is an independent community project, not an official cluster service.
No dataset-specific adapters, batch dashboards or private experiment assets
are included. Installing it does not modify your job launchers.

## Requirements

On the login node: Linux, Python 3.10+, Bash, `squeue`, `scontrol`, and user
systemd. Slurm commands must resolve in a login shell. You need permission to
run a lightweight user service on your cluster. For GPU telemetry: NVIDIA
`nvidia-smi`, readable Slurm process cgroups, and permission to create overlapping
steps in your own running allocations. You can disable telemetry during install.

## Install on Skynet

SSH to your usual login node, then:

```bash
git clone https://github.com/GaTech-RL2/skynet-monitor.git
cd skynet-monitor
python3 scripts/install.py
loginctl enable-linger "$USER"
```

The installer selects an available local port and prints it. Each user gets
separate code, state, key and systemd unit in their own home directory. There is
no shared administrator account. If a port conflicts later, reinstall with
`python3 scripts/install.py --port YOUR_PORT` using an available port.

`enable-linger` keeps your user service alive after logout and starts it on boot.
If your site denies this, ask the cluster administrator; do not assume logout
persistence. Installation itself needs no sudo. Validate after a host reboot.
The service runs only on the login node where you started it; use that same
node for your SSH tunnel.

Optional installation flags:

```bash
python3 scripts/install.py --no-gpu-telemetry
python3 scripts/install.py --training-only
```

Default: all RUNNING jobs. `--training-only` selects recognized training names
plus jobs with valid standard progress. Customize the name patterns with
`SKYNET_TRAIN_INCLUDE` / `SKYNET_TRAIN_EXCLUDE` in a systemd environment override.
A missing progress file never prevents a job appearing in default mode.

## Open from your computer

Replace `PORT` with the printed port and `YOUR_SKYNET_HOST` with your normal
SSH host or alias:

```bash
ssh -N -L PORT:127.0.0.1:PORT YOUR_SKYNET_HOST
```

Open `http://127.0.0.1:PORT/`. Retrieve your generated access key on the login
node and enter it in the page (this is **not** your account password):

```bash
cat ~/.local/state/skynet-monitor/access.key
```

The server binds loopback by default. Keep the SSH tunnel open while viewing.
Closing it does not stop remote collection. SSH key rotation, sleep and network
changes may require reconnecting. Never copy a laptop's private SSH key to the
cluster. Public Internet hosting and TLS termination are outside this installer.

## Progress and ETA

Jobs appear automatically. Exact progress requires a reported total and completed
count; the monitor cannot infer these reliably for arbitrary programs.

```bash
python3 ~/.local/share/skynet-monitor/report_progress.py \
  --completed 200 --total 10000 --unit steps --kind training
```

Run that **inside the job** after successful work. It derives the Slurm job ID
and array identity automatically. For efficient in-process reporting and the
complete schema/discovery rules, see [PROGRESS.md](PROGRESS.md).

Existing jobs with `configs/<job-name>.json` containing matching `id` and `steps`,
and `runs/<job-name>/metrics.jsonl` containing `step`, work without changes.
If a wrapper job name differs from the run ID, explicitly bind the job to its
actual configuration (no training restart required):

```bash
python3 ~/.local/share/skynet-monitor/bind_run.py \
  --job-id YOUR_JOB_ID --config /path/to/campaign/configs/actual-run.json
```

For future submissions, call the same command inside your batch script without
`--job-id`; Slurm identity is detected automatically. A per-job `run.json`
binding points to the exact configuration and its `runs/<id>/metrics.jsonl`.
Identity is checked before reading; standard `progress.json` still has priority.

An optional `auto_report.py --pid CHILD_PID --config CONFIG.json` sidecar can
watch this layout; it exits when the workload exits and never signals it.

ETA is based on recent progress, not a promise. Initial estimates need two
advances spanning at least 30 seconds. Stale progress suppresses ETA. Requeues,
stage/target changes and counter rollback reset the estimate. Final validation,
checkpointing, queued work and retries may extend completion time.

## GPU measurements

The GPU column uses actual `AllocTRES`, not the requested hardware. A generic
allocation may have an unknown model; it is never guessed from a node name.

- **Load:** sampled whole-device utilization. Shared-device load can include
  other work; this is not per-process utilization or a 30-second average.
- **VRAM:** memory attributed to this job's GPU processes / device capacity,
  matched using process cgroup job IDs and GPU UUIDs.
- GPU indices are local to the query's allocation, not physical node slot IDs.
- No attributable process, unavailable access, CPU-only and unsupported
  multi-node telemetry are handled explicitly. An unavailable reading is not 0%.

Every poll may create a short **read-only overlapping Slurm step** in each
visible GPU job, running two `nvidia-smi` queries. It does not submit training
jobs or request extra GPUs, but has small CPU/Slurm accounting overhead. At most
six queries run concurrently; each has bounded startup/execution time. Set
`--no-gpu-telemetry` if site policy or your workload cannot tolerate these steps.
MIG/MPS layouts are not validated. Current support targets single-node NVIDIA jobs.

## Manage and update

```bash
systemctl --user status skynet-monitor
journalctl --user -u skynet-monitor -n 50
systemctl --user restart skynet-monitor
systemctl --user disable --now skynet-monitor
```

To update: `git pull --ff-only`, then rerun the installer with your desired flags.
The selected port and access key are preserved. Existing launcher hooks are not
installed, changed or removed. State and logs stay outside the source checkout.

Without systemd, run directly on the login node:

```bash
python3 scripts/install.py --configure-only
python3 skynet_monitor/server.py --port 18790 \
  --access-key-file ~/.local/state/skynet-monitor/access.key
```

Direct mode is loopback-only by default and requires an access key, including on
multi-user login nodes. The process must stay alive for collection to continue.

## Development

```bash
python3 -B -m unittest discover -s skynet_monitor -p 'test_*.py'
python3 -B -m unittest discover -s tests -p 'test_*.py'
```

Tests use synthetic fixtures, not a live cluster. See [CONTRIBUTING.md](CONTRIBUTING.md).
License: [MIT](LICENSE).
