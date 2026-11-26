"""Conservative static configuration discovery from Slurm's submitted script.

This is not a shell interpreter. Never execute or source submitted script text.
"""
import re
import shlex
from pathlib import Path
from protocol import read_regular_json


def expand(value, variables):
    def replace(match):
        name=match[1] or match[2]
        if name not in variables:raise ValueError('Unresolved variable: '+name)
        return variables[name]
    result=re.sub(r'\$\{([A-Za-z_]\w*)\}|\$([A-Za-z_]\w*)',replace,value)
    if any(c in result for c in '$`*?[]{}~\n'):
        raise ValueError('Dynamic shell expressions are not supported')
    return result


def discover_config(script, workdir):
    if len(script.encode())>65536:raise ValueError('Submitted script exceeds 64 KiB')
    variables={'SLURM_SUBMIT_DIR':str(workdir)}
    cwd=Path(workdir)
    candidates=set()
    expected=None
    executed=False
    for raw in script.replace('\\\n',' ').splitlines():
        line=raw.strip()
        if not line or line.startswith('#'):continue
        if executed:raise ValueError('Multiple commands or post-launch assignments are ambiguous')
        # Refuse branching/loops, substitutions and shell metacharacters. A static
        # export before a branch is not proof of the configuration actually used.
        if re.match(r'(if|elif|else|fi|for|while|until|case|function|select)\b',line):
            raise ValueError('Conditional or dynamic wrapper; report progress.json instead')
        if any(c in line for c in '`;&|<>') or '$(' in line or ('\'' in line and '$' in line):
            raise ValueError('Dynamic wrapper; report progress.json instead')
        words=shlex.split(line,comments=True)
        if not words:continue
        if words[0] in {'set','unset','source','.'}:
            if words[0] in {'unset','source','.'}:raise ValueError('Wrapper changes environment dynamically')
            continue
        assignment=words[1:] if words[0] in {'export','readonly'} else words
        if assignment and all(re.match(r'^[A-Za-z_]\w*=',w) for w in assignment):
            for word in assignment:
                name,value=word.split('=',1)
                variables[name]=expand(value,variables)
            continue
        if words[0]=='cd':
            if len(words)!=2:raise ValueError('Unsupported cd')
            path=Path(expand(words[1],variables))
            cwd=path if path.is_absolute() else cwd/path
            continue
        # Only recognize explicit config arguments on a single execution command.
        if words[0]=='exec':words=words[1:]
        if not words:raise ValueError('Empty execution command')
        if not re.search(r'(?:^|/)(?:python[0-9.]*|bash|sh)$',words[0]) and not words[0].startswith('$'):
            raise ValueError('Unrecognized command in wrapper')
        executed=True
        for i,word in enumerate(words):
            value=None
            if word=='--config' and i+1<len(words):value=words[i+1]
            elif word.startswith('--config='):value=word.split('=',1)[1]
            if value is not None:
                path=Path(expand(value,variables))
                candidates.add(path if path.is_absolute() else cwd/path)
        # Other arguments may reference script arguments, but configuration may not.
    if not executed:raise ValueError('No execution command in wrapper')
    if 'CAMPAIGN_ROOT' in variables and 'RUN_ID' in variables:
        run_id=variables['RUN_ID']
        if not run_id or '/' in run_id or run_id in {'.','..'}:raise ValueError('Invalid run ID')
        root=Path(variables['CAMPAIGN_ROOT'])
        root=root if root.is_absolute() else cwd/root
        candidates.add(root/'configs'/(run_id+'.json'))
        expected=run_id
    if len(candidates)!=1:raise ValueError('No unique static configuration in submitted script')
    path=next(iter(candidates)).resolve()
    if path.parent.name!='configs' or path.suffix!='.json':raise ValueError('Unsupported config/metrics layout')
    config=read_regular_json(path)
    run_id=config.get('id') if isinstance(config,dict) else None
    if not isinstance(run_id,str) or not run_id or '/' in run_id or run_id in {'.','..'}:
        raise ValueError('Invalid configuration identity')
    if expected is not None and expected!=run_id:raise ValueError('Wrapper/config identity mismatch')
    if type(config.get('steps')) is not int or config['steps']<=0:raise ValueError('Invalid step target')
    return path,run_id
