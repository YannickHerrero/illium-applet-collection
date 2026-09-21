#!/usr/bin/env python3
"""Every coding agent visible from WSL, as one JSON object for the Winarchy view.

Sources: the running herdr servers (their Unix sockets) and the Multica task
queue (the local server's REST API). Read-only: nothing is focused, cancelled
or killed, and the action argument Winarchy appends is ignored.

Winarchy runs this through `wsl.exe`, so it starts from a non-interactive
shell; every path used here is derived from $HOME.
"""
import datetime
import glob
import json
import os
import re
import socket
import sys
import urllib.error
import urllib.request

HERDR_TIMEOUT = 1.0
MULTICA_TIMEOUT = 2.0
RESPONSE_BYTE_CAP = 2 * 1024 * 1024
ISSUE_LOOKUP_CAP = 8
CARD_CAP = 60
TEXT_CAP = 160
# Winarchy reads at most 64 KiB from a provider; stay well under it.
OUTPUT_BYTE_CAP = 60 * 1024
DONE_WINDOW = datetime.timedelta(hours=2)

# One vocabulary for both sources, in display order.
STATUS_RANK = {'waiting': 0, 'working': 1, 'queued': 2, 'failed': 3, 'done': 4, 'idle': 5}
STATUS_WORD = {'waiting': 'needs you', 'working': 'working', 'queued': 'queued',
               'failed': 'failed', 'done': 'done', 'idle': 'ready'}
HERDR_STATUS = {'blocked': 'waiting', 'working': 'working', 'done': 'done', 'idle': 'idle'}
MULTICA_STATUS = {'running': 'working', 'queued': 'queued', 'dispatched': 'queued',
                  'deferred': 'queued', 'waiting_local_directory': 'waiting',
                  'completed': 'done', 'failed': 'failed'}
AGENT_NAMES = {'claude': 'Claude', 'codex': 'Codex', 'opencode': 'OpenCode', 'pi': 'Pi', 'omp': 'OMP',
               'grok': 'Grok', 'hermes': 'Hermes', 'copilot': 'Copilot', 'cursor': 'Cursor', 'gemini': 'Gemini'}


def now():
    return datetime.datetime.now(datetime.timezone.utc)


def redact(text):
    """Keys and tokens that agents sometimes echo into titles or prompts."""
    t = text
    t = re.sub(r'\b(sk-[A-Za-z0-9_-]{8})[A-Za-z0-9_-]{12,}\b', r'\1…[redacted]', t)
    t = re.sub(r'\b(ghp_[A-Za-z0-9]{4})[A-Za-z0-9]{16,}\b', r'\1…[redacted]', t)
    t = re.sub(r'\b(github_pat_[A-Za-z0-9_]{4})[A-Za-z0-9_]{16,}\b', r'\1…[redacted]', t)
    t = re.sub(r'\b(AKIA[0-9A-Z]{4})[0-9A-Z]{12}\b', r'\1…[redacted]', t)
    t = re.sub(r'(Bearer\s+)[A-Za-z0-9._~+/-]{16,}', r'\1[redacted]', t, flags=re.IGNORECASE)
    t = re.sub(r"((?:api[_-]?key|secret|token|password)\s*[:=]\s*['\"])[^'\"]{8,}(['\"])", r'\1[redacted]\2', t, flags=re.IGNORECASE)
    return t


def clean(text, cap=TEXT_CAP):
    """One line of plain text: no control characters, spinner glyphs or markup links."""
    t = str(text or '')
    t = re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', t)
    t = re.sub(r'\[([^\]]*)\]\(mention://[^)]*\)', r'\1', t)
    t = re.sub(r'[\x00-\x1f\x7f]+', ' ', t)
    # herdr puts a spinner glyph in front of a working agent's title.
    t = re.sub(r'^[^0-9A-Za-zÀ-ɏͰ-Ͽ一-鿿]+', '', t)
    t = re.sub(r'\s+', ' ', t).strip()
    t = redact(t)
    if len(t) > cap:
        t = t[:cap - 1].rstrip() + '…'
    return t


def short_path(path, home):
    if not path:
        return ''
    if path == home:
        return '~'
    if path.startswith(home + '/'):
        path = '~' + path[len(home):]
    return path


def elapsed(stamp, reference):
    """'3 min', '2 h', '5 d' since an RFC 3339 stamp, or '' when unreadable."""
    try:
        moment = datetime.datetime.fromisoformat(str(stamp).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return ''
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.timezone.utc)
    seconds = max(0, int((reference - moment).total_seconds()))
    if seconds < 60:
        return 'just now'
    if seconds < 3600:
        return f'{seconds // 60} min'
    if seconds < 86400:
        return f'{seconds // 3600} h'
    return f'{seconds // 86400} d'


def parse_stamp(stamp):
    try:
        moment = datetime.datetime.fromisoformat(str(stamp).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=datetime.timezone.utc)


def agent_name(kind):
    key = str(kind or '').lower()
    return AGENT_NAMES.get(key, key.capitalize() or 'Agent')


