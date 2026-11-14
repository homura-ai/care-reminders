"""Offline tests for install.sh and uninstall.sh in a throwaway HOME (no systemctl).
Run: python3 test_install.py
"""
import json, os, pathlib, subprocess, sys, tempfile, unittest

HERE = pathlib.Path(__file__).resolve().parent


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = pathlib.Path(self.tmp.name)
        self.units = self.home / '.config/systemd/user'
        self.units.mkdir(parents=True)
        (self.home / '.local/bin').mkdir(parents=True)
        # An older, unrelated care setup with similar names.
        self.old_unit = self.units / 'care-run.service'
        self.old_unit.write_text('[Service]\nExecStart=%h/.local/lib/old-care/care_run.py tick\n')
        self.old_link = self.home / '.local/bin/care-run'
        self.old_link.symlink_to('../lib/old-care/care_run.py')
        self.env = {**os.environ, 'HOME': str(self.home), 'SYSTEMCTL': 'true',
                    'CARE_STATE_DIR': str(self.home / 'state')}
        self.env.pop('CARE_CONFIG', None)

    def sh(self, script, *args):
        return subprocess.run(['bash', str(HERE / script), *args], env=self.env,
                              capture_output=True, text=True, timeout=60)

    def test_install_leaves_older_care_files_alone_and_uninstall_removes_only_its_own(self):
        r = self.sh('install.sh', '--no-enable')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('old-care', self.old_unit.read_text())
        self.assertEqual(os.readlink(self.old_link), '../lib/old-care/care_run.py')
        for name in ('care-reminders-run.service', 'care-reminders-run.timer',
                     'care-reminders-send.service', 'care-reminders-send.timer'):
            self.assertTrue((self.units / name).is_file(), name)
        care = self.home / '.local/bin/care'
        status = subprocess.run([str(care), 'run', 'status'], env=self.env,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertFalse(json.loads(status.stdout)['active'])
        r = self.sh('uninstall.sh')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(care.exists() or care.is_symlink())
        self.assertFalse((self.units / 'care-reminders-send.timer').exists())
        self.assertTrue(self.old_unit.exists())
        self.assertTrue(self.old_link.is_symlink())

    def test_install_refuses_to_replace_a_foreign_unit(self):
        foreign = self.units / 'care-reminders-send.service'
        foreign.write_text('[Service]\nExecStart=/bin/true\n')
        r = self.sh('install.sh', '--no-enable')
        self.assertEqual(r.returncode, 1)
        self.assertIn('not from care-reminders', r.stderr)
        self.assertEqual(foreign.read_text(), '[Service]\nExecStart=/bin/true\n')
        self.assertFalse((self.home / '.local/lib/care-reminders').exists())
        r = self.sh('uninstall.sh')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(foreign.exists())


if __name__ == '__main__':
    unittest.main()
