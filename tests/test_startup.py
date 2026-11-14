import unittest
from clipper.startup import startup_command

class StartupTests(unittest.TestCase):
    def test_command_quotes_paths_and_includes_module_for_python(self):
        self.assertEqual(startup_command(r'C:\Program Files\Clipper\Clipper.exe', True), '"C:\\Program Files\\Clipper\\Clipper.exe"')
        self.assertEqual(startup_command(r'C:\Python\pythonw.exe', False), r'C:\Python\pythonw.exe -m clipper')

class SecretTests(unittest.TestCase):
    @unittest.skipUnless(__import__('sys').platform == 'win32', 'Windows DPAPI only')
    def test_windows_secret_round_trip(self):
        from clipper.secrets import protect, unprotect
        token = protect('heslo 🔒')
        self.assertNotIn('heslo', token)
        self.assertEqual(unprotect(token), 'heslo 🔒')
