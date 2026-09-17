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
    return {'id': 'cli:api:snapshot', 'result': {'snapshot': {
        'version': version,
        'workspaces': [{'workspace_id': f'w{i}', 'label': label} for i, label in enumerate(workspaces)],
        'agents': [{'pane_id': f'w0:p{i}', 'agent': 'claude', 'agent_status': status, 'terminal_title': title,
                    'terminal_title_stripped': title} for i, (title, status) in enumerate(agents)]}}}


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

    def test_joins_sessions_snapshots_and_saved_layouts(self):
        self.write_sessions(('9', False), ('5', True), ('default', True), ('3', True), ('7', False), ('bad name!', True))
        self.write_snapshot('default', '0.8.0', ['checkout-service', 'design-tokens', 'checkout-service'],
                            [('Token names for the new palette', 'idle'), ('◐ Rewrite the receipt formatter', 'working'), ('', 'working')])
        self.write_snapshot('3', '0.8.0', ['billing-api'], [('Drop the legacy invoice table', 'blocked')])
        self.write_snapshot('5', '0.8.0', ['docs-site'], [('Upgrade the search index', 'done'), ('π - anchors', 'done')])
        (self.home / '.config/herdr/sessions/7/session.json').write_text(json.dumps({'workspaces': [
            {'identity_cwd': str(self.home)}, {'custom_name': 'Named'}, {'identity_cwd': '/srv/api'}]}))
        data = self.run_script('refresh')
        self.assertEqual((data['ok'], data['error']), (True, ''))
        self.assertEqual(data['title'], 'Herdr (3 servers, 6 agents)')
        self.assertEqual(data['bar_label'], '!3')
        sessions = {s['name']: s for s in data['sessions']}
        self.assertEqual([s['name'] for s in data['sessions']], ['default', '3', '5', '7', '9'])
        shared = sessions['default']
        self.assertEqual((shared['display'], shared['running'], shared['is_default']), ('Shared session', True, True))
        self.assertEqual((shared['summary'], shared['summary_state'], shared['agent_count']), ('2 working', 'working', '3 agents'))
        self.assertEqual(shared['projects'], 'checkout-service  ·  design-tokens')
        self.assertEqual([(a['title'], a['label']) for a in shared['agents']],
                         [('Rewrite the receipt formatter', 'working'), ('Token names for the new palette', 'ready')])
        self.assertEqual((sessions['3']['display'], sessions['3']['summary'], sessions['3']['summary_state'], sessions['3']['agent_count']),
                         ('Workspace 3', '1 needs you', 'blocked', '1 agent'))
        self.assertEqual(sessions['3']['agents'][0]['label'], 'needs you')
        self.assertEqual((sessions['5']['summary'], sessions['5']['summary_state']), ('2 done', 'done'))
        self.assertEqual(sessions['5']['agents'][1]['title'], 'π - anchors')
        self.assertEqual((sessions['7']['summary'], sessions['7']['summary_state'], sessions['7']['projects'], sessions['7']['agent_count']),
                         ('stopped', 'stopped', 'Named  ·  api  ·  ~', ''))
        self.assertEqual((sessions['9']['projects'], sessions['9']['agents']), ('nothing saved', []))

    def test_missing_herdr_is_reported_without_failing(self):
        self.write_sessions()
        data = self.run_script(without_herdr=True)
        self.assertEqual((data['ok'], data['bar_label'], data['sessions']), (False, '', []))
        self.assertIn('herdr is not installed', data['error'])

    def test_no_sessions_gives_an_empty_bar_label(self):
        self.write_sessions()
        data = self.run_script()
        self.assertEqual((data['ok'], data['bar_label'], data['title']), (True, '', 'Herdr (0 servers, 0 agents)'))

    def test_unanswering_server_does_not_take_the_list_down(self):
        self.write_sessions(('default', True), ('3', True))
        self.write_snapshot('default', '0.8.0', [], [])
        data = self.run_script()
        self.assertEqual([s['name'] for s in data['sessions']], ['default', '3'])
        self.assertEqual((data['sessions'][0]['summary'], data['sessions'][0]['summary_state']), ('no agents', 'empty'))
        self.assertEqual((data['sessions'][1]['summary'], data['sessions'][1]['summary_state'], data['sessions'][1]['agent_count']), ('no answer', 'unreachable', ''))
        self.assertEqual((data['bar_label'], data['title']), ('2', 'Herdr (2 servers, 0 agents)'))

    def test_unparseable_session_list_is_an_error(self):
        (self.fixtures / 'sessions.json').write_text('not json')
        data = self.run_script()
        self.assertEqual((data['ok'], data['sessions']), (False, []))


if __name__ == '__main__':
    unittest.main()
