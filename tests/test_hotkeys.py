import unittest
from clipper.hotkeys import parse_hotkey

class HotkeyTests(unittest.TestCase):
    def test_windows_hotkey_mapping(self):
        self.assertEqual(parse_hotkey('F10'), (0x4000, 0x79))
        self.assertEqual(parse_hotkey('Ctrl+Shift+A'), (0x4006, 65))
        self.assertEqual(parse_hotkey('Win+F24'), (0x4008, 0x87))
    def test_windows_named_keys_and_modifier_aliases(self):
        expected = {
            'PageUp': 0x21,
            'PageDown': 0x22,
            'Home': 0x24,
            'End': 0x23,
            'Insert': 0x2D,
            'Delete': 0x2E,
            'Escape': 0x1B,
            'Space': 0x20,
        }
        for key, code in expected.items():
            with self.subTest(key=key):
                self.assertEqual(parse_hotkey(key), (0x4000, code))
        self.assertEqual(parse_hotkey('Control+Super+Delete'), (0x400A, 0x2E))
        self.assertEqual(parse_hotkey('Ctrl+Shift+Space'), (0x4006, 0x20))
    def test_invalid_shortcuts(self):
        for value in ('', 'F25', 'Ctrl+Ctrl+A', 'Ctrl+Space+', 'Ctrl+Alt', 'PageUp+A'):
            with self.subTest(value=value), self.assertRaises(ValueError): parse_hotkey(value)
