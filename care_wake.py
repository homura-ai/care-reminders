#!/usr/bin/python3
"""Shared sleep rule for the care scripts.

Explicit sleep (state.json `sleeping` / `sleep_state`) holds until an explicit
awake confirmation (`awake_confirmed_at`) strictly after `sleeping_since`. Message
or desktop activity never ends sleep: replies from bed must not restart reminders.
care_send.py stores each successful activity probe in activity.json.
"""
import contextlib, fcntl, json, pathlib, sys, time
from datetime import datetime
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import care_config as C

ROOT = C.state_dir()
ACTIVITY = ROOT/'activity.json'
LOCK = ROOT/'state.lock'

@contextlib.contextmanager
def state_lock():
    """The one lock every state.json writer holds (scripts here; humans or agents via `flock`)."""
    ROOT.mkdir(parents=True, exist_ok=True)
    with open(LOCK, 'a') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield

def ts(value):
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp()
    except (TypeError, ValueError):
        return None

def aware_ts(value):
    """Like ts(), but None for timezone-naive values, so they can never end sleep."""
    try:
        d = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None
    return d.timestamp() if d.tzinfo is not None and d.utcoffset() is not None else None

def explicit_sleep(state):
    return bool(state.get('sleeping') or state.get('sleep_state') in ('sleeping', 'asleep'))

def woke(state, latest=None):
    """Sleep ends ONLY on an explicit awake confirmation; `latest` activity is deliberately ignored."""
    since = aware_ts(state.get('sleeping_since'))
    confirmed = aware_ts(state.get('awake_confirmed_at'))
    # Strictly after: whole-second stamps, so a same-second confirmation never undoes a new sleep.
    return since is not None and confirmed is not None and confirmed > since

def asleep(state, latest):
    return explicit_sleep(state) and not woke(state, latest)

def stored_latest():
    try:
        return ts(json.loads(ACTIVITY.read_text()).get('latest'))
    except (OSError, ValueError, AttributeError):
        return None

def store_latest(iso):
    if not iso:
        return
    ROOT.mkdir(parents=True, exist_ok=True)
    tmp = ACTIVITY.with_suffix('.tmp')
    tmp.write_text(json.dumps({'latest': iso, 'checked_at': time.time()}))
    tmp.replace(ACTIVITY)

def reconcile(state_path, latest):
    """Clear explicit sleep in state.json once an awake confirmation is recorded. Returns True if cleared."""
    path = pathlib.Path(state_path)
    with state_lock():
        try:
            state = json.loads(path.read_text())
        except (OSError, ValueError):
            return False
        if not explicit_sleep(state) or not woke(state, latest):
            return False
        state.setdefault('wake_history', []).append({
            'slept_at': state.get('sleeping_since'), 'woke_at': state.get('awake_confirmed_at'),
            'source': 'explicit awake confirmation'})
        state['sleeping'] = None
        state['sleep_state'] = None
        tmp = path.with_suffix('.wake.tmp')
        tmp.write_text(json.dumps(state, indent=2))
        tmp.replace(path)
    return True
