#!/usr/bin/env python3
"""Read Fable through Claude Code's experimental control API, never through credentials."""
import argparse
import datetime
import fcntl
import json
import math
import os
from pathlib import Path
import selectors
import signal
import subprocess
import tempfile
import time

INTERVAL = 300
TIMEOUT = 20
MAX_OUTPUT = 1024 * 1024


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def extract(limits, now):
    if not isinstance(limits, dict):
        return None
    # Prefer the named projection; older/headless versions expose only raw limits[].
    for key in ('model_scoped', 'limits'):
        rows = limits.get(key)
        if not isinstance(rows, list):
            continue
        matches = []
        for row in rows[:128]:
            if not isinstance(row, dict):
                continue
            if key == 'model_scoped':
                name, used = row.get('display_name'), row.get('utilization')
            else:
                if row.get('kind') != 'weekly_scoped' or row.get('is_active') is False:
                    continue
                scope = row.get('scope')
                model = scope.get('model') if isinstance(scope, dict) else None
                name = model.get('display_name') if isinstance(model, dict) else None
                used = row.get('percent')
            if not isinstance(name, str) or name.casefold() != 'fable':
                continue
            reset = row.get('resets_at')
            if isinstance(reset, str):
                try:
                    date = datetime.datetime.fromisoformat(reset.replace('Z', '+00:00'))
                    reset = date.timestamp() if date.tzinfo else None
                except ValueError:
                    continue
            if not number(used) or not 0 <= used <= 100 or not number(reset) or not now < reset <= now + 8 * 86400:
                continue
            matches.append({'used_percentage': used, 'resets_at': int(reset), 'received_at': int(now)})
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            return None  # Do not guess between different Fable buckets.
    return None


def query(claude, timeout=TIMEOUT):
    command = [claude, '--print', '--input-format', 'stream-json', '--output-format', 'stream-json',
               '--verbose', '--no-session-persistence', '--setting-sources', '',
               '--settings', '{"disableAllHooks":true,"remoteControlAtStartup":false}',
               '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}', '--tools', '']
    with tempfile.TemporaryDirectory(prefix='illium-quota-') as directory:
        process = subprocess.Popen(command, cwd=directory, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, start_new_session=True,
                                   # CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC must stay unset: it also
                                   # stops the usage request, leaving only a stale interactive cache.
                                   env={**os.environ, 'DISABLE_AUTOUPDATER': '1'})
        reader = selectors.DefaultSelector()
        reader.register(process.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + timeout
        buffer = b''
        total = 0
        def request(request_id, body):
            nonlocal buffer, total
            process.stdin.write((json.dumps({'type': 'control_request', 'request_id': request_id, 'request': body}) + '\n').encode())
            process.stdin.flush()
            while time.monotonic() < deadline:
                while b'\n' in buffer:
                    line, buffer = buffer.split(b'\n', 1)
                    try:
                        message = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(message, dict) or message.get('type') != 'control_response':
                        continue
                    response = message.get('response', {})
                    if not isinstance(response, dict) or response.get('request_id') != request_id:
                        continue
                    if response.get('subtype') != 'success':
                        raise ValueError('Claude Code rejected the quota control request')
                    return response.get('response', {})
                if not reader.select(max(0, deadline - time.monotonic())):
                    break
                chunk = os.read(process.stdout.fileno(), 65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_OUTPUT:
                    raise ValueError('Claude Code quota output exceeds 1 MiB')
                buffer += chunk
            raise TimeoutError('Claude Code quota request did not complete')
        try:
            request('init', {'subtype': 'initialize'})
            data = request('usage', {'subtype': 'get_usage', 'skip_behaviors': True})
            return data.get('rate_limits') if isinstance(data, dict) else None
        finally:
            reader.close()
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            process.stdin.close()
            process.stdout.close()


def read_json(path):
    try:
        with path.open('rb') as stream:
            data = stream.read(8193)
        result = json.loads(data) if len(data) <= 8192 else {}
        return result if isinstance(result, dict) else {}
    except (OSError, ValueError):
        return {}


def atomic_json(path, data):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, prefix='.fable-', delete=False) as stream:
            temporary = stream.name
            json.dump(data, stream, allow_nan=False, separators=(',', ':'))
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def collect(directory, claude):
    directory.mkdir(parents=True, exist_ok=True)
    attempt = directory / 'fable-attempt.json'
    snapshot = directory / 'fable.json'
    with (directory / 'fable.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        now = time.time()
        last = read_json(attempt).get('attempted_at', 0)
        if number(last) and 0 <= now - last < INTERVAL:
            return
        atomic_json(attempt, {'attempted_at': int(now)})
        old = read_json(snapshot)
        try:
            window = extract(query(claude), time.time())
            if window is None:
                return  # Preserve the old value's age; never replace failure with 0%.
            previous = old.get('window', {})
            # The experimental API may silently return a cached server response.
            # Do not make unchanged data look newly verified on each probe.
            if isinstance(previous, dict) and all(previous.get(k) == window[k] for k in ('used_percentage', 'resets_at')):
                return
            atomic_json(snapshot, {'schema': 1, 'source': 'claude-code-usage', 'window': window})
        except (OSError, ValueError, TimeoutError):
            return


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--claude', required=True)
    args = parser.parse_args()
    collect(args.directory, args.claude)


if __name__ == '__main__':
    main()
