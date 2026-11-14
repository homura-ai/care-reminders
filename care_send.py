#!/usr/bin/python3
"""Model-free care reminder sender. Run every 30 s by care-reminders-send.timer.

Anchored breaks (every 30 min) and zoom-outs (every 15 min), due meals, and a
wind-down then a firmer bedtime note once per night. Unanswered reminders repeat
every 15 min. Nothing is sent during a run (care_run.py status), while snoozed,
in personal quiet, while explicitly asleep, or at night when there has been no
activity for 90 min (or activity is unknown). A reminder counts as sent only on
the primary notifier's receipt; state.json writes hold the shared state.lock.

    care_send.py             one tick
    care_send.py --dry-run   print the decision and the text; no sends, no writes, no lock
"""
import fcntl, json, math, os, pathlib, subprocess, sys, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import care_config as C
import care_wake
from datetime import datetime, timedelta, timezone

CFG = C.CFG
ROOT = C.state_dir()
STATE = ROOT/'state.json'
OWN = ROOT/'send-state.json'
CARE_RUN = [sys.executable, str(C.HERE/'care_run.py'), 'status']
SPACING_MIN = CFG['spacing_minutes']
FIRM_ACTIVITY_MAX = CFG['bedtime']['firm_needs_activity_minutes']*60
PREFIX = CFG['prefix']
LINES = CFG['lines']

def ts(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp()
    except ValueError:
        return None

def local_hour():
    return datetime.now(C.zone()).hour

def run(args, stdin=None):
    env = {k: v for k, v in os.environ.items() if k not in ('LD_LIBRARY_PATH', 'LD_PRELOAD')}
    try:
        # No stdin spec: /dev/null, never the caller's stdin (it could block the notifier).
        feed = {'input': stdin} if stdin is not None else {'stdin': subprocess.DEVNULL}
        p = subprocess.run(args, capture_output=True, text=True, timeout=60, env=env, **feed)
        return p.returncode, p.stdout + p.stderr
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)

def in_run():
    code, out = run(CARE_RUN)
    try:
        return code == 0 and json.loads(out.strip().splitlines()[-1]).get('active') is True
    except (ValueError, IndexError, AttributeError):
        return False

def skipped(state, now):
    """Kinds with an active skip. Accepts {kind: until} under 'skips' or 'skip'."""
    out = set()
    for key in ('skips', 'skip'):
        value = state.get(key)
        if isinstance(value, dict):
            for kind, until in value.items():
                end = ts(until.get('until') if isinstance(until, dict) else until)
                if end is None or end > now:
                    out.add(kind)
    return out

def gate(state, now, running, hour, latest=None):
    if running:
        return 'in run'
    if not isinstance(state, dict):
        return 'state unreadable'
    if state.get('personal_quiet'):
        return 'personal quiet'
    end = ts(state.get('postponed_until'))
    if state.get('postponed_until') and end is None:
        return 'snooze unreadable'
    if end and end > now:
        return 'snoozed'
    if care_wake.asleep(state, latest):
        return 'sleeping'
    night = CFG['night']
    if (in_night(hour, night['start_hour'], night['end_hour'])
            and (latest is None or now - latest >= night['idle_minutes']*60)):
        return f"night: no activity in {night['idle_minutes']} min (or unknown), defer"
    return None

def in_night(hour, start, end):
    """Night hours [start, end): wraps past midnight when start > end; start == end means no night."""
    return start <= hour < end if start <= end else (hour >= start or hour < end)

def last_sent(state, own, kind):
    values = [ts((state.get('last_reminder') or {}).get(kind)),
              (own.get('last_by_kind') or {}).get(kind)]
    for record in own.get('history', []):
        if kind in record.get('kinds', []) and record.get('sent') is True:
            values.append(ts(record.get('at')))
    return max([v for v in values if isinstance(v, (int, float))] or [0])

def at_local(day, hhmm):
    h, m = (int(x) for x in hhmm.split(':'))
    return day.replace(hour=h, minute=m, second=0, microsecond=0)

