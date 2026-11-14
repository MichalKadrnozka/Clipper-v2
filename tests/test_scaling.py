import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from clipper.library import Library
from clipper.scaling import apply_saved_scale, valid_scale


class ScalingTests(unittest.TestCase):
    def test_valid_range(self):
        for value in ('nan', 'inf', '-1', '2.1', None, 'broken'):
            self.assertIsNone(valid_scale(value))
        self.assertEqual(valid_scale('1.25'), 1.25)

    def test_scale_is_applied_before_qt_and_explicit_override_wins(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'db.sqlite'
            db = Library(path); db.set_setting('ui_scale', '1.25'); db.close()
            with patch.dict(os.environ, {}, clear=True):
                apply_saved_scale(path)
                self.assertEqual(os.environ['QT_SCALE_FACTOR'], '1.25')
            with patch.dict(os.environ, {'QT_SCALE_FACTOR': '1.5'}, clear=True):
                apply_saved_scale(path)
                self.assertEqual(os.environ['QT_SCALE_FACTOR'], '1.5')
            path.rename(path.with_name('renamed.sqlite'))

    def test_bad_database_is_ignored(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            path = Path(directory) / 'invalid'; path.write_text('invalid')
            apply_saved_scale(path)
            self.assertNotIn('QT_SCALE_FACTOR', os.environ)
            path.rename(path.with_name('renamed'))
