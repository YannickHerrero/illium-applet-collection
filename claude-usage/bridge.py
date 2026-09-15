#!/usr/bin/env python3
"""Preserve a Claude Code statusline and export only its documented quota fields."""
import argparse
import fcntl
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

MAX_INPUT = 1024 * 1024
MAX_CACHE = 8192
WINDOWS = ("five_hour", "seven_day")


def finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def quotas(payload, now):
    limits = payload.get("rate_limits", {}) if isinstance(payload, dict) else {}
    if not isinstance(limits, dict):
        return {}
    result = {}
    for key in WINDOWS:
        item = limits.get(key)
        if not isinstance(item, dict):
            continue
        used, resets = item.get("used_percentage"), item.get("resets_at")
        if not finite_number(used) or not 0 <= used <= 100:
            continue
        if not finite_number(resets) or not now < resets <= now + 8 * 86400:
            continue
        result[key] = {"used_percentage": used, "resets_at": int(resets), "received_at": int(now)}
    return result


def publish(path, payload, now=None):
    now = time.time() if now is None else now
    incoming = quotas(payload, now)
    if not incoming:
        return False  # A new/idle session must not erase another session's valid reading.
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with (path.parent / (path.name + ".lock")).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        previous = {}
        try:
            with path.open("rb") as stream:
                raw = stream.read(MAX_CACHE + 1)
            if len(raw) <= MAX_CACHE:
                old = json.loads(raw)
                if old.get("schema") == 1:
                    # Revalidate old data, preserving receipt ages rather than refreshing them.
                    for key in WINDOWS:
                        item = old.get("windows", {}).get(key, {})
                        if key in quotas({"rate_limits": {key: item}}, now):
                            received = item.get("received_at")
                            if finite_number(received) and 0 <= received <= now:
                                previous[key] = {k: item[k] for k in ("used_percentage", "resets_at", "received_at")}
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        current = dict(previous)
        for key, item in incoming.items():
            old = previous.get(key, {})
            same = all(old.get(k) == item[k] for k in ("used_percentage", "resets_at"))
            if not same or now - old.get("received_at", 0) >= 60:
                current[key] = item
        if current == previous:
            return False
        snapshot = {"schema": 1, "source": "claude-code-statusline", "windows": current}
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=".quota-", delete=False) as stream:
                temporary = stream.name
                json.dump(snapshot, stream, allow_nan=False, separators=(",", ":"))
            os.replace(temporary, path)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
    return True


def start_fable(settings):
    if settings.get('fable_probe') is not True:
        return
    directory = Path(settings['cache']).parent
    worker = Path(__file__).with_name('fable.py')
    if not worker.is_file():
        return
    attempt = directory / 'fable-attempt.json'
    try:
        if 0 <= time.time() - attempt.stat().st_mtime < 300:
            return
    except FileNotFoundError:
        pass
    # The worker owns a nonblocking lock and checks the interval again. Even
    # simultaneous statuslines cannot start overlapping Claude probes.
    directory.mkdir(parents=True, exist_ok=True)
    subprocess.Popen([sys.executable, str(worker), '--directory', str(directory),
                      '--claude', settings.get('claude', 'claude')],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    settings = json.loads(args.config.read_text(encoding="utf-8"))
    payload = sys.stdin.buffer.read(MAX_INPUT + 1)
    # A collector failure must not break the user's existing CLI statusline.
    if len(payload) <= MAX_INPUT:
        try:
            publish(settings["cache"], json.loads(payload))
            start_fable(settings)
        except (OSError, ValueError, TypeError, AttributeError):
            pass
    command = settings.get("delegate", "")
    if command:
        # This is the user's original trusted settings command, never a value from stdin.
        result = subprocess.run(["/bin/sh", "-c", command], input=payload, check=False)
        return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
