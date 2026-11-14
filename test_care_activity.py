import contextlib
import io
import json
import subprocess
import unittest
from unittest.mock import MagicMock, call, patch

import care_activity as activity

activity.PROJECT, activity.ENVIRONMENT = "test-project", "test-environment"


def response(value="2026-11-11T11:06:05-05:00", **overrides):
    return json.dumps({"environmentId": activity.ENVIRONMENT,
                       "projectId": activity.PROJECT,
                       "latestHumanMessageAt": value, **overrides})


class CareActivityTests(unittest.TestCase):
    def test_normalizes_timezone_and_rejects_unknown_or_wrong_scope(self):
        self.assertEqual(activity.timestamp_from_activity(response()), "2026-11-11T16:06:05Z")
        for output in ("not json", "[]", "null", response(None), response("bad"),
                       response("2026-11-11T11:06:05"),
                       response(projectId="another-project"),
                       response(environmentId="another-environment"),
                       json.dumps({"projectId": activity.PROJECT,
                                   "environmentId": activity.ENVIRONMENT})):
            with self.subTest(output=output):
                self.assertIsNone(activity.timestamp_from_activity(output))

    def test_only_timestamp_is_printed_and_supported_cli_is_used(self):
        stdout = io.StringIO()
        child = MagicMock(returncode=0)
        child.communicate.return_value = (response(threads=[{"private": "do not print"}]), None)
        with patch.object(activity.subprocess, "Popen", return_value=child) as run:
            with contextlib.redirect_stdout(stdout):
                activity.main([])
        self.assertEqual(stdout.getvalue(), "2026-11-11T16:06:05Z\n")
        args = run.call_args.args[0]
        self.assertEqual(args[:3], [str(activity.CLI), "thread", "activity"])
        self.assertEqual(args[args.index("--project") + 1], activity.PROJECT)
        self.assertEqual(run.call_args.kwargs["stderr"], subprocess.DEVNULL)
        child.terminate.assert_not_called()
        child.kill.assert_not_called()

    def test_cli_failure_and_unsupported_server_print_nothing(self):
        for outcome in (OSError("private error"), (1, "private error"), (0, "{}")):
            with self.subTest(outcome=outcome):
                stdout = io.StringIO()
                error = io.StringIO()
                if isinstance(outcome, Exception):
                    kwargs = {"side_effect": outcome}
                else:
                    child = MagicMock(returncode=outcome[0])
                    child.communicate.return_value = (outcome[1], None)
                    kwargs = {"return_value": child}
                with patch.object(activity.subprocess, "Popen", **kwargs):
                    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(error):
                        activity.main([])
                self.assertEqual(stdout.getvalue(), "")
                self.assertEqual(error.getvalue(), "")

    def test_timeout_allows_graceful_cli_session_cleanup(self):
        child = MagicMock(returncode=0)
        child.communicate.side_effect = [subprocess.TimeoutExpired("t3", 20), (response(), None)]
        stdout = io.StringIO()
        with patch.object(activity.subprocess, "Popen", return_value=child):
            with contextlib.redirect_stdout(stdout):
                activity.main([])
        self.assertEqual(child.mock_calls, [call.communicate(timeout=20),
                                          call.terminate(), call.communicate(timeout=5)])
        self.assertEqual(stdout.getvalue(), "")

    def test_unresponsive_cli_is_killed_only_after_cleanup_grace(self):
        child = MagicMock(returncode=-9)
        child.communicate.side_effect = [subprocess.TimeoutExpired("t3", 20),
                                        subprocess.TimeoutExpired("t3", 5), ("", None)]
        with patch.object(activity.subprocess, "Popen", return_value=child):
            self.assertIsNone(activity.latest_activity())
        self.assertEqual(child.mock_calls, [call.communicate(timeout=20), call.terminate(),
                                          call.communicate(timeout=5), call.kill(), call.communicate()])


if __name__ == "__main__":
    unittest.main()
