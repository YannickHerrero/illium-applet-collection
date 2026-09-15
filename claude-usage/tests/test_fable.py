import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'fable.py'
spec = importlib.util.spec_from_file_location('fable', SCRIPT)
fable = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fable)
NOW = 1800000000


def limits(used=54):
    return {'limits': [{'kind': 'weekly_scoped', 'is_active': True, 'scope': {'model': {'display_name': 'Fable'}}, 'percent': used, 'resets_at': NOW + 400000}]}


class FableTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def test_extracts_only_fable_weekly(self):
        self.assertEqual(fable.extract(limits(), NOW), {'used_percentage':54, 'resets_at':NOW+400000, 'received_at':NOW})
        for bad in [True, -1, 101, '54', float('nan')]:
            self.assertIsNone(fable.extract(limits(bad), NOW))
        self.assertEqual(fable.extract(limits(0), NOW)['used_percentage'], 0)
        data = limits()
        data['limits'][0]['scope']['model']['display_name'] = 'Sonnet'
        self.assertIsNone(fable.extract(data, NOW))
        self.assertIsNone(fable.extract({'five_hour': {'utilization':54}}, NOW))
        self.assertIsNone(fable.extract(limits(), NOW+400000))

    def test_projection_and_timezone(self):
        reset = fable.datetime.datetime.fromtimestamp(NOW+400000, fable.datetime.timezone.utc).isoformat()
        data = {'model_scoped': [{'display_name':'Fable', 'utilization':54, 'resets_at':reset}]}
        self.assertEqual(fable.extract(data, NOW)['resets_at'], NOW+400000)
        data['model_scoped'][0]['resets_at'] = reset.removesuffix('+00:00')
        self.assertIsNone(fable.extract(data, NOW))
        data = limits(); data['limits'] *= 2
        self.assertIsNone(fable.extract(data, NOW))

    def test_throttle_and_unchanged_cache_do_not_fake_freshness(self):
        with patch.object(fable, 'query', return_value=limits()) as query:
            with patch.object(fable.time, 'time', return_value=NOW):
                fable.collect(self.directory, 'claude')
                fable.collect(self.directory, 'claude')
            self.assertEqual(query.call_count, 1)
            with patch.object(fable.time, 'time', return_value=NOW+301):
                fable.collect(self.directory, 'claude')
            self.assertEqual(query.call_count, 2)
        cached = fable.read_json(self.directory/'fable.json')
        self.assertEqual(cached['window']['received_at'], NOW)
        self.assertEqual(set(cached), {'schema','source','window'})
        with patch.object(fable, 'query', side_effect=TimeoutError), patch.object(fable.time, 'time', return_value=NOW+602):
            fable.collect(self.directory, 'claude')
        self.assertEqual(fable.read_json(self.directory/'fable.json'), cached)

    def test_control_protocol_never_sends_a_prompt(self):
        executable = self.directory/'fake-claude'
        executable.write_text('''#!/usr/bin/env python3
import sys,json
assert '--no-session-persistence' in sys.argv
assert '--tools' in sys.argv and sys.argv[sys.argv.index('--tools')+1] == ''
for line in sys.stdin:
 message=json.loads(line)
 assert message['type']=='control_request'
 body=message['request']
 assert body['subtype'] in ('initialize','get_usage')
 if body['subtype']=='get_usage': assert body['skip_behaviors'] is True
 response={'rate_limits':{'model_scoped':[]}} if body['subtype']=='get_usage' else {}
 print(json.dumps({'type':'control_response','response':{'subtype':'success','request_id':message['request_id'],'response':response}}),flush=True)
''')
        executable.chmod(0o700)
        self.assertEqual(fable.query(str(executable)), {'model_scoped':[]})

    def test_probe_times_out_without_leaving_a_process(self):
        executable = self.directory/'stuck-claude'
        executable.write_text('#!/usr/bin/env python3\nimport time\ntime.sleep(10)\n')
        executable.chmod(0o700)
        with self.assertRaises(TimeoutError):
            fable.query(str(executable), timeout=0.1)


if __name__ == '__main__':
    unittest.main()
