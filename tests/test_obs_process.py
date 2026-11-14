import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from clipper.obs_process import find_obs
from clipper.obs import OBSError

class OBSProcessTests(unittest.TestCase):
    def test_finds_user_selected_executable(self):
        with tempfile.TemporaryDirectory() as d:
            exe = Path(d)/'obs64.exe'; exe.touch()
            self.assertEqual(find_obs(str(exe)), exe)
    def test_missing_executable_is_actionable(self):
        with patch.dict('os.environ', {'ProgramFiles':'', 'ProgramW6432':'', 'ProgramFiles(x86)':''}):
            with self.assertRaises(OBSError): find_obs('')
