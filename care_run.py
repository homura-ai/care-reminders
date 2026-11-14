#!/usr/bin/python3
"""Bounded care silence ("in a run"), from scheduled windows or a manual override.

    care run start [--minutes N]   quiet now (default 240, 1-720)
    care run stop  [--minutes N]   not in a run now, overriding windows for N minutes
    care run auto                  clear the override
    care run status                read-only; "active" is authoritative
    care_run.py tick               refresh run-state.json (care-reminders-run.timer, every 30 s)

Precedence: manual > scheduled window. Records carry a 90 s lease, so if the
timer stops (including suspend) silence fails open. Windows come from the
config's "run_windows": [[label, start ISO, end ISO], ...].
"""
import argparse
import fcntl
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import time
from datetime import datetime
sys.path.insert(0, str(Path(__file__).resolve().parent))
import care_config as C

STATE = C.state_dir()
LEASE = 90  # Fail open if the timer stops, including suspend/resume.
MAX_DURATION = C.CFG['run_max_hours'] * 3600
WINDOWS = tuple(tuple(w) for w in C.CFG['run_windows'])


def read(path):
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def atomic(path, data):
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.care-')
    try:
        with os.fdopen(fd, 'w') as file:
            json.dump(data, file, allow_nan=False)
            file.flush()
            os.fsync(file.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def valid(data, now):
    """Heartbeat readers must reject stale, malformed, future or unbounded silence."""
    try:
        since, until, updated, expires = (data[k] for k in ('since', 'until', 'updated_at', 'expires_at'))
        return (
            data['active'] is True
            and data['source'] in ('clock', 'manual')
            and all(finite(n) for n in (since, until, updated, expires))
            and since <= now < until <= since + MAX_DURATION
            and updated <= now < expires <= min(until, updated + LEASE)
        )
    except (KeyError, TypeError):
        return False


def window_time(value):
    """A run_windows time; one without an offset is in the configured timezone."""
    d = datetime.fromisoformat(value)
    if d.tzinfo is None and C.zone() is not None:
        d = d.replace(tzinfo=C.zone())
    return d.timestamp()


def select(now, manual):
    if (finite(manual.get('since')) and finite(manual.get('until'))
            and manual['since'] <= now < manual['until'] <= manual['since'] + MAX_DURATION
            and type(manual.get('active')) is bool):
        return manual['active'], manual['since'], manual['until'], 'manual', 'override'
    for label, start, end in WINDOWS:
        since, until = (window_time(v) for v in (start, end))
        if since <= now < until:
            return True, since, until, 'clock', label
    return False, None, None, 'clock', 'outside-run'


def update(directory, now, manual):
    active, since, until, source, label = select(now, manual)
    data = dict(active=active, since=since, until=until, source=source,
                session_id=f'{source}:{label}:{since}' if active else None,
                updated_at=now, expires_at=min(now + LEASE, until) if active else now + LEASE)
    atomic(directory / 'run-state.json', data)
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('tick', 'start', 'stop', 'auto', 'status'))
    parser.add_argument('--minutes', type=int, default=240,
                        help='manual override duration, 1–720 minutes; stop also expires')
    args = parser.parse_args()
    if not 1 <= args.minutes <= 720:
        parser.error('--minutes must be 1–720')
    now = time.time()
    if args.command == 'status':
        data = read(STATE / 'run-state.json')
        data['active'] = valid(data, now)
        print(json.dumps(data))
        return
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (STATE / 'switch.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        now = time.time()
        manual_path = STATE / 'manual-override.json'
        if args.command in ('start', 'stop'):
            atomic(manual_path, dict(active=args.command == 'start', since=now,
                                     until=now + args.minutes * 60))
        elif args.command == 'auto':
            manual_path.unlink(missing_ok=True)
        print(json.dumps(update(STATE, now, read(manual_path))))


if __name__ == '__main__':
    main()
