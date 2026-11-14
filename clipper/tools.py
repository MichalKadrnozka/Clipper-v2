"""Find bundled media executables before falling back to PATH."""
import os
from pathlib import Path
import shutil
import sys

def executable(name):
    filename = name + ('.exe' if sys.platform == 'win32' else '')
    locations = []
    if getattr(sys, 'frozen', False):
        locations.extend([Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent)), Path(sys.executable).parent])
    for folder in locations:
        candidate = folder / filename
        if candidate.is_file(): return str(candidate)
    return shutil.which(filename) or filename


def external_environment():
    """Keep frozen Linux's bundled libraries out of system subprocesses."""
    env = os.environ.copy()
    if sys.platform.startswith('linux') and getattr(sys, 'frozen', False):
        original = env.get('LD_LIBRARY_PATH_ORIG')
        if original is None: env.pop('LD_LIBRARY_PATH', None)
        else: env['LD_LIBRARY_PATH'] = original
    return env


def configure_external_process(process):
    """Apply the same environment to external tools started through Qt."""
    if sys.platform.startswith('linux') and getattr(sys, 'frozen', False):
        from PyQt6.QtCore import QProcessEnvironment
        environment = QProcessEnvironment.systemEnvironment()
        original = os.environ.get('LD_LIBRARY_PATH_ORIG')
        if original is None: environment.remove('LD_LIBRARY_PATH')
        else: environment.insert('LD_LIBRARY_PATH', original)
        process.setProcessEnvironment(environment)
