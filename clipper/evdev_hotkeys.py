"""Linux global hotkeys using evdev devices without a blocking read loop."""
from __future__ import annotations

import re
import select
from contextlib import suppress

try:
    from PyQt6.QtCore import QThread, pyqtSignal
except ImportError:
    QThread = None


_MODIFIER_ALIASES = {
    'CTRL': 'KEY_LEFTCTRL',
    'CONTROL': 'KEY_LEFTCTRL',
    'LEFTCTRL': 'KEY_LEFTCTRL',
    'RIGHTCTRL': 'KEY_LEFTCTRL',
    'KEY_CTRL': 'KEY_LEFTCTRL',
    'KEY_CONTROL': 'KEY_LEFTCTRL',
    'KEY_LEFTCTRL': 'KEY_LEFTCTRL',
    'KEY_RIGHTCTRL': 'KEY_LEFTCTRL',
    'SHIFT': 'KEY_LEFTSHIFT',
    'LEFTSHIFT': 'KEY_LEFTSHIFT',
    'RIGHTSHIFT': 'KEY_LEFTSHIFT',
    'KEY_LEFTSHIFT': 'KEY_LEFTSHIFT',
    'KEY_RIGHTSHIFT': 'KEY_LEFTSHIFT',
    'ALT': 'KEY_LEFTALT',
    'LEFTALT': 'KEY_LEFTALT',
    'RIGHTALT': 'KEY_LEFTALT',
    'ALTGR': 'KEY_LEFTALT',
    'KEY_LEFTALT': 'KEY_LEFTALT',
    'KEY_RIGHTALT': 'KEY_LEFTALT',
    'WIN': 'KEY_LEFTMETA',
    'WINDOWS': 'KEY_LEFTMETA',
    'SUPER': 'KEY_LEFTMETA',
    'META': 'KEY_LEFTMETA',
    'LOGO': 'KEY_LEFTMETA',
    'LEFTMETA': 'KEY_LEFTMETA',
    'RIGHTMETA': 'KEY_LEFTMETA',
    'KEY_LEFTMETA': 'KEY_LEFTMETA',
    'KEY_RIGHTMETA': 'KEY_LEFTMETA',
}
_KEY_ALIASES = {
    'PAGEUP': 'KEY_PAGEUP',
    'PGUP': 'KEY_PAGEUP',
    'PAGEDOWN': 'KEY_PAGEDOWN',
    'PGDN': 'KEY_PAGEDOWN',
    'HOME': 'KEY_HOME',
    'END': 'KEY_END',
    'INSERT': 'KEY_INSERT',
    'INS': 'KEY_INSERT',
    'DELETE': 'KEY_DELETE',
    'DEL': 'KEY_DELETE',
    'ESCAPE': 'KEY_ESC',
    'ESC': 'KEY_ESC',
    'SPACE': 'KEY_SPACE',
    'SPACEBAR': 'KEY_SPACE',
    'KEY_PAGEUP': 'KEY_PAGEUP',
    'KEY_PAGEDOWN': 'KEY_PAGEDOWN',
    'KEY_HOME': 'KEY_HOME',
    'KEY_END': 'KEY_END',
    'KEY_INSERT': 'KEY_INSERT',
    'KEY_DELETE': 'KEY_DELETE',
    'KEY_ESC': 'KEY_ESC',
    'KEY_SPACE': 'KEY_SPACE',
}
_MODIFIERS = frozenset(_MODIFIER_ALIASES.values())
_RIGHT_TO_LEFT = {
    'KEY_RIGHTCTRL': 'KEY_LEFTCTRL',
    'KEY_RIGHTSHIFT': 'KEY_LEFTSHIFT',
    'KEY_RIGHTALT': 'KEY_LEFTALT',
    'KEY_RIGHTMETA': 'KEY_LEFTMETA',
}


