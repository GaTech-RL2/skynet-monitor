"""Local-only HTTP UI with a shared, bounded SSH poller (stdlib only)."""
import argparse
import hmac
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import threading
import time
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs
from http.cookies import SimpleCookie
from progress import estimate

ROOT = Path(__file__).resolve().parent
state = dict(data=None, error=None, refreshing=True)
lock = threading.Lock()
detail_lock = threading.Lock()
details = {}
progress_samples = {}


def collect(job=None):
    env = dict(os.environ, SKYNET_TRAINING_ONLY='1' if args.training_only else '0',
               SKYNET_GPU_TELEMETRY='0' if args.no_gpu_telemetry else '1')
    invocation = [sys.executable, str(ROOT / 'collector.py')] + ([job] if job else [])
    invocation = ['bash', '-lc', 'exec ' + shlex.join(invocation)]
    p = subprocess.run(invocation, cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=90)
    if p.returncode:
        raise RuntimeError(p.stderr[-1800:] or 'SSH collector failed')
    return json.loads(p.stdout)


def poll():
    while True:
        with lock:
            state['refreshing'] = True
        try:
            data = collect()
            active = {j['id'] for j in data['jobs']}
            for job_id in list(progress_samples):
                if job_id not in active:
                    del progress_samples[job_id]
            for job in data['jobs']:
                estimate(job.setdefault('progress', {}), progress_samples.setdefault(job['id'], []), time.time())
            with lock:
                state.update(data=data, error=None)
            if args.snapshot_file:
                target = Path(args.snapshot_file)
                temporary = target.with_suffix('.tmp')
                temporary.write_text(json.dumps(data))
                temporary.chmod(0o600)
                temporary.replace(target)
        except Exception as e:
            with lock:
                state['error'] = str(e)
        finally:
            with lock:
                state['refreshing'] = False
        time.sleep(args.interval)


class Handler(BaseHTTPRequestHandler):
    def authorized(self):
        if not access_key:
            return True
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get('Cookie', ''))
            value = cookie['skynet_access'].value if 'skynet_access' in cookie else ''
            return hmac.compare_digest(value, access_key)
        except Exception:
            return False

    def do_POST(self):
        if self.headers.get('Host') not in allowed_hosts or self.path != '/login':
            self.send_error(403)
            return
        try:
            size = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            self.send_error(400)
            return
        if not 0 < size < 4096:
            self.send_error(400)
            return
        value = parse_qs(self.rfile.read(size).decode()).get('key', [''])[0]
        if not access_key or not hmac.compare_digest(value, access_key):
            self.send_error(403, 'Invalid access key')
            return
        self.send_response(303)
        self.send_header('Set-Cookie', 'skynet_access=' + access_key + '; HttpOnly; SameSite=Strict; Path=/')
        self.send_header('Location', '/')
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_GET(self):
        # Reject DNS rebinding; never expose arbitrary remote commands or file paths.
        if self.headers.get('Host') not in allowed_hosts:
            self.send_error(403)
            return
        path = urlsplit(self.path).path
        if not self.authorized():
            if path != '/':
                self.send_error(401)
                return
            body = (ROOT / 'login.html').read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        code, mime = 200, 'application/json; charset=utf-8'
        if path == '/':
            body, mime = (ROOT / 'index.html').read_bytes(), 'text/html; charset=utf-8'
        elif path == '/api/snapshot':
            with lock:
                body = json.dumps(state).encode()
        elif re.fullmatch(r'/api/job/\d+(?:_\d+)?', path):
            job = path.rsplit('/', 1)[1]
            with lock:
                owned = any(j['id'] == job for j in (state.get('data') or {}).get('jobs', []))
            if not owned:
                self.send_error(404)
                return
            try:
                with detail_lock:
                    old = details.get(job)
                    if not old or time.monotonic() - old[0] > 30:
                        details[job] = (time.monotonic(), collect(job))
                    body = json.dumps(details[job][1]).encode()
            except Exception as e:
                code, body = 502, json.dumps(dict(error=str(e))).encode()
        else:
            self.send_error(404)
            return
        self.send_response(code)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=18790)
    parser.add_argument('--interval', type=int, default=30)
    parser.add_argument('--local', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--no-gpu-telemetry', action='store_true', help='Disable allocation GPU sampling')
    parser.add_argument('--training-only', action='store_true')
    parser.add_argument('--listen', default='127.0.0.1')
    parser.add_argument('--allowed-host', action='append', default=[])
    parser.add_argument('--access-key-file', required=True)
    parser.add_argument('--snapshot-file')
    args = parser.parse_args()
    if args.interval < 15 or not 1 <= args.port <= 65535:
        parser.error('Port must be valid; interval must be >=15 seconds')
    access_key = Path(args.access_key_file).read_text().strip() if args.access_key_file else None
    if not access_key or len(access_key) < 24:
        parser.error('An access key of at least 24 characters is required')
    allowed_hosts = {f'127.0.0.1:{args.port}', f'localhost:{args.port}', *args.allowed_host}
    if args.snapshot_file and Path(args.snapshot_file).exists():
        try:
            state['data'] = json.loads(Path(args.snapshot_file).read_text())
            state['error'] = 'Service restarted; awaiting fresh collection'
        except (OSError, ValueError):
            pass
    server = ThreadingHTTPServer((args.listen, args.port), Handler)
    threading.Thread(target=poll, daemon=True).start()
    print(f'Skynet Monitor: http://127.0.0.1:{args.port}', flush=True)
    server.serve_forever()
