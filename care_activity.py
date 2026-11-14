#!/usr/bin/python3
"""Print the latest human-message time in one T3 Code project, or nothing if unknown.

Optional activity source for care_send.py (config "activity_cmd"). Uses the
installed T3 CLI's normal local authentication and its `thread activity`
command (latestHumanMessageAt); never reads messages, SQLite or auth files.

    care_activity.py --project PROJECT_ID --environment ENVIRONMENT_ID
(or CARE_T3_PROJECT / CARE_T3_ENVIRONMENT). Without both, it prints nothing.
"""
import json
import os
from pathlib import Path
import subprocess
from datetime import datetime, timezone

PROJECT = os.environ.get("CARE_T3_PROJECT", "")
ENVIRONMENT = os.environ.get("CARE_T3_ENVIRONMENT", "")
CLI = Path(os.environ.get("CARE_T3_CLI", Path.home() / ".t3/bin/t3"))


def timestamp_from_activity(output):
    if not PROJECT or not ENVIRONMENT:
        return None
    try:
        result = json.loads(output)
        if not isinstance(result, dict):
            return None
        if result.get("projectId") != PROJECT or result.get("environmentId") != ENVIRONMENT:
            return None
        value = result.get("latestHumanMessageAt")
        if not isinstance(value, str):
            return None
        stamp = datetime.fromisoformat(value.removesuffix("Z") + ("+00:00" if value.endswith("Z") else ""))
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            return None
        return stamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except (ValueError, OverflowError):
        return None


def latest_activity():
    env = {key: value for key, value in os.environ.items()
           if key not in ("LD_LIBRARY_PATH", "LD_PRELOAD")}
    try:
        child = subprocess.Popen(
            [str(CLI), "thread", "activity", "--project", PROJECT, "--json",
             "--base-dir", str(Path.home() / ".t3")],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            env=env,
        )
        try:
            output, _ = child.communicate(timeout=20)
        except subprocess.TimeoutExpired:
            # NodeRuntime handles SIGTERM by interrupting the command and running
            # scoped finalizers, including temporary MCP-session revocation.
            child.terminate()
            try:
                child.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.communicate()
            return None
        return timestamp_from_activity(output) if child.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        return None


def main(argv=None):
    global PROJECT, ENVIRONMENT
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=PROJECT)
    ap.add_argument("--environment", default=ENVIRONMENT)
    a = ap.parse_args(argv)
    PROJECT, ENVIRONMENT = a.project, a.environment
    if not PROJECT or not ENVIRONMENT:
        return
    stamp = latest_activity()
    if stamp is not None:
        print(stamp)


if __name__ == "__main__":
    main()
