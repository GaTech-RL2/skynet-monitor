"""ETA from observed metric advances, including time spent between updates."""


def estimate(progress, samples, now):
    if 'step' not in progress:
        samples.clear()
        return
    step, target, timestamp = progress['step'], progress['target'], progress['updated']
    signature = (target, progress.get('unit'), progress.get('stage') if progress.get('adapter') == 'progress.json' else None, progress.get('attempt_id'))
    progress['eta_seconds'] = None
    progress.pop('estimated_finish', None)
    progress.pop('steps_per_second', None)
    if progress.get('eta_mode') == 'none':
        samples.clear()
        return
    progress['stale'] = now - timestamp > 300
    if samples and (step < samples[-1][1] or signature != samples[-1][2]):
        samples.clear()
    if not samples or (step > samples[-1][1] and timestamp > samples[-1][0]):
        samples.append((timestamp, step, signature))
    while len(samples) > 2 and samples[-1][0] - samples[0][0] > 600:
        samples.pop(0)
    if samples and now - samples[-1][0] > 300:
        progress['stale'] = True
    if progress['stale'] or step >= target or len(samples) < 2:
        return
    duration = samples[-1][0] - samples[0][0]
    delta = samples[-1][1] - samples[0][1]
    if duration >= 30 and delta > 0:
        progress['steps_per_second'] = delta / duration
        progress['eta_seconds'] = (target - step) * duration / delta
        progress['estimated_finish'] = now + progress['eta_seconds']
