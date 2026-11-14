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
  `care quiet on|off`, `care skip meal 60`, `care show`. `--dry-run` works here too.
- `care run` (`care_run.py`, timer: every 30 s) is the run switch. `care run start
  [--minutes N]`, `stop`, `auto`, `status`. Scheduled windows come from
  `run_windows` (times without an offset are in `timezone`). Records carry a 90-second lease, so if the timer stops
  (suspend, crash) silence fails open.
- `care_wake.py`: only `care awake` ends explicit sleep. Activity never does.
- `care_activity.py` (optional): prints the latest human message time in one T3
  Code project, for `activity_cmd`. **With no activity source (the default),
  every reminder between `night.start_hour` and `night.end_hour` (23–07) is
  deferred, and the firmer bedtime note (default 23:30) is never sent: it needs
  activity in the last 15 minutes.** The wind-down note (default 22:30) still
  goes out. Set `activity_cmd` to any command that prints your latest activity
  time (ISO 8601 with a zone) if you want the firmer note, or reminders at
  night while you are still working.

Config: `~/.config/care-reminders/config.json` (or `CARE_CONFIG`). State:
`~/.local/state/care-reminders/` (or `CARE_STATE_DIR`). Every key is optional;
see `config.example.json` and `DEFAULTS` in `care_config.py`. Times are local:
the system's zone, or an IANA name such as `"Europe/Berlin"` in `timezone`. The bedtime times may cross midnight (the default wind-down 22:30,
firm 23:30, end 07:00): a night runs from `wind_down` to the next `end`. Night
hours wrap past midnight when `start_hour` > `end_hour`; equal values mean no
night hours.

## Status

**Partial: the logic is tested, this package has not been run live.**
The sending rules (cadence, gates, bedtime, spacing, same-key retry) are
code that ran daily in an earlier version, and their tests still pass. The
config loading, `care_state.py`, the notifier receipt and the install scripts
are new. Offline checks:

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
care_send.py --dry-run  # ~/.local/lib/care-reminders/care_send.py: what it would send now
```

The timers are `care-reminders-run.timer` and `care-reminders-send.timer`.
`./install.sh --no-enable` copies files without touching systemd. The installer
refuses (and changes nothing) if `~/.local/bin/care` or one of those units
exists and was not installed by this package; `--force` replaces them.
`uninstall.sh` likewise removes only its own units and link. Under systemd,
`notify-send` needs the session bus. A normal desktop login provides it.

## Uninstall

```bash
./uninstall.sh          # stops timers, removes files; keeps ~/.config/care-reminders and the state dir
```

## Limits

- Reminders only go out once `state.json` exists (`care start`). Unreadable state
  means quiet.
- Breaks and zoom-outs are anchored to `cadence_started_at`, not to when you
  last answered. An answer only stops repeats until the next mark.
- There is no escalation (sound until you answer) and no timed breaks inside runs.
- `secondary` is one extra channel, tried once after the primary receipt. It is
  not retried.
