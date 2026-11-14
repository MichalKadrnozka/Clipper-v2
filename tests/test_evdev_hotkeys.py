import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from clipper.evdev_hotkeys import EvdevHotkeys, parse_evdev_hotkey


class EvdevHotkeyTests(unittest.TestCase):
    def test_parses_legacy_and_ui_shortcuts(self):
        self.assertEqual(parse_evdev_hotkey('KEY_PAGEUP'), frozenset({'KEY_PAGEUP'}))
        self.assertEqual(
            parse_evdev_hotkey('KEY_LEFTCTRL+KEY_P'),
            frozenset({'KEY_LEFTCTRL', 'KEY_P'}),
        )
        self.assertEqual(
            parse_evdev_hotkey('Ctrl+Shift+A'),
            frozenset({'KEY_LEFTCTRL', 'KEY_LEFTSHIFT', 'KEY_A'}),
        )
        for value in ('', 'KEY_LEFTCTRL', 'Ctrl+Ctrl+A', 'KEY_A+KEY_P', 'Ctrl+'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_evdev_hotkey(value)

    def test_worker_activates_legacy_bindings_and_closes_devices(self):
        ecodes = SimpleNamespace(EV_KEY=1, KEY_PAGEUP=104, KEY_LEFTCTRL=29, KEY_P=25)

        class Device:
            def __init__(self, events):
                self.events = list(events)
                self.closed = False

            def capabilities(self):
                return {ecodes.EV_KEY: [ecodes.KEY_PAGEUP, ecodes.KEY_LEFTCTRL, ecodes.KEY_P]}

            def read_one(self):
                return self.events.pop(0)

            def close(self):
                self.closed = True

        pageup = Device([
            SimpleNamespace(type=ecodes.EV_KEY, code=ecodes.KEY_PAGEUP, value=1),
            SimpleNamespace(type=ecodes.EV_KEY, code=ecodes.KEY_PAGEUP, value=2),
            SimpleNamespace(type=ecodes.EV_KEY, code=ecodes.KEY_PAGEUP, value=0),
        ])
        combo = Device([
            SimpleNamespace(type=ecodes.EV_KEY, code=ecodes.KEY_LEFTCTRL, value=1),
            SimpleNamespace(type=ecodes.EV_KEY, code=ecodes.KEY_P, value=1),
            SimpleNamespace(type=ecodes.EV_KEY, code=ecodes.KEY_P, value=0),
            SimpleNamespace(type=ecodes.EV_KEY, code=ecodes.KEY_LEFTCTRL, value=0),
        ])
        devices = [pageup, combo]
        fake_evdev = SimpleNamespace(
            ecodes=ecodes,
            list_devices=lambda: ['/dev/input/event1', '/dev/input/event2'],
            InputDevice=lambda path: devices.pop(0),
        )
        worker = EvdevHotkeys({'save': 'KEY_PAGEUP', 'toggle': 'KEY_LEFTCTRL+KEY_P'})
        hits = []
        registrations = []
        worker.activated.connect(hits.append)
        worker.registered.connect(lambda: registrations.append(True))

        with patch.dict(sys.modules, {'evdev': fake_evdev}), \
                patch('clipper.evdev_hotkeys.select.select', side_effect=lambda devices, _, __, ___: ([d for d in devices if d.events], [], [])), \
                patch.object(worker, 'isInterruptionRequested', side_effect=lambda: not pageup.events and not combo.events):
            worker._run_evdev()

        self.assertEqual(hits, ['save', 'toggle'])
        self.assertEqual(registrations, [True])
        self.assertTrue(pageup.closed)
        self.assertTrue(combo.closed)

    def test_empty_select_does_not_prevent_shutdown(self):
        ecodes = SimpleNamespace(EV_KEY=1, KEY_PAGEUP=104)

        class Device:
            closed = False

            def capabilities(self):
                return {ecodes.EV_KEY: [ecodes.KEY_PAGEUP]}

            def read_one(self):
                raise AssertionError('read_one must not be called without an event')

            def close(self):
                self.closed = True

        device = Device()
        fake_evdev = SimpleNamespace(
            ecodes=ecodes,
            list_devices=lambda: ['/dev/input/event1'],
            InputDevice=lambda path: device,
        )
        worker = EvdevHotkeys({'save': 'KEY_PAGEUP'})
        with patch.dict(sys.modules, {'evdev': fake_evdev}), \
                patch('clipper.evdev_hotkeys.select.select', return_value=([], [], [])) as selected, \
                patch.object(worker, 'isInterruptionRequested', side_effect=[False, True]):
            worker._run_evdev()

        self.assertEqual(selected.call_args.args[3], 0.2)
        self.assertTrue(device.closed)

    def test_missing_evdev_is_reported_when_worker_starts(self):
        worker = EvdevHotkeys({'save': 'KEY_PAGEUP'})
        errors = []
        worker.error.connect(errors.append)
        with patch.dict(sys.modules, {'evdev': None}):
            worker.run()
        self.assertEqual(len(errors), 1)
        self.assertIn("balíček 'evdev'", errors[0])


if __name__ == '__main__':
    unittest.main()
