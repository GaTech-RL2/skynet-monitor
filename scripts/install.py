#!/usr/bin/env python3
"""Install a per-user monitor on a Linux Slurm login node (no sudo)."""
import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys


def quote(value):
    # systemd specifiers must be escaped even inside quoted arguments.
    return '"' + str(value).replace('%', '%%').replace('\\', '\\\\').replace('"', '\\"') + '"'


def install(home, source, port=None, configure_only=False, gpu=True, training_only=False):
    home, source = Path(home).resolve(), Path(source).resolve()
    app = home / '.local/share/skynet-monitor'
    state = home / '.local/state/skynet-monitor'
    unit = home / '.config/systemd/user/skynet-monitor.service'
    config = state / 'installation.json'
    for directory in (app, state, unit.parent):directory.mkdir(parents=True,exist_ok=True)
    state.chmod(0o700)
    if port is None and config.exists():port=json.loads(config.read_text())['port']
    if port is None:
        # Each user chooses an available port; nothing changes another user's service.
        for candidate in range(18000 + os.getuid() % 10000, 65536):
            try:
                with socket.socket() as sock:sock.bind(('127.0.0.1', candidate))
                port=candidate;break
            except OSError:continue
    if port is None or not 1 <= port <= 65535:raise ValueError('No valid port available')
    key = state / 'access.key'
    if not key.exists():
        fd=os.open(key,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as handle:handle.write(secrets.token_urlsafe(32)+'\n')
    key.chmod(0o600)
    for file in (source / 'skynet_monitor').iterdir():
        if file.suffix in {'.py','.html'} and not file.name.startswith('test_'):
            shutil.copy2(file, app / file.name)
    command=[sys.executable,str(app/'server.py'),'--port',str(port),'--access-key-file',str(key),'--snapshot-file',str(state/'snapshot.json')]
    if not gpu:command.append('--no-gpu-telemetry')
    if training_only:command.append('--training-only')
    text='[Unit]\nDescription=Skynet Monitor\nAfter=network.target\n\n[Service]\nType=simple\n'
    text+='WorkingDirectory='+quote(app)+'\nExecStart='+ ' '.join(map(quote,command))+'\n'
    text+='Restart=always\nRestartSec=10\nUMask=0077\nEnvironment=PYTHONDONTWRITEBYTECODE=1\n'
    text+='\n[Install]\nWantedBy=default.target\n'
    unit.write_text(text)
    config.write_text(json.dumps(dict(port=port,app=str(app)),indent=2))
    if not configure_only:
        subprocess.run(['systemctl','--user','daemon-reload'],check=True)
        subprocess.run(['systemctl','--user','enable','skynet-monitor'],check=True)
        subprocess.run(['systemctl','--user','restart','skynet-monitor'],check=True)
        subprocess.run(['systemctl','--user','is-active','skynet-monitor'],check=True)
    return dict(port=port,key=str(key),unit=str(unit))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int)
    parser.add_argument('--configure-only',action='store_true',help='Write files without starting systemd')
    parser.add_argument('--no-gpu-telemetry',action='store_true')
    parser.add_argument('--training-only',action='store_true')
    args=parser.parse_args()
    result=install(Path.home(),Path(__file__).resolve().parents[1],args.port,args.configure_only,not args.no_gpu_telemetry,args.training_only)
    print('Installed:',result['unit'])
    print('Port:',result['port'])
    print('Read your login key with: cat',result['key'])
    print('From your laptop: ssh -N -L {0}:127.0.0.1:{0} YOUR_SKYNET_SSH_HOST'.format(result['port']))
    print('Then open http://127.0.0.1:{}/'.format(result['port']))
    print('For collection after logout, enable lingering if permitted: loginctl enable-linger "$USER"')