def bedtime_window(now):
    """(wind, firm, end) Unix times of the bedtime night that contains now, or None.

    The night starts at wind_down; firm is the first firm time at or after it and
    end the first end time after firm, so a bedtime before midnight with an end
    after midnight (22:30 / 23:30 / 07:00) works as well as one after midnight
    (01:15 / 02:30 / 08:00).
    """
    b = CFG['bedtime']
    today = C.local(now)
    for back in (0, 1):
        day = today - timedelta(days=back)
        wind = at_local(day, b['wind_down'])
        firm = at_local(day, b['firm'])
        if firm < wind:
            firm += timedelta(days=1)
        end = at_local(day, b['end'])
        while end <= firm:
            end += timedelta(days=1)
        wind, firm, end = (t.timestamp() for t in (wind, firm, end))
        if wind <= now < end:
            return wind, firm, end
    return None

def bedtime_kinds(state, own, now, latest=None):
    """Once per local night; deferred under the shared gates and spacing, never caught up by day.

    Wind-down can catch up until the firmer note is due. The firmer note needs
    activity in the last 15 minutes; unknown means defer. The bedtime end time
    ends both windows.
    """
    window = bedtime_window(now)
    if window is None:
        return []
    wind, firm, end = window
    due = []
    if wind <= now < firm and last_sent(state, own, 'wind_down') < wind:
        due.append('wind_down')
    active = latest is not None and 0 <= now - latest < FIRM_ACTIVITY_MAX
    if firm <= now < end and active and last_sent(state, own, 'firm') < firm:
        due.append('firm')
    return due

def due_kinds(state, own, now, latest=None):
    kinds = []
    anchor = ts(state.get('cadence_started_at'))
    for kind, minutes in (('break', CFG['break_minutes']), ('zoom_out', CFG['zoom_out_minutes'])):
        sent = last_sent(state, own, kind)
        ack = ts(state.get(f'last_{kind}_ack_at')) or 0
        mark = (anchor + math.floor((now-anchor)/(minutes*60))*minutes*60
                if anchor is not None and now >= anchor + minutes*60 else 0)
        # New anchored marks, or repeat a still-unanswered concern every 15 min.
        if ((mark and mark > max(sent, ack)) or
                (sent > ack and now - sent >= SPACING_MIN*60)):
            kinds.append(kind)
    meal_due = ts(state.get('meal_next_due_at'))
    if meal_due is not None and meal_due <= now:
        if now - last_sent(state, own, 'meal') >= SPACING_MIN*60:
            kinds.insert(1, 'meal')
    kinds = bedtime_kinds(state, own, now, latest) + kinds
    return [k for k in kinds if k not in skipped(state, now)]

def decide(state, own, now, running, hour, latest=None):
    why = gate(state, now, running, hour, latest)
    if why:
        return why, None
    kinds = due_kinds(state, own, now, latest)
    if not kinds:
        return 'nothing due', None
    last_any = max(ts((state.get('last_reminder') or {}).get('any')) or 0,
                   own.get('last_sent') or 0)
    expiry = ts(state.get('postponed_until'))
    # A snooze expiry overrides spacing exactly once.
    resumed = expiry is not None and expiry <= now and last_any < expiry
    if not resumed and now - last_any < SPACING_MIN*60:
        return 'reminded recently', None
    return None, kinds

def compose(kinds):
    lines = [LINES[k] for k in kinds]
    if 'break' in kinds and 'zoom_out' in kinds:
        lines[kinds.index('break')] = LINES['break_and_zoom']
        lines.remove(LINES['zoom_out'])
    return PREFIX + ' '.join(lines)

def load_state():
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return None

def latest_activity():
    """Latest activity time (ISO) from activity_cmd, or None when unknown or not configured."""
    cmd = CFG.get('activity_cmd')
    if not cmd:
        return None
    code, out = run([os.path.expanduser(a) for a in cmd])
    lines = out.strip().splitlines()
    return lines[-1] if code == 0 and lines and care_wake.aware_ts(lines[-1]) else None

