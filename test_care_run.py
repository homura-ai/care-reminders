"""Offline tests for care_run.py with a temporary config and state dir. Run: python3 test_care_run.py"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime

_TMP = Path(tempfile.mkdtemp())
os.environ['CARE_STATE_DIR'] = str(_TMP / 'state')
os.environ['CARE_CONFIG'] = str(_TMP / 'config.json')
(_TMP / 'config.json').write_text(json.dumps({'run_windows': [
    ['evening', '2030-01-02T18:00:00-05:00', '2030-01-02T21:15:00-05:00'],
    ['sunday', '2030-01-06T12:00:00-08:00', '2030-01-06T20:15:00-08:00']]}))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.dont_write_bytecode = True
import care_run as care  # noqa: E402


class CareRunTests(unittest.TestCase):
    def test_windows_come_from_config(self):
        self.assertEqual([w[0] for w in care.WINDOWS], ['evening', 'sunday'])

    def test_clock_boundaries_and_manual_precedence(self):
        for label, start, end in care.WINDOWS:
            a, b = (datetime.fromisoformat(v).timestamp() for v in (start, end))
            self.assertFalse(care.select(a - 1, {})[0])
            self.assertEqual(care.select(a, {})[3], 'clock')
            self.assertFalse(care.select(b, {})[0])
            manual = dict(active=False, since=a, until=a + 600)
            self.assertFalse(care.select(a + 1, manual)[0])
            self.assertTrue(care.select(a + 600, manual)[0])
        self.assertTrue(care.select(200, dict(active=True, since=100, until=300))[0])
        self.assertFalse(care.select(300, dict(active=True, since=100, until=300))[0])
        self.assertFalse(care.select(200, dict(active=True, since=100, until=999999))[0])

    def test_window_without_offset_uses_configured_timezone(self):
        from unittest.mock import patch
        from zoneinfo import ZoneInfo
        with patch.dict(care.C.CFG, {'timezone': 'Asia/Tokyo'}):
            self.assertEqual(care.window_time('2026-11-12T09:00:00'),
                             datetime(2026, 11, 12, 9, tzinfo=ZoneInfo('Asia/Tokyo')).timestamp())
        self.assertEqual(care.window_time('2026-11-12T09:00:00-05:00'),
                         datetime.fromisoformat('2026-11-12T14:00:00+00:00').timestamp())

    def test_reader_fails_open_and_writer_leaves_other_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'state.json').write_text('{"ack":"preserve"}')
            data = care.update(root, 200, dict(active=True, since=100, until=300))
            self.assertTrue(care.valid(data, 200))
            self.assertFalse(care.valid(data, 290))
            self.assertFalse(care.valid(data, 199))
            self.assertFalse(care.valid({}, 200))
            self.assertFalse(care.valid(dict(data, until=float('inf')), 200))
            self.assertFalse(care.valid(dict(data, expires_at=99999), 200))
            self.assertFalse(care.valid(dict(data, active='true'), 200))
            self.assertEqual(care.read(root / 'absent'), {})
            (root / 'bad').write_text('broken')
            self.assertEqual(care.read(root / 'bad'), {})
            self.assertEqual(json.loads((root / 'state.json').read_text()), {'ack': 'preserve'})
            self.assertEqual(care.read(root / 'run-state.json'), data)

    def test_cli_start_status_auto(self):
        script = str(Path(care.__file__))
        def cli(*args):
            r = subprocess.run([sys.executable, '-B', script, *args], capture_output=True, text=True,
                               env=os.environ, timeout=20)
            self.assertEqual(r.returncode, 0, r.stderr)
            return json.loads(r.stdout)
        self.assertFalse(cli('status').get('active'))
        self.assertTrue(cli('start', '--minutes', '5')['active'])
        self.assertTrue(cli('status')['active'])
        self.assertFalse(cli('auto')['active'])
        self.assertFalse(cli('status')['active'])


if __name__ == '__main__':
    try:
        unittest.main()
    finally:
        import shutil; shutil.rmtree(_TMP, ignore_errors=True)
