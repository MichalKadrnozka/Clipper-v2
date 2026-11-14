import tempfile
import unittest
from pathlib import Path
from clipper.linux_identity import ensure_desktop_entry, APP_ID

class LinuxIdentityTests(unittest.TestCase):
    def test_desktop_entry_is_created_without_overwriting_existing(self):
        with tempfile.TemporaryDirectory() as root:
            path=ensure_desktop_entry(root)
            self.assertEqual(path.name, APP_ID + '.desktop')
            self.assertIn('Name=Clipper', path.read_text())
            path.write_text('custom')
            self.assertEqual(ensure_desktop_entry(root).read_text(), 'custom')

    def test_opt_in_login_entry_can_be_removed(self):
        from clipper.linux_identity import set_login_start, starts_on_login
        with tempfile.TemporaryDirectory() as data, tempfile.TemporaryDirectory() as config:
            self.assertFalse(starts_on_login(config))
            set_login_start(True, data, config)
            self.assertTrue(starts_on_login(config))
            set_login_start(False, data, config)
            self.assertFalse(starts_on_login(config))