def probe(write=True):
    """Latest activity as Unix time; None = unknown. Also applies an explicit awake confirmation."""
    iso = latest_activity()
    if write:
        care_wake.store_latest(iso)
        if care_wake.reconcile(STATE, care_wake.ts(iso)):
            print('woke: cleared explicit sleep in state.json')
    return care_wake.ts(iso)

def current(write=True):
    latest = probe(write)  # slow step first, so state and run status are read after it
    running = in_run()
    return load_state(), running, latest

def persist(own):
    tmp = OWN.with_suffix('.tmp')
    tmp.write_text(json.dumps(own, indent=2)); tmp.replace(OWN)

def load_own():
    try:
        return json.loads(OWN.read_text())
    except (OSError, ValueError):
        return {}

def fill(template, text, key):
    return os.path.expanduser(template.replace('{text}', text).replace('{key}', key)
                              .replace('{app}', CFG['app_name']))

def send(spec, text, key):
    """Run one notifier; True only on its receipt."""
    argv = [fill(a, text, key) for a in spec['argv']]
    stdin = fill(spec['stdin'], text, key) if spec.get('stdin') else None
    code, out = run(argv, stdin)
    receipt = spec.get('receipt', 'exit0')
    if code != 0:
        return False, out
    if receipt == 'exit0':
        return True, out
    if receipt == 'stdout':
        return bool(out.strip()), out
    return out.strip().endswith(receipt), out

def main(argv):
    if argv not in ([], ['--dry-run']):
        # Anything else (a typo such as "-n" or "--dryrun") must not run a real tick.
        print(__doc__, file=sys.stderr); return 2
    if argv[:1] == ['--dry-run']:
        own = load_own()
        state, running, latest = current(write=False)
        why, kinds = decide(state, own, time.time(), running, local_hour(), latest)
        print('quiet:', why) if why else print('would send:', compose(kinds))
        return 0
    ROOT.mkdir(parents=True, exist_ok=True)
    with open(ROOT/'send.lock', 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print('quiet: another tick'); return 0
        return tick()

def tick():
    own = load_own()
    state, running, latest = current()
    now = time.time()
    why, kinds = decide(state, own, now, running, local_hour(), latest)
    if why:
        print('quiet:', why); return 0
    text = compose(kinds)
    # Persist a stable identity before sending: an uncertain send retries the
    # same key rather than inventing a second reminder.
    pending = own.get('pending')
    if not pending or pending['text'] != text:
        pending = {'event_key': f'care-{time.time_ns()}', 'text': text, 'kinds': kinds}
        own['pending'] = pending; persist(own)
    ok, out = send(CFG['notify'], text, pending['event_key'])
    if not ok:
        print('FAILED (same-key retry next tick):', out.strip()[:200]); return 0
    sent = time.time()
    at = datetime.fromtimestamp(sent, timezone.utc).isoformat()
    record = dict(pending, sent=True, sent_at=sent, at=at)
    own['last_sent'] = sent
    own.setdefault('last_by_kind', {}).update({k: sent for k in kinds})
    own['current'] = record
    own.pop('pending', None)
    persist(own)
    with care_wake.state_lock():
        state = load_state()
        if state is not None:
            state.setdefault('last_reminder', {}).update({k: at for k in ['any'] + kinds})
            state.setdefault('delivery_history', []).append(dict(record, via='care_send.py'))
            state['delivery_history'] = state['delivery_history'][-200:]
            tmp = STATE.with_suffix('.send.tmp')
            tmp.write_text(json.dumps(state, indent=2)); tmp.replace(STATE)
    if CFG.get('secondary'):
        st, running, latest = current()
        why = gate(st, time.time(), running, local_hour(), latest)
        if not why and any(k in skipped(st, time.time()) or
                (ts(st.get(f'last_{k}_ack_at')) or 0) >= sent for k in kinds):
            why = 'notice answered or skipped'
        record['secondary'] = send(CFG['secondary'], text, pending['event_key'])[0] if not why else 'stopped: ' + why
    own['current'] = record
    own.setdefault('history', []).append(record)
    own['history'] = own['history'][-50:]
    persist(own)
    print('delivered:', json.dumps(record))
    return 0

if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
