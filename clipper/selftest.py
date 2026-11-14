"""Smoke-check critical components inside a packaged desktop build."""
from __future__ import annotations
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from .tools import executable, external_environment


def run_selftest(report_path):
    checks = {}
    try:
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtMultimedia import QMediaPlayer, QVideoSink
        from websockets.sync.client import connect  # noqa: F401
        from .editor import Editor  # noqa: F401
        from .obs import OBSClient  # noqa: F401
        app = QApplication.instance() or QApplication([])
        player = QMediaPlayer(); sink = QVideoSink(); player.setVideoSink(sink)
        player.setVideoSink(None)
        checks['qt_multimedia'] = True
        checks['websocket_and_editor_import'] = True
        if sys.platform == 'linux' and getattr(sys, 'frozen', False):
            import evdev  # noqa: F401
            import dbus_next  # noqa: F401
            from .evdev_hotkeys import EvdevHotkeys  # noqa: F401
            from .portal_hotkeys import PortalHotkeys  # noqa: F401
            checks['linux_hotkey_backends'] = True
        for name in ('ffmpeg', 'ffprobe'):
            path = executable(name)
            if sys.platform == 'win32' and getattr(sys, 'frozen', False):
                roots = [Path(sys.executable).parent.resolve(), Path(getattr(sys, '_MEIPASS', sys.executable)).resolve()]
                if not Path(path).is_file() or not any(Path(path).resolve().parent == root for root in roots):
                    checks[name] = False
                    continue
            proc = subprocess.run([path, '-version'], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                timeout=10, env=external_environment(), creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
            checks[name] = proc.returncode == 0
        checks['ok'] = all(checks.values())
    except Exception as exc:
        checks['ok'] = False
        checks['error'] = str(exc)
    try:
        Path(report_path).write_text(json.dumps(checks, indent=2), encoding='utf-8')
    except OSError:
        return 1
    return 0 if checks['ok'] else 1


def run_ui_selftest(report_path):
    """Open and close the packaged main window using an isolated empty library."""
    checks = {}
    previous = {key: os.environ.get(key) for key in ('APPDATA', 'XDG_DATA_HOME')}
    window = None
    try:
        with tempfile.TemporaryDirectory(prefix='clipper-ui-selftest-') as data:
            os.environ['APPDATA'] = data
            os.environ['XDG_DATA_HOME'] = data
            from PyQt6.QtCore import QEventLoop, QTimer
            from PyQt6.QtWidgets import QApplication
            from .app import Window
            app = QApplication.instance() or QApplication([])
            app.setQuitOnLastWindowClosed(False)
            window = Window(); window.show()
            loop = QEventLoop(); QTimer.singleShot(250, loop.quit); loop.exec()
            checks['window_visible'] = window.isVisible()
            checks['tabs'] = window.tabs.count() == 3
            checks['library'] = window.list is not None
            window.quitting = True
            checks['closed'] = window.close()
            checks['ok'] = all(checks.values())
    except Exception as exc:
        checks['ok'] = False
        checks['error'] = str(exc)
        if window is not None:
            try: window.quitting = True; window.close()
            except Exception: pass
    finally:
        for key, value in previous.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value
    try:
        Path(report_path).write_text(json.dumps(checks, indent=2), encoding='utf-8')
    except OSError:
        return 1
    return 0 if checks['ok'] else 1
