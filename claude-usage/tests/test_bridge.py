import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "bridge.py"
spec = importlib.util.spec_from_file_location("bridge", SCRIPT)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)
NOW = 1800000000


def payload(used=34):
    return {"rate_limits": {"five_hour": {"used_percentage": used, "resets_at": NOW + 9000}}, "session_id": "do-not-store", "workspace": {"current_dir": "do-not-store"}, "secret": "do-not-store", "context_window": {"used_percentage": 99}}


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cache = Path(self.temp.name) / "snapshot.json"

    def test_only_documented_quota_fields_survive(self):
        self.assertTrue(bridge.publish(self.cache, payload(), NOW))
        text = self.cache.read_text()
        self.assertNotIn("do-not-store", text)
        data = json.loads(text)
        self.assertEqual(data["windows"]["five_hour"]["used_percentage"], 34)
        self.assertEqual(set(data), {"schema", "source", "windows"})

    def test_context_percentage_is_not_subscription_usage(self):
        self.assertFalse(bridge.publish(self.cache, {"context_window": {"used_percentage": 99}}, NOW))
        self.assertFalse(self.cache.exists())

    def test_missing_window_preserves_age_not_a_fake_refresh(self):
        bridge.publish(self.cache, payload(), NOW)
        before = self.cache.read_bytes()
        self.assertFalse(bridge.publish(self.cache, {}, NOW + 30))
        self.assertEqual(self.cache.read_bytes(), before)
        self.assertFalse(bridge.publish(self.cache, payload(), NOW + 30))
        self.assertEqual(self.cache.read_bytes(), before)
        self.assertTrue(bridge.publish(self.cache, payload(), NOW + 60))
        self.assertEqual(json.loads(self.cache.read_text())["windows"]["five_hour"]["received_at"], NOW + 60)

    def test_windows_merge_independently(self):
        bridge.publish(self.cache, payload(), NOW)
        bridge.publish(self.cache, {"rate_limits": {"seven_day": {"used_percentage": 12, "resets_at": NOW + 500000}}}, NOW + 10)
        windows = json.loads(self.cache.read_text())["windows"]
        self.assertEqual(len(windows), 2)
        self.assertEqual(windows["five_hour"]["received_at"], NOW)

    def test_invalid_numbers_and_expired_windows_are_rejected(self):
        for value in (True, None, "34", -1, 101, float("nan"), float("inf")):
            self.assertEqual(bridge.quotas(payload(value), NOW), {})
        self.assertEqual(bridge.quotas(payload(), NOW + 9000), {})
        self.assertEqual(bridge.quotas({"rate_limits": []}, NOW), {})
        self.assertTrue(bridge.quotas(payload(0), NOW))

    def test_concurrent_sessions_publish_valid_bounded_snapshots(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda n: bridge.publish(self.cache, payload(n), NOW + n), range(20)))
        data = json.loads(self.cache.read_text())
        self.assertIn(data["windows"]["five_hour"]["used_percentage"], range(20))
        self.assertLess(self.cache.stat().st_size, bridge.MAX_CACHE)
        self.assertEqual(list(self.cache.parent.glob('.quota-*')), [])

    def test_corrupt_cache_recovers(self):
        self.cache.write_text("not JSON")
        bridge.publish(self.cache, payload(), NOW)
        self.assertEqual(json.loads(self.cache.read_text())["schema"], 1)
        self.assertEqual(list(self.cache.parent.glob('.quota-*')), [])

    def test_delegate_receives_original_unicode_input_and_keeps_exit_code(self):
        config = self.cache.parent / "bridge.json"
        config.write_text(json.dumps({"cache": str(self.cache), "delegate": "cat; exit 7"}))
        raw = '{"model":{"display_name":"Café 日本語"}}'.encode()
        result = subprocess.run([sys.executable, "-B", str(SCRIPT), "--config", str(config)], input=raw, capture_output=True)
        self.assertEqual(result.stdout, raw)
        self.assertEqual(result.stderr, b"")
        self.assertEqual(result.returncode, 7)


if __name__ == "__main__":
    unittest.main()