def card(source, agent, title, detail, status, place=''):
    return {'source': source, 'agent': agent, 'title': title, 'detail': detail, 'place': place,
            'status': status, 'label': STATUS_WORD[status]}


# ----------------------------------------------------------------- herdr

def herdr_sockets(home):
    """(session name, socket path) of every running herdr server."""
    sockets = []
    default = os.path.join(home, '.config/herdr/herdr.sock')
    if os.path.exists(default):
        sockets.append(('default', default))
    for path in sorted(glob.glob(os.path.join(home, '.config/herdr/sessions/*/herdr.sock'))):
        sockets.append((os.path.basename(os.path.dirname(path)), path))
    return sockets


def herdr_snapshot(path):
    """The live snapshot of one server, or None when it does not answer."""
    request = json.dumps({'id': 'winarchy:agent-orchestrator', 'method': 'session.snapshot', 'params': {}}) + '\n'
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(HERDR_TIMEOUT)
            sock.connect(path)
            sock.sendall(request.encode('utf-8'))
            data = b''
            while b'\n' not in data and len(data) < RESPONSE_BYTE_CAP:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                data += chunk
        reply = json.loads(data.decode('utf-8', errors='replace').split('\n', 1)[0])
        snapshot = reply.get('result', {}).get('snapshot')
        return snapshot if isinstance(snapshot, dict) else None
    except (OSError, ValueError, AttributeError):
        return None


def herdr_cards(home):
    """Cards for every agent pane of every running herdr server, plus the source line."""
    sockets = herdr_sockets(home)
    if not sockets:
        return [], {'name': 'Herdr', 'state': 'off', 'detail': 'not running'}
    cards, answered = [], 0
    for session, path in sockets:
        snapshot = herdr_snapshot(path)
        if snapshot is None:
            continue
        answered += 1
        workspaces = {w.get('workspace_id'): w for w in snapshot.get('workspaces', []) if isinstance(w, dict)}
        for agent in snapshot.get('agents', []):
            if not isinstance(agent, dict):
                continue
            workspace = workspaces.get(agent.get('workspace_id'), {})
            label = clean(workspace.get('label') or f"Workspace {workspace.get('number', '?')}", 40)
            if session != 'default':
                label = f'{session}: {label}'
            cwd = short_path(str(agent.get('foreground_cwd') or agent.get('cwd') or ''), home)
            title = clean(agent.get('terminal_title_stripped') or agent.get('terminal_title') or '')
            status = HERDR_STATUS.get(str(agent.get('agent_status') or ''), 'idle')
            cards.append(card('herdr', agent_name(agent.get('agent')), title or os.path.basename(cwd) or 'Agent',
                              cwd, status, label))
    if answered == 0:
        return [], {'name': 'Herdr', 'state': 'error', 'detail': 'no answer from the server'}
    detail = f'{len(cards)} agent' + ('' if len(cards) == 1 else 's')
    if answered > 1:
        detail += f' on {answered} servers'
    return cards, {'name': 'Herdr', 'state': 'ok', 'detail': detail}


# --------------------------------------------------------------- multica

class Multica:
    """Read-only client for the local Multica server, authenticated like the CLI."""

    def __init__(self, home):
        with open(os.path.join(home, '.multica/config.json'), encoding='utf-8') as handle:
            config = json.load(handle)
        self.server = str(config.get('server_url') or '').rstrip('/')
        self.workspace = str(config.get('workspace_id') or '')
        self.token = str(config.get('token') or '')
        if not (self.server.startswith('http://') or self.server.startswith('https://')) or not self.workspace or not self.token:
            raise ValueError('incomplete Multica configuration')
        if not re.fullmatch(r'[0-9a-fA-F-]{36}', self.workspace):
            raise ValueError('unexpected Multica workspace id')

    def get(self, path):
        request = urllib.request.Request(self.server + path, headers={
            'Authorization': 'Bearer ' + self.token, 'X-Workspace-ID': self.workspace, 'Accept': 'application/json'})
        with urllib.request.urlopen(request, timeout=MULTICA_TIMEOUT) as response:
            return json.loads(response.read(RESPONSE_BYTE_CAP).decode('utf-8'))


