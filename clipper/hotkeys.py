"""Windows global hotkeys using the operating system registration API."""
from __future__ import annotations
import re

MODIFIERS = {'ALT': 0x0001, 'CTRL': 0x0002, 'SHIFT': 0x0004, 'WIN': 0x0008}

def parse_hotkey(text):
    tokens = [s.strip().upper() for s in text.split('+')]
    if not tokens or any(not s for s in tokens):
        raise ValueError('Use a key such as F10 or Ctrl+Shift+F10')
    modifier = 0
    for token in tokens[:-1]:
        if token not in MODIFIERS or modifier & MODIFIERS[token]:
            raise ValueError('Invalid or repeated modifier')
        modifier |= MODIFIERS[token]
    key = tokens[-1]
    if re.fullmatch(r'F(?:[1-9]|1[0-9]|2[0-4])', key):
        code = 0x70 + int(key[1:]) - 1
    elif re.fullmatch(r'[A-Z0-9]', key):
        code = ord(key)
    else:
        raise ValueError('Use a letter, digit, or F1–F24 as the key')
    return modifier | 0x4000, code  # MOD_NOREPEAT

try:
    from PyQt6.QtCore import QThread, pyqtSignal
except ImportError:
    QThread = None

if QThread:
    class WindowsHotkeys(QThread):
        activated = pyqtSignal(str)
        error = pyqtSignal(str)
        registered = pyqtSignal()
        def __init__(self, bindings, parent=None):
            super().__init__(parent)
            self.bindings = [(name, *parse_hotkey(key)) for name, key in bindings.items()]
        def run(self):
            try:
                self._run_native()
            except Exception as exc:
                self.error.emit(f'Globální klávesové zkratky selhaly: {exc}')
        def _run_native(self):
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.WinDLL('user32', use_last_error=True)
            user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
            user32.RegisterHotKey.restype = wintypes.BOOL
            user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
            user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
            ids = {}
            try:
                for ident, (name, modifiers, code) in enumerate(self.bindings, 1):
                    if not user32.RegisterHotKey(None, ident, modifiers, code):
                        self.error.emit(f'Nelze zaregistrovat klávesovou zkratku {name}; může ji používat jiná aplikace.')
                        return
                    ids[ident] = name
                self.registered.emit()
                message = wintypes.MSG()
                while not self.isInterruptionRequested():
                    while user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 1):
                        if message.message == 0x0312 and message.wParam in ids:
                            self.activated.emit(ids[message.wParam])
                    self.msleep(30)
            finally:
                for ident in ids: user32.UnregisterHotKey(None, ident)
