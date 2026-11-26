# Agent entry point

For helping a user install the monitor or integrate their training, read
[README.md](README.md), then [TRAINING.md](TRAINING.md). The exact progress
contract is [PROGRESS.md](PROGRESS.md). These docs are self-contained; no access
to the original author's experiments or conversation is needed.

Use the user's own SSH host, account, paths, environment and Slurm resources.
Do not copy example resource choices into a real training submission without
checking the user's existing launcher. Installing the monitor does not submit
training or change launchers. Preserve existing training behavior and checkpoints.
Do not restart running jobs merely to add monitoring.

Prefer standard progress reporting for new integrations. Static chain discovery
is a compatibility adapter for the documented config/metrics layout, not a
universal shell parser. Never infer completed work from elapsed time or choose
the newest metrics file in a directory. Keep access keys, private SSH keys,
real job snapshots and private paths out of commits.

For development, follow CONTRIBUTING.md and run the two unittest discovery
commands in README.md. For user onboarding, follow TRAINING.md's verification
steps and report which steps were actually verified on their cluster.