def multica_cards(home, reference):
    try:
        client = Multica(home)
    except (OSError, ValueError):
        return [], {'name': 'Multica', 'state': 'off', 'detail': 'not configured'}
    try:
        tasks = client.get('/api/agent-task-snapshot?workspace_id=' + client.workspace)
        agents = client.get('/api/agents')
    except (OSError, ValueError, urllib.error.URLError):
        return [], {'name': 'Multica', 'state': 'error', 'detail': 'server unreachable'}
    if not isinstance(tasks, list) or not isinstance(agents, list):
        return [], {'name': 'Multica', 'state': 'error', 'detail': 'unexpected answer'}
    names = {a.get('id'): clean(a.get('name'), 40) for a in agents if isinstance(a, dict)}

    active, outcomes = [], []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        status = MULTICA_STATUS.get(str(task.get('status') or ''))
        if status in ('done', 'failed'):
            outcomes.append(task)
        elif status:
            active.append(task)
    busy_agents = {t.get('agent_id') for t in active}
    # The snapshot carries each agent's last outcome as its "last activity";
    # an old one is just the agent resting, and a busy agent's is stale.
    for task in outcomes:
        finished = parse_stamp(task.get('completed_at'))
        if task.get('agent_id') in busy_agents:
            continue
        if finished is None or reference - finished > DONE_WINDOW:
            task['_status'] = 'idle'
        active.append(task)

    issues = {}
    for task in active:
        issue_id = str(task.get('issue_id') or '')
        if not issue_id or issue_id in issues or len(issues) >= ISSUE_LOOKUP_CAP:
            continue
        if not re.fullmatch(r'[0-9a-fA-F-]{36}', issue_id):
            continue
        try:
            issues[issue_id] = client.get('/api/issues/' + issue_id)
        except (OSError, ValueError, urllib.error.URLError):
            issues[issue_id] = None

    cards = []
    for task in active:
        status = task.get('_status') or MULTICA_STATUS[str(task.get('status'))]
        issue = issues.get(str(task.get('issue_id') or '')) or {}
        identifier = clean(issue.get('identifier'), 20)
        title = clean(issue.get('title')) or clean(task.get('trigger_summary')) or 'Task'
        if identifier:
            title = f'{identifier}  {title}'
        when = task.get('completed_at') if status in ('done', 'failed', 'idle') else (task.get('started_at') or task.get('created_at'))
        parts = [clean(task.get('kind'), 20)]
        if status == 'waiting':
            parts.append(clean(task.get('wait_reason'), 60) or 'waiting for a local directory')
        elif status == 'failed':
            parts.append(clean(task.get('failure_reason') or task.get('error'), 80))
        since = elapsed(when, reference)
        if since:
            parts.append(('finished ' if status in ('done', 'failed', 'idle') else 'started ') + since)
        detail = '  ·  '.join(p for p in parts if p)
        cards.append(card('multica', names.get(task.get('agent_id')) or 'Agent', title, detail, status))
    resting = [names[a] for a in names if a not in {t.get('agent_id') for t in active}]
    for name in sorted(resting):
        cards.append(card('multica', name, 'No task yet', '', 'idle'))
    detail = f'{len(names)} agent' + ('' if len(names) == 1 else 's')
    return cards, {'name': 'Multica', 'state': 'ok', 'detail': detail}


# --------------------------------------------------------------- output

def plural(count, word):
    return f'{count} {word}' + ('' if count == 1 else 's')


def assemble(cards, sources):
    cards.sort(key=lambda c: (STATUS_RANK[c['status']], c['source'], c['agent'].lower(), c['title'].lower()))
    counts = {status: sum(1 for c in cards if c['status'] == status) for status in STATUS_RANK}
    waiting, working = counts['waiting'], counts['working'] + counts['queued']
    if waiting:
        headline, icon, bar_label = f'{plural(waiting, "agent")} need you', 'icon-attention.svg', str(waiting)
    elif working:
        headline, icon, bar_label = f'{plural(working, "agent")} working', 'icon-active.svg', str(working)
    elif counts['failed']:
        headline, icon, bar_label = f'{plural(counts["failed"], "task")} failed', 'icon-attention.svg', ''
    elif counts['done']:
        headline, icon, bar_label = f'{plural(counts["done"], "agent")} done', 'icon.svg', ''
    elif cards:
        headline, icon, bar_label = f'{plural(len(cards), "agent")} idle', 'icon.svg', ''
    else:
        headline, icon, bar_label = 'No agents', 'icon.svg', ''
    if all(s['state'] != 'ok' for s in sources):
        headline = 'No source reachable'
    summary = {'total': len(cards), 'waiting': waiting, 'working': working, 'done': counts['done'] + counts['failed'],
               'idle': counts['idle'], 'headline': headline}
    return {'ok': True, 'error': '', 'bar_label': bar_label, 'icon': icon, 'summary': summary,
            'sources': sources, 'cards': cards[:CARD_CAP]}


def dumps(payload):
    text = json.dumps(payload, ensure_ascii=False)
    while len(text.encode('utf-8')) > OUTPUT_BYTE_CAP and payload['cards']:
        payload['cards'].pop()
        text = json.dumps(payload, ensure_ascii=False)
    return text


def collect(home, reference=None):
    reference = reference or now()
    herdr, herdr_source = herdr_cards(home)
    multica, multica_source = multica_cards(home, reference)
    return assemble(herdr + multica, [herdr_source, multica_source])


def main():
    home = os.path.expanduser('~')
    try:
        payload = collect(home)
    except Exception as error:  # a broken poll must still leave a readable popup
        payload = {'ok': False, 'error': f'{type(error).__name__}: {error}', 'bar_label': '', 'icon': 'icon.svg',
                   'summary': {'total': 0, 'waiting': 0, 'working': 0, 'done': 0, 'idle': 0, 'headline': ''},
                   'sources': [], 'cards': []}
    sys.stdout.write(dumps(payload) + '\n')


if __name__ == '__main__':
    main()
