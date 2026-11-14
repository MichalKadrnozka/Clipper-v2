"""Locate and launch OBS on Windows without creating duplicate instances."""
import os
from pathlib import Path
import subprocess
import sys
import time
from .obs import OBSError

def find_obs(configured=''):
    candidates = [Path(configured)] if configured else []
    for key in ('ProgramFiles', 'ProgramW6432', 'ProgramFiles(x86)'):
        root = os.environ.get(key)
        if root: candidates.append(Path(root) / 'obs-studio' / 'bin' / '64bit' / 'obs64.exe')
    for path in candidates:
        if path.is_file(): return path
    raise OBSError('OBS Studio nebylo nalezeno. Vyber obs64.exe v nastavení.')

def obs_running():
    if sys.platform != 'win32': raise OBSError('Automatic OBS launch is only available on Windows')
    try:
        result = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq obs64.exe', '/FO', 'CSV', '/NH'],
            capture_output=True, text=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
    except OSError as exc: raise OBSError(str(exc)) from exc
    if result.returncode != 0: raise OBSError('Unable to determine whether OBS is already running')
    return '"obs64.exe"' in result.stdout.casefold()

def launch_obs(executable=''):
    if sys.platform != 'win32': raise OBSError('Automatic OBS launch is only available on Windows')
    if obs_running(): return False
    path = find_obs(executable)
    try:
        subprocess.Popen([str(path), '--minimize-to-tray', '--profile', 'Clipper Capture', '--collection', 'Clipper Capture'], cwd=str(path.parent),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
    except OSError as exc: raise OBSError(f'Could not launch OBS: {exc}') from exc
    return True

def wait_until_connected(client, timeout=40):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try: client.request('GetVersion'); return
        except OBSError as exc: last = exc; time.sleep(1)
    raise OBSError(f'OBS se nepodařilo připojit: {last}')
