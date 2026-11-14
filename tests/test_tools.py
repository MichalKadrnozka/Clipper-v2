import os
import unittest
from unittest.mock import patch
from clipper.tools import external_environment, configure_external_process


class ExternalEnvironmentTests(unittest.TestCase):
    def test_frozen_linux_restores_original_library_path(self):
        with patch('clipper.tools.sys.platform', 'linux'), patch('clipper.tools.sys.frozen', True, create=True):
            with patch.dict(os.environ, {'LD_LIBRARY_PATH': '/bundled', 'LD_LIBRARY_PATH_ORIG': '/custom'}, clear=True):
                self.assertEqual(external_environment()['LD_LIBRARY_PATH'], '/custom')
                from PyQt6.QtCore import QProcess
                process = QProcess(); configure_external_process(process)
                self.assertEqual(process.processEnvironment().value('LD_LIBRARY_PATH'), '/custom')
            with patch.dict(os.environ, {'LD_LIBRARY_PATH': '/bundled'}, clear=True):
                self.assertNotIn('LD_LIBRARY_PATH', external_environment())
                process = QProcess(); configure_external_process(process)
                self.assertFalse(process.processEnvironment().contains('LD_LIBRARY_PATH'))

    def test_development_and_windows_environment_is_untouched(self):
        with patch.dict(os.environ, {'LD_LIBRARY_PATH': '/custom'}, clear=True):
            with patch('clipper.tools.sys.frozen', False, create=True):
                self.assertEqual(external_environment()['LD_LIBRARY_PATH'], '/custom')
            with patch('clipper.tools.sys.frozen', True, create=True), patch('clipper.tools.sys.platform', 'win32'):
                self.assertEqual(external_environment()['LD_LIBRARY_PATH'], '/custom')
