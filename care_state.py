#!/usr/bin/python3
"""Edit the care state (state.json) that care_send.py reads. All writes hold state.lock.

    care start                    start the break/zoom-out cadence now (creates state.json)
    care ack break|zoom_out|meal  record that you did it (a meal also sets the next meal in 3 h)
    care snooze MINUTES           no reminders until then
    care sleep | care awake       explicit sleep; only "awake" ends it
    care quiet on|off             personal quiet until turned off
    care skip KIND MINUTES        leave one kind out for a while
    care show                     print the state
    care run start|stop|auto|status [--minutes N]   the run switch (care_run.py)
Add --dry-run before the command to print the new state without writing it.
"""
import json, os, pathlib, sys, time
from datetime import datetime, timezone
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import care_config as C
import care_wake

STATE = C.state_dir()/'state.json'
MEAL_HOURS = 3
KINDS = ('break', 'zoom_out', 'meal', 'wind_down', 'firm')


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec='seconds')


def change(state, args, now):
    cmd = args[0] if args else 'show'
    if cmd == 'start':
        state['cadence_started_at'] = iso(now)
    elif cmd == 'ack' and len(args) == 2 and args[1] in ('break', 'zoom_out', 'meal'):
        state[f'last_{args[1]}_ack_at'] = iso(now)
        if args[1] == 'meal':
            state['meal_next_due_at'] = iso(now + MEAL_HOURS*3600)
    elif cmd == 'snooze' and len(args) == 2 and args[1].isdigit():
        state['postponed_until'] = iso(now + int(args[1])*60)
    elif cmd == 'sleep':
        state.update(sleeping=True, sleep_state='sleeping', sleeping_since=iso(now))
    elif cmd == 'awake':
        state['awake_confirmed_at'] = iso(now + 1)  # strictly after a same-second sleep
    elif cmd == 'quiet' and args[1:] in (['on'], ['off']):
        state['personal_quiet'] = args[1] == 'on'
    elif cmd == 'skip' and len(args) == 3 and args[1] in KINDS and args[2].isdigit():
        state.setdefault('skips', {})[args[1]] = iso(now + int(args[2])*60)
    elif cmd != 'show':
        raise SystemExit(__doc__)
    return cmd != 'show'


def main(argv):
    if argv[:1] == ['run']:
        script = str(pathlib.Path(__file__).resolve().parent/'care_run.py')
        os.execv(sys.executable, [sys.executable, script, *argv[1:]])
    dry = argv[:1] == ['--dry-run']
    args = argv[1:] if dry else argv
    if dry or not args or args[0] == 'show':
        try:
            state = json.loads(STATE.read_text())
        except (OSError, ValueError):
            state = {}
        change(state, args, time.time())
        print(json.dumps(state, indent=2))
        return 0
    STATE.parent.mkdir(parents=True, exist_ok=True)
    with care_wake.state_lock():
        try:
            state = json.loads(STATE.read_text())
        except (OSError, ValueError):
            state = {}
        change(state, args, time.time())
        tmp = STATE.with_suffix('.cli.tmp')
        tmp.write_text(json.dumps(state, indent=2)); tmp.replace(STATE)
    if args[0] == 'awake':
        care_wake.reconcile(STATE, None)
    print(json.dumps(json.loads(STATE.read_text()), indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
