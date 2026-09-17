import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / 'herdr-agents.sh'


def snapshot(version, workspaces, agents):
    """workspaces: list of labels; agents: (title, status, workspace index) tuples."""
    return {'id': 'cli:api:snapshot', 'result': {'snapshot': {
        'version': version,
        'workspaces': [{'workspace_id': f'w{i}', 'label': label, 'number': i + 1, 'tab_count': i + 1} for i, label in enumerate(workspaces)],
        'agents': [{'pane_id': f'w{ws}:p{i}', 'workspace_id': f'w{ws}', 'agent': 'claude', 'agent_status': status, 'terminal_title': title,
                    'terminal_title_stripped': title} for i, (title, status, ws) in enumerate(agents)]}}}


class AgentsScriptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fixtures = self.root / 'fixtures'
        self.fixtures.mkdir()
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        shutil.copy(HERE / 'fake-herdr', self.bin / 'herdr')
        self.home = self.root / 'home'
        (self.home / '.config/herdr/sessions/9').mkdir(parents=True)
        (self.home / '.config/herdr/sessions/7').mkdir(parents=True)

    def run_script(self, *args, without_herdr=False):
        env = dict(os.environ, FAKE_HERDR_DIR=str(self.fixtures), HOME=str(self.home))
        env['PATH'] = ('' if without_herdr else f'{self.bin}:') + '/usr/bin:/bin'
        result = subprocess.run(['bash', str(SCRIPT), *args], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        return json.loads(result.stdout)

    def write_sessions(self, *rows):
        (self.fixtures / 'sessions.json').write_text(json.dumps({'sessions': [
            {'name': name, 'default': name == 'default', 'running': running,
             'session_dir': str(self.home / ('.config/herdr' if name == 'default' else f'.config/herdr/sessions/{name}')),
             'socket_path': ''} for name, running in rows]}))

    def write_snapshot(self, name, *args):
        (self.fixtures / f'snapshot-{name}.json').write_text(json.dumps(snapshot(*args), ensure_ascii=False))

    def test_one_card_per_workspace_then_stopped_sessions(self):
        self.write_sessions(('9', False), ('default', True), ('7', False), ('bad name!', True))
        self.write_snapshot('default', '0.8.0', ['checkout-service', 'billing-api', 'docs-site', 'scratch'], [
            ('Token names for the new palette', 'idle', 0), ('◐ Rewrite the receipt formatter', 'working', 0), ('', 'working', 0),
            ('Drop the legacy invoice table', 'blocked', 1),
            ('Upgrade the search index', 'done', 2), ('π - anchors', 'done', 2)])
        (self.home / '.config/herdr/sessions/7/session.json').write_text(json.dumps({'workspaces': [
            {'identity_cwd': str(self.home)}, {'custom_name': 'Named'}, {'identity_cwd': '/srv/api'}]}))
        data = self.run_script('refresh')
        self.assertEqual((data['ok'], data['error']), (True, ''))
        self.assertEqual(data['title'], 'Herdr (1 server, 6 agents)')
        self.assertEqual(data['bar_label'], '!1')
        cards = data['cards']
        self.assertEqual([c['title'] for c in cards], ['checkout-service', 'billing-api', 'docs-site', 'scratch', 'Workspace 7', 'Workspace 9'])
        first = cards[0]
        self.assertEqual((first['subtitle'], first['attention'], first['summary'], first['agent_count'], first['active']),
                         ('Workspace 1  ·  1 tab', 'working', '2 working', '3 agents', True))
        self.assertEqual([(a['title'], a['label']) for a in first['agents']],
                         [('Rewrite the receipt formatter', 'working'), ('Token names for the new palette', 'ready')])
        self.assertEqual((cards[1]['attention'], cards[1]['summary'], cards[1]['agent_count'], cards[1]['agents'][0]['label']),
                         ('blocked', '1 needs you', '1 agent', 'needs you'))
        self.assertEqual((cards[2]['attention'], cards[2]['summary'], cards[2]['agents'][1]['title']), ('done', '2 done', 'π - anchors'))
        self.assertEqual((cards[3]['attention'], cards[3]['summary'], cards[3]['agent_count'], cards[3]['agents']), ('empty', 'no agents', '', []))
        self.assertEqual((cards[4]['attention'], cards[4]['summary'], cards[4]['subtitle'], cards[4]['active'], cards[4]['agent_count']),
                         ('stopped', 'stopped', 'Named  ·  api  ·  ~', False, ''))
        self.assertEqual((cards[5]['subtitle'], cards[5]['agents']), ('nothing saved', []))

    def test_missing_herdr_is_reported_without_failing(self):
        self.write_sessions()
        data = self.run_script(without_herdr=True)
        self.assertEqual((data['ok'], data['bar_label'], data['cards']), (False, '', []))
        self.assertIn('herdr is not installed', data['error'])

    def test_no_sessions_gives_an_empty_bar_label(self):
        self.write_sessions()
        data = self.run_script()
        self.assertEqual((data['ok'], data['bar_label'], data['title']), (True, '', 'Herdr (0 servers, 0 agents)'))

    def test_unanswering_server_does_not_take_the_list_down(self):
        self.write_sessions(('default', True), ('3', True))
        self.write_snapshot('default', '0.8.0', ['api'], [])
        data = self.run_script()
        self.assertEqual([c['title'] for c in data['cards']], ['api', 'Workspace 3'])
        self.assertEqual((data['cards'][0]['summary'], data['cards'][0]['attention']), ('no agents', 'empty'))
        self.assertEqual((data['cards'][1]['summary'], data['cards'][1]['attention'], data['cards'][1]['active']), ('no answer', 'unreachable', False))
        self.assertEqual((data['bar_label'], data['title']), ('2', 'Herdr (2 servers, 0 agents)'))

    def test_unparseable_session_list_is_an_error(self):
        (self.fixtures / 'sessions.json').write_text('not json')
        data = self.run_script()
        self.assertEqual((data['ok'], data['cards']), (False, []))


if __name__ == '__main__':
    unittest.main()
