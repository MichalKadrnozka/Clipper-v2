"""Opt-in Windows per-user login integration."""
import subprocess
import sys

RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
VALUE_NAME = 'Clipper'

def startup_command(executable=None, frozen=None):
    executable = executable or sys.executable
    if frozen is None: frozen = getattr(sys, 'frozen', False)
    args = [executable] if frozen else [executable, '-m', 'clipper']
    return subprocess.list2cmdline(args)

def set_start_on_login(enabled):
    if sys.platform != 'win32': raise RuntimeError('Windows login integration is unavailable on this platform')
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if enabled:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, startup_command())
        else:
            try: winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError: pass

def starts_on_login():
    if sys.platform != 'win32': return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            return winreg.QueryValueEx(key, VALUE_NAME)[0] == startup_command()
    except FileNotFoundError:
        return False
