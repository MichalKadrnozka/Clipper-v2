import unittest
from clipper.hotkeys import parse_hotkey

class HotkeyTests(unittest.TestCase):
    def test_windows_hotkey_mapping(self):
        self.assertEqual(parse_hotkey('F10'), (0x4000, 0x79))
        self.assertEqual(parse_hotkey('Ctrl+Shift+A'), (0x4006, 65))
        self.assertEqual(parse_hotkey('Win+F24'), (0x4008, 0x87))
    def test_invalid_shortcuts(self):
        for value in ('', 'F25', 'Ctrl+Ctrl+A', 'Ctrl+', 'Escape', 'Ctrl+Alt'):
            with self.subTest(value=value), self.assertRaises(ValueError): parse_hotkey(value)