def parse_evdev_hotkey(text):
    """Return a frozenset of evdev key names for one shortcut.

    Both the UI syntax (``Ctrl+Shift+A``) and legacy evdev syntax
    (``KEY_LEFTCTRL+KEY_P``) are accepted.
    """
    if not isinstance(text, str):
        raise ValueError('Use a key such as KEY_PAGEUP or Ctrl+Shift+F10')
    tokens = [token.strip().upper() for token in text.split('+')]
    if not tokens or any(not token for token in tokens):
        raise ValueError('Use a key such as KEY_PAGEUP or Ctrl+Shift+F10')

    keys = set()
    regular_key = None
    for token in tokens:
        key = _MODIFIER_ALIASES.get(token) or _KEY_ALIASES.get(token)
        if key is None:
            name = token[4:] if token.startswith('KEY_') else token
            if re.fullmatch(r'F(?:[1-9]|1[0-9]|2[0-4])', name) or re.fullmatch(r'[A-Z0-9]', name):
                key = f'KEY_{name}'
            else:
                raise ValueError(f'Unsupported evdev key: {token}')
        if key in _MODIFIERS:
            if key in keys:
                raise ValueError('Invalid or repeated modifier')
            keys.add(key)
        else:
            if regular_key is not None:
                raise ValueError('A hotkey must contain exactly one non-modifier key')
            regular_key = key
            keys.add(key)
    if regular_key is None:
        raise ValueError('A hotkey must contain one non-modifier key')
    return frozenset(keys)


if QThread:
    class EvdevHotkeys(QThread):
        activated = pyqtSignal(str)
        error = pyqtSignal(str)
        registered = pyqtSignal()

        def __init__(self, bindings, parent=None):
            super().__init__(parent)
            self.bindings = {name: parse_evdev_hotkey(key) for name, key in bindings.items()}

        def run(self):
            try:
                self._run_evdev()
            except Exception as exc:
                self.error.emit(f'Globální klávesové zkratky selhaly: {exc}')

        def _run_evdev(self):
            # Optional dependency: importing the application never imports evdev.
            try:
                import evdev
            except ImportError as exc:
                raise RuntimeError(
                    "Linuxový evdev fallback vyžaduje balíček 'evdev' "
                    '(například pip install evdev).'
                ) from exc

            ecodes = evdev.ecodes
            bindings = {
                name: frozenset(getattr(ecodes, key) for key in keys)
                for name, keys in self.bindings.items()
            }
            required = frozenset().union(*bindings.values()) if bindings else frozenset()
            right_to_left = {
                getattr(ecodes, right): getattr(ecodes, left)
                for right, left in _RIGHT_TO_LEFT.items()
                if hasattr(ecodes, right) and hasattr(ecodes, left)
            }

            devices = []
            try:
                for path in evdev.list_devices():
                    try:
                        device = evdev.InputDevice(path)
                    except OSError:
                        continue
                    try:
                        keys = device.capabilities().get(ecodes.EV_KEY, [])
                    except OSError:
                        device.close()
                        continue
                    if any(key in keys for key in required):
                        devices.append(device)
                    else:
                        device.close()
                if not devices:
                    raise RuntimeError(
                        'Nebylo nalezeno žádné dostupné klávesnicové evdev zařízení. '
                        'Zkontrolujte oprávnění k /dev/input/event*.'
                    )

                pressed = {id(device): set() for device in devices}
                active = {id(device): set() for device in devices}
                self.registered.emit()
                while not self.isInterruptionRequested():
                    readable, _, _ = select.select(devices, [], [], 0.2)
                    for device in readable:
                        # select() guarantees that this single read will not hold
                        # shutdown behind a blocking device.read() iteration.
                        event = device.read_one()
                        if event is None or event.type != ecodes.EV_KEY:
                            continue
                        code = right_to_left.get(event.code, event.code)
                        device_id = id(device)
                        if event.value == 0:
                            pressed[device_id].discard(code)
                            for name, keys in bindings.items():
                                if not keys.issubset(pressed[device_id]):
                                    active[device_id].discard(name)
                        elif event.value == 1:
                            pressed[device_id].add(code)
                            for name, keys in bindings.items():
                                if keys.issubset(pressed[device_id]) and name not in active[device_id]:
                                    active[device_id].add(name)
                                    self.activated.emit(name)
            finally:
                for device in devices:
                    with suppress(Exception):
                        device.close()
