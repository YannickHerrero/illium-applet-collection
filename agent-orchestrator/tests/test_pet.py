"""Offline state-machine tests: no real agent, credentials or runtime data."""
import datetime
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('pet_agents', Path(__file__).resolve().parents[1] / 'agents.py')
agents = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agents)


class PetTests(unittest.TestCase):
    def step(self, observations, previous=None, time=100, waiting=0, working=0):
        return agents.pet_transition(observations, {'waiting': waiting, 'working': working}, previous or {}, time)

    def test_baseline_and_steady_states(self):
        self.assertEqual(self.step({'a': 'done'})[0], 'idle')
        self.assertEqual(self.step({'a': 'error'})[0], 'idle')
        self.assertEqual(self.step({'a': 'working'}, working=1)[0], 'working')
        self.assertEqual(self.step({}, waiting=1, working=4)[0], 'waiting')

    def test_completion_is_transient_and_not_retriggered(self):
        _, before = self.step({'a': 'working', 'b': 'working'}, working=2)
        state, after = self.step({'a': 'done', 'b': 'working'}, before, 103, working=1)
        self.assertEqual(state, 'success')
        state, later = self.step({'a': 'done', 'b': 'working'}, after, 106, working=1)
        self.assertEqual(state, 'success')
        self.assertEqual(later['until'], 108)
        self.assertEqual(self.step({'a': 'done', 'b': 'working'}, later, 109, working=1)[0], 'working')

    def test_waiting_suppresses_and_discards_reaction(self):
        _, before = self.step({'a': 'working', 'b': 'working'})
        state, after = self.step({'a': 'done', 'b': 'waiting'}, before, 103, waiting=1)
        self.assertEqual(state, 'waiting')
        self.assertEqual(self.step({'a': 'done', 'b': 'working'}, after, 104, working=1)[0], 'working')

    def test_failure_wins_simultaneous_results_and_expires(self):
        _, before = self.step({'a': 'working', 'b': 'working'})
        state, after = self.step({'a': 'done', 'b': 'error'}, before, 103)
        self.assertEqual(state, 'error')
        self.assertEqual(after['until'], 111)
        self.assertEqual(self.step({'a': 'done', 'b': 'error'}, after, 112)[0], 'idle')

    def test_disappearance_outage_and_long_restart_do_not_imply_success(self):
        _, before = self.step({'a': 'working'})
        state, absent = self.step({}, before, 103)
        self.assertEqual(state, 'idle')
        self.assertEqual(self.step({'a': 'done'}, absent, 106)[0], 'idle')
        self.assertEqual(self.step({'a': 'done'}, before, 200)[0], 'idle')
        self.assertEqual(self.step({'a': 'done'}, before, 90)[0], 'idle')

    def test_new_agent_does_not_reuse_another_agents_transition(self):
        _, before = self.step({'a': 'working'})
        self.assertEqual(self.step({'b': 'done'}, before, 103)[0], 'idle')

    def test_atomic_private_state_and_corrupt_cache(self):
        with tempfile.TemporaryDirectory() as home:
            reference = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
            summary = {'waiting': 0, 'working': 1}
            observations = {}
            agents.observe(observations, ['herdr', 'private-session', 'private-pane'], 'working')
            self.assertEqual(agents.pet_state(home, observations, summary, reference), 'working')
            path = Path(home) / '.local/state/winarchy-applet-collection/agent-orchestrator/pet.json'
            text = path.read_text()
            self.assertNotIn('private', text)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            done = {key: 'done' for key in observations}
            later = reference + datetime.timedelta(seconds=3)
            self.assertEqual(agents.pet_state(home, done, {'waiting': 0, 'working': 0}, later), 'success')
            for corrupt in ('broken', '[]', '{"version": 1}', json.dumps({'version': 1, 'agents': [], 'updated_at': 'bad'})):
                path.write_text(corrupt)
                self.assertEqual(agents.pet_state(home, done, {'waiting': 0, 'working': 0}, later), 'idle')
            with patch.object(agents.os, 'replace', side_effect=OSError('read only')):
                self.assertEqual(agents.pet_state(home, observations, summary, later), 'working')
            self.assertEqual(list(path.parent.iterdir()), [path])


if __name__ == '__main__':
    unittest.main()
