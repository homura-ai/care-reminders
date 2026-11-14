#!/usr/bin/python3
"""Settings shared by the care scripts: JSON at $CARE_CONFIG or ~/.config/care-reminders/config.json.

Every key is optional. Nested dicts ("lines", "bedtime", "night") merge key by key.
"""
import json
import os
import pathlib
from datetime import datetime
from zoneinfo import ZoneInfo

HERE = pathlib.Path(__file__).resolve().parent
DEFAULTS = {
    'state_dir': '~/.local/state/care-reminders',
    'timezone': None,            # e.g. "America/New_York"; default: the system's local zone
    'app_name': 'Care',
    'prefix': '',                # put before every reminder, e.g. "Care: "
    'lines': {
        'break': 'Take a one-minute break. After your break, zoom out for a moment.',
        'break_and_zoom': 'Take a one-minute break, then zoom out and write down the top 1–2 things to do.',
        'meal': 'Eat if you have not.',
        'zoom_out': 'Zoom out and write down the top 1–2 things to do.',
        'wind_down': 'Your bedtime is near. Start winding down for sleep.',
        'firm': 'It is past your bedtime. Please stop and go to sleep now.',
    },
    'break_minutes': 30,
    'zoom_out_minutes': 15,
    'spacing_minutes': 15,       # minimum gap between reminders; unanswered ones repeat at this gap
    'bedtime': {'wind_down': '22:30', 'firm': '23:30', 'end': '07:00',
                'firm_needs_activity_minutes': 15},
    'night': {'start_hour': 23, 'end_hour': 7, 'idle_minutes': 90},
    # Primary channel: a reminder counts as sent only on its receipt ("exit0",
    # "stdout" = exit 0 and output, or an exact last stdout line such as "queued").
    # argv/stdin may use {text}, {key} and {app}.
    'notify': {'argv': ['notify-send', '--app-name={app}', '--urgency=normal', '{app}', '{text}'],
               'receipt': 'exit0'},
    'secondary': None,           # optional extra channel, tried once after the primary receipt
    'activity_cmd': None,        # argv printing your latest activity time (ISO 8601 with zone)
    'run_windows': [],           # [[label, start ISO, end ISO], ...]: scheduled quiet runs
    'run_max_hours': 12,
}


def load():
    cfg = json.loads(json.dumps(DEFAULTS))
    path = pathlib.Path(os.environ.get('CARE_CONFIG', '~/.config/care-reminders/config.json')).expanduser()
    if path.exists():
        data = json.loads(path.read_text())
        for key, value in data.items():
            if isinstance(cfg.get(key), dict) and isinstance(value, dict):
                cfg[key].update(value)
            else:
                cfg[key] = value
    return cfg


CFG = load()


def state_dir():
    return pathlib.Path(os.environ.get('CARE_STATE_DIR', CFG['state_dir'])).expanduser()


def zone():
    return ZoneInfo(CFG['timezone']) if CFG['timezone'] else None


def local(ts):
    """Local datetime for a Unix time (naive local time when no zone is configured)."""
    return datetime.fromtimestamp(ts, zone())
