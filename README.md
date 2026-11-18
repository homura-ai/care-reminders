# care-reminders

Model-free reminders to look after yourself while working: a one-minute break
every 30 min, a zoom-out ("write down the top 1–2 things") every 15 min, food
when a meal is due, and a wind-down then a firmer bedtime note once per night.
They are quiet during a "run" (a focus session), while snoozed, in personal
quiet, while explicitly asleep, and at night when there has been no activity
for 90 minutes.

- `care_send.py` (timer: every 30 s) decides and sends. An unanswered reminder
  repeats every 15 min, and reminders are at least 15 min apart. A send counts
  only on the notifier's receipt. A failed send retries under the same key and
  never creates a second reminder. `--dry-run` prints the decision and text
  with no send, no write and no lock.
- `care` (`care_state.py`) records what you did: `care start`, `care ack
  break|zoom_out|meal`, `care snooze 30`, `care sleep`, `care awake`,
  `care quiet on|off`, `care skip meal 60`, `care show`. Put `--dry-run` before
  the state command, for example `care --dry-run snooze 30`; `care run` does
  not accept it.
- `care run` (`care_run.py`, timer: every 30 s) is the run switch. `care run start
  [--minutes N]`, `stop`, `auto`, `status`. Scheduled windows come from
  `run_windows` (times without an offset are in `timezone`). Records carry a 90-second lease, so if the timer stops
  (suspend, crash) silence fails open.
- `care_wake.py`: only `care awake` ends explicit sleep. Activity never does.
- `care_activity.py` (optional): prints the latest human message time in one T3
  Code project, for `activity_cmd`. With no activity source, reminders during
  night hours (23–07 by default) are deferred. The default wind-down at 22:30
  can still go out. The firmer note requires activity in the last 15 minutes.
  Set `activity_cmd` to a command that prints your latest activity time (ISO
  8601 with a zone). For the T3 helper, set it to
  `["python3", "~/.local/lib/care-reminders/care_activity.py", "--project", "PROJECT_ID", "--environment", "ENVIRONMENT_ID"]`
  with your two IDs. The helper prints nothing if either ID is absent or the
  CLI does not support `thread activity`.

Config: `~/.config/care-reminders/config.json` (or `CARE_CONFIG`). State:
`~/.local/state/care-reminders/` (or `CARE_STATE_DIR`). Every key is optional;
see `config.example.json` and `DEFAULTS` in `care_config.py`. Times use the
system zone unless you set an IANA name in `timezone`. The bedtime times may
cross midnight, for example wind-down at 22:30, firm at 23:30, and end at 07:00.
A night runs from `wind_down` to the next `end`. Night hours wrap past midnight
when `start_hour` > `end_hour`. Equal values mean no night hours.

## Status

The reminder and installation tests run offline with temporary files and
stubbed notifiers.

```bash
for t in test_care_send.py test_care_run.py test_care_wake.py test_care_activity.py test_care_state.py test_install.py; do python3 -B $t; done
```

That is 33 + 5 + 6 + 5 + 2 + 2 tests. Each uses a temporary state dir and config,
with stubbed notifiers. `test_install.py` runs `install.sh --no-enable` and
`uninstall.sh` in a throwaway HOME (with `SYSTEMCTL=true`), then `care run status`.

## Dependencies

Python 3.9+, standard library only. systemd user session. `notify-send` for the
default notifier, or any command set in `notify`. Optional: the T3 Code CLI for
`care_activity.py`.

## Install

```bash
./install.sh            # copies to ~/.local/lib/care-reminders, links care, enables both timers
care start              # begin the cadence
python3 ~/.local/lib/care-reminders/care_send.py --dry-run  # what it would send now
```

The timers are `care-reminders-run.timer` and `care-reminders-send.timer`.
`./install.sh --no-enable` copies files without touching systemd. The installer
refuses (and changes nothing) if `~/.local/bin/care` or one of those units
exists and was not installed by this package; `--force` replaces them.
`uninstall.sh` likewise removes only its own units and link. Under systemd,
`notify-send` needs the session bus. A normal desktop login provides it.

If migrating from an earlier reminder setup, disable its timers before
enabling these to avoid duplicate reminders.

## Uninstall

```bash
./uninstall.sh          # stops timers, removes files; keeps ~/.config/care-reminders and the state dir
```

## Limits

- Reminders only go out once `state.json` exists (`care start`). Unreadable state
  means quiet.
- Breaks and zoom-outs are anchored to `cadence_started_at`, not to when you
  last answered. An answer only stops repeats until the next mark.
- No reminders go out during a run.
- `secondary` is one extra channel, tried once after the primary receipt. It is
  not retried.
