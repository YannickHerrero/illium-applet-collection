import datetime
import http.server
import importlib.util
import json
import os
from pathlib import Path
import socket
import socketserver
import subprocess
import tempfile
import threading
import unittest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / 'agents.py'
spec = importlib.util.spec_from_file_location('agents', SCRIPT)
agents = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agents)

NOW = datetime.datetime(2026, 9, 21, 12, 0, tzinfo=datetime.timezone.utc)
WORKSPACE = '63190b5f-59ac-4658-a465-2d3822a96cc7'
TOKEN = 'mlt_test_token_that_must_never_be_printed'


def stamp(minutes_ago):
    return (NOW - datetime.timedelta(minutes=minutes_ago)).strftime('%Y-%m-%dT%H:%M:%SZ')


def herdr_agent(pane, title, status, workspace, kind='claude', cwd='/home/tester/dev/api'):
    return {'pane_id': pane, 'workspace_id': workspace, 'agent': kind, 'agent_status': status,
            'terminal_title': title, 'terminal_title_stripped': title, 'cwd': cwd, 'foreground_cwd': cwd}


class FakeHerdr(threading.Thread):
    """A herdr server socket answering session.snapshot from a fixture."""

    def __init__(self, path, snapshot):
        super().__init__(daemon=True)
        self.path, self.snapshot = path, snapshot
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(str(path))
        self.server.listen(4)
        self.server.settimeout(0.2)
        self.stopping = False
        self.requests = []

    def run(self):
        while not self.stopping:
            try:
                connection, _ = self.server.accept()
            except socket.timeout:
                continue
            with connection:
                connection.settimeout(1)
                data = b''
                while b'\n' not in data:
                    chunk = connection.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                self.requests.append(json.loads(data.decode()))
                if self.snapshot is not None:
                    reply = {'id': self.requests[-1]['id'], 'result': {'type': 'snapshot', 'snapshot': self.snapshot}}
                    connection.sendall((json.dumps(reply) + '\n').encode())

    def stop(self):
        self.stopping = True
        self.join()
        self.server.close()


class FakeMultica(http.server.BaseHTTPRequestHandler):
    routes = {}
    seen = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        FakeMultica.seen.append((self.path, self.headers.get('Authorization'), self.headers.get('X-Workspace-ID')))
        if self.headers.get('Authorization') != 'Bearer ' + TOKEN:
            self.send_response(401)
            self.end_headers()
            return
        body = FakeMultica.routes.get(self.path.split('?')[0])
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        payload = json.dumps(body).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(payload)


class AgentsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        (self.home / '.config/herdr').mkdir(parents=True)
        (self.home / '.multica').mkdir()
        self.herdr_servers = []
        self.http = None
        FakeMultica.routes = {}
        FakeMultica.seen = []

    def tearDown(self):
        for server in self.herdr_servers:
            server.stop()
        if self.http:
            self.http.shutdown()
            self.http.server_close()

    def start_herdr(self, snapshot, session='default'):
        path = self.home / '.config/herdr/herdr.sock' if session == 'default' else self.home / f'.config/herdr/sessions/{session}/herdr.sock'
        path.parent.mkdir(parents=True, exist_ok=True)
        server = FakeHerdr(path, snapshot)
        server.start()
        self.herdr_servers.append(server)
        return server

    def start_multica(self, tasks, agents, issues=()):
        self.http = socketserver.TCPServer(('127.0.0.1', 0), FakeMultica)
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        FakeMultica.routes = {'/api/agent-task-snapshot': tasks, '/api/agents': agents}
        for issue in issues:
            FakeMultica.routes['/api/issues/' + issue['id']] = issue
        (self.home / '.multica/config.json').write_text(json.dumps({
            'server_url': f'http://127.0.0.1:{self.http.server_address[1]}', 'workspace_id': WORKSPACE, 'token': TOKEN}))

    def collect(self):
        return agents.collect(str(self.home), NOW)

    def test_herdr_and_multica_cards_share_one_ordered_list(self):
        self.start_herdr({'workspaces': [{'workspace_id': 'wA', 'label': 'api', 'number': 1}, {'workspace_id': 'wB', 'number': 2}], 'agents': [
            herdr_agent('wA:p1', '◐ Rewrite the receipt formatter', 'working', 'wA'),
            herdr_agent('wA:p2', 'Token names', 'idle', 'wA', kind='pi'),
            herdr_agent('wB:p1', 'Drop the legacy table', 'blocked', 'wB', cwd=str(self.home)),
            herdr_agent('wB:p2', '', 'done', 'wB', kind='codex', cwd='/home/tester/dev/docs-site')]})
        yuqi, minnie = 'a1', 'a2'
        self.start_multica(tasks=[
            {'id': 't1', 'agent_id': yuqi, 'issue_id': '01a0c28d-1fa3-79ca-b27a-8b691be95f14', 'status': 'running', 'kind': 'comment', 'started_at': stamp(4)},
            {'id': 't2', 'agent_id': yuqi, 'issue_id': '01a0c28d-1fa3-79ca-b27a-8b691be95f14', 'status': 'completed', 'kind': 'comment', 'completed_at': stamp(60)},
            {'id': 't3', 'agent_id': minnie, 'issue_id': '01a0c28d-1fa3-79ca-b27a-8b691be95f00', 'status': 'running', 'kind': 'direct', 'started_at': stamp(30),
             'trigger_summary': '[@Minnie](mention://agent/a2) please review'},
            {'id': 't4', 'agent_id': 'a3', 'issue_id': '01a0c28d-1fa3-79ca-b27a-8b691be95f01', 'status': 'failed', 'kind': 'direct', 'completed_at': stamp(5)},
            {'id': 't5', 'agent_id': 'a4', 'issue_id': '01a0c28d-1fa3-79ca-b27a-8b691be95f02', 'status': 'queued', 'kind': 'direct', 'created_at': stamp(2)},
            {'id': 't6', 'agent_id': 'a4', 'issue_id': '01a0c28d-1fa3-79ca-b27a-8b691be95f02', 'status': 'waiting_local_directory', 'kind': 'direct', 'created_at': stamp(2)},
        ], agents=[{'id': yuqi, 'name': 'Yuqi'}, {'id': minnie, 'name': 'Minnie'}, {'id': 'a3', 'name': 'Shuhua'}, {'id': 'a4', 'name': 'Soyeon'}, {'id': 'a5', 'name': 'Miyeon'}],
            issues=[{'id': '01a0c28d-1fa3-79ca-b27a-8b691be95f14', 'identifier': 'DEV-100', 'title': 'Daily recap'}])
        data = self.collect()
        self.assertEqual((data['ok'], data['bar_label'], data['icon']), (True, '1', 'icon-attention.svg'))
        self.assertEqual(data['summary'], {'total': 6, 'waiting': 1, 'working': 3, 'done': 1, 'idle': 1, 'headline': '1 agent needs you'})
        self.assertEqual(data['sources'], [{'name': 'Herdr', 'state': 'ok', 'detail': '4 agents'}, {'name': 'Multica', 'state': 'ok', 'detail': '2 working'}])
        rows = [(c['source'], c['agent'], c['status'], c['title']) for c in data['cards']]
        # Only running Multica tasks are shown: no queued, waiting, finished or resting agent.
        self.assertEqual(rows, [
            ('herdr', 'Claude', 'waiting', 'Drop the legacy table'),
            ('herdr', 'Claude', 'working', 'Rewrite the receipt formatter'),
            ('multica', 'Minnie', 'working', 'Minnie please review'),
            ('multica', 'Yuqi', 'working', 'DEV-100  Daily recap'),
            ('herdr', 'Codex', 'done', 'docs-site'),
            ('herdr', 'Pi', 'idle', 'Token names'),
        ])
        blocked = data['cards'][0]
        self.assertEqual((blocked['label'], blocked['place'], blocked['detail']), ('needs you', 'Workspace 2', '~'))
        self.assertEqual(data['cards'][1]['place'], 'api')
        self.assertEqual(data['cards'][2]['detail'], 'direct  ·  started 30 min')
        self.assertEqual(data['cards'][3]['detail'], 'comment  ·  started 4 min')
        # Only issues of running tasks are looked up, once each, with the CLI's headers.
        issue_calls = [s for s in FakeMultica.seen if s[0].startswith('/api/issues/')]
        self.assertEqual(len(issue_calls), 2)
        self.assertTrue(all(s[1] == 'Bearer ' + TOKEN and s[2] == WORKSPACE for s in FakeMultica.seen))
        text = agents.dumps(data)
        self.assertNotIn(TOKEN, text)
        self.assertNotIn('mention://', text)

    def test_no_source_is_reported_without_failing(self):
        data = self.collect()
        self.assertEqual((data['ok'], data['bar_label'], data['icon'], data['cards']), (True, '', 'icon.svg', []))
        self.assertEqual(data['summary']['headline'], 'No source reachable')
        self.assertEqual([s['state'] for s in data['sources']], ['off', 'off'])

    def test_unanswering_herdr_and_unreachable_multica(self):
        self.start_herdr(None)
        (self.home / '.multica/config.json').write_text(json.dumps({'server_url': 'http://127.0.0.1:9', 'workspace_id': WORKSPACE, 'token': TOKEN}))
        data = self.collect()
        self.assertEqual(data['sources'], [{'name': 'Herdr', 'state': 'error', 'detail': 'no answer from the server'},
                                           {'name': 'Multica', 'state': 'error', 'detail': 'server unreachable'}])
        self.assertEqual(data['cards'], [])

    def test_named_sessions_prefix_the_workspace_and_working_drives_the_bar(self):
        self.start_herdr({'workspaces': [{'workspace_id': 'w1', 'label': 'api', 'number': 1}], 'agents': [herdr_agent('w1:p1', 'Build', 'working', 'w1')]})
        self.start_herdr({'workspaces': [{'workspace_id': 'w1', 'label': 'site', 'number': 1}], 'agents': [herdr_agent('w1:p1', 'Deploy', 'idle', 'w1')]}, session='3')
        data = self.collect()
        self.assertEqual((data['bar_label'], data['icon'], data['summary']['headline']), ('1', 'icon-active.svg', '1 agent working'))
        self.assertEqual([c['place'] for c in data['cards']], ['api', '3: site'])
        self.assertEqual(data['sources'][0]['detail'], '2 agents on 2 servers')

    def test_secrets_and_control_characters_never_reach_the_view(self):
        title = 'Use token: "sk-abcdefgh1234567890123456" \x1b[31mnow\x1b[0m ghp_abcdefghijklmnopqrstuvwxyz'
        self.start_herdr({'workspaces': [], 'agents': [herdr_agent('w:p', title, 'idle', 'w')]})
        card = self.collect()['cards'][0]
        self.assertEqual(card['title'], 'Use token: "[redacted]" now ghp_abcd…[redacted]')
        self.assertEqual(card['place'], 'Workspace ?')

    def test_output_stays_under_the_provider_limit(self):
        self.start_herdr({'workspaces': [], 'agents': [herdr_agent(f'w:p{i}', 'x' * 400, 'idle', 'w') for i in range(300)]})
        text = agents.dumps(self.collect())
        self.assertLessEqual(len(text.encode()), agents.OUTPUT_BYTE_CAP)
        self.assertLessEqual(len(json.loads(text)['cards']), agents.CARD_CAP)
        self.assertEqual(json.loads(text)['summary']['total'], 300)

    def test_script_runs_end_to_end_and_ignores_the_action(self):
        result = subprocess.run(['python3', str(SCRIPT), 'refresh'], env=dict(os.environ, HOME=str(self.home)), capture_output=True, text=True, timeout=30)
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        data = json.loads(result.stdout)
        self.assertEqual((data['ok'], data['cards']), (True, []))


if __name__ == '__main__':
    unittest.main()
