"""Offline tests: care_state.py edits a temporary state, and care_send.py --dry-run reads it.
Run: python3 test_care_state.py
"""
import json, os, pathlib, subprocess, sys, tempfile, unittest

HERE = pathlib.Path(__file__).resolve().parent


class CareStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: subprocess.run(['rm', '-rf', str(self.tmp)]))
        (self.tmp / 'config.json').write_text(json.dumps({'break_minutes': 1, 'zoom_out_minutes': 1,
                                                          'night': {'start_hour': 24, 'end_hour': 0}}))
        self.env = {**os.environ, 'CARE_STATE_DIR': str(self.tmp / 'state'),
                    'CARE_CONFIG': str(self.tmp / 'config.json')}

    def care(self, *args, script='care_state.py'):
        r = subprocess.run([sys.executable, '-B', str(HERE / script), *args], env=self.env,
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def state(self):
        return json.loads((self.tmp / 'state/state.json').read_text())

    def test_dry_run_writes_nothing(self):
        self.assertIn('cadence_started_at', self.care('--dry-run', 'start'))
        self.assertFalse((self.tmp / 'state').exists())

    def test_commands_and_sender_reads_them(self):
        self.assertIn('state unreadable', self.care('--dry-run', script='care_send.py'))
        self.care('start')
        self.assertIn('nothing due', self.care('--dry-run', script='care_send.py'))
        self.care('snooze', '30')
        self.assertIn('snoozed', self.care('--dry-run', script='care_send.py'))
        self.care('sleep')
        self.assertTrue(self.state()['sleeping'])
        self.care('awake')
        self.assertFalse(self.state()['sleeping'])
        self.care('ack', 'meal')
        self.assertIn('meal_next_due_at', self.state())
        self.care('quiet', 'on')
        self.assertTrue(self.state()['personal_quiet'])
        self.care('skip', 'meal', '60')
        self.assertIn('meal', self.state()['skips'])


if __name__ == '__main__':
    unittest.main()
