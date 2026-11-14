"""Linux GPU Screen Recorder adapter; recording remains outside the GUI thread."""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
import os
import errno
import queue
import re
import signal
import subprocess
import sys
import threading
from .tools import external_environment

class RecorderError(RuntimeError):
    pass

def active_window_name():
    """Best-effort foreground title, without blocking the UI or requiring a portal."""
    if sys.platform == 'win32':
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            user32.GetForegroundWindow.restype = wintypes.HWND
            user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
            user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
            window = user32.GetForegroundWindow()
            length = user32.GetWindowTextLengthW(window)
            if not window or length <= 0: return ''
            title = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(window, title, len(title))
            return title.value
        except (OSError, AttributeError):
            return ''
    if os.environ.get('WAYLAND_DISPLAY'):
        commands = [('hyprctl', 'activewindow', '-j'), ('kdotool', 'getactivewindow', 'getwindowname')]
    else:
        commands = [('xdotool', 'getactivewindow', 'getwindowname')]
    for command in commands:
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=1,
                                    check=True, env=external_environment())
            title = result.stdout.strip()
            if command[0] == 'hyprctl':
                import json
                title = json.loads(title).get('title', '')
            if isinstance(title, str) and title: return title
        except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
            continue
    return ''

def _rename_noreplace(source, target):
    """Move within a directory without replacing an existing destination."""
    if sys.platform == 'win32':
        os.rename(source, target)  # Windows rename refuses an existing target.
        return
    if sys.platform.startswith('linux'):
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = getattr(libc, 'renameat2', None)
        if renameat2 is not None:
            renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
            renameat2.restype = ctypes.c_int
            if renameat2(-100, os.fsencode(source), -100, os.fsencode(target), 1) == 0:
                return
            code = ctypes.get_errno()
            if code not in (errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP):
                raise OSError(code, os.strerror(code), str(target))
    # Older kernels and filesystems may not implement renameat2. A hard link
    # still creates the destination exclusively, without copying large clips.
    os.link(source, target)
    try:
        source.unlink()
    except OSError:
        try: target.unlink()
        except OSError: pass
        raise

def name_saved_replay(path, folder, title):
    """Give a recorder-owned replay a readable name without replacing a file."""
    source = Path(path)
    try:
        if source.is_symlink() or not source.is_file() or source.parent.resolve() != Path(folder).resolve():
            return str(source)
        clean = title.split(' - ')[0].split(' | ')[0].strip()
        clean = re.sub(r'[<>:"/\\|?*™®\x00-\x1f]', '', clean)
        clean = re.sub(r'\s+', '-', clean).strip(' .-')[:80] or 'Desktop'
        if clean.upper() in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}:
            clean = 'Desktop'
        stem = source.stem
        stem = clean + stem[6:] if stem.startswith('Replay') else clean + '_' + stem
        for suffix in ('', *(f'_{i}' for i in range(2, 1000))):
            target = source.with_name(stem + suffix + source.suffix)
            try: _rename_noreplace(source, target)
            except FileExistsError: continue
            return str(target)
    except OSError:
        pass
    return str(source)

def name_replay_for_active_window(path, folder):
    """Window detection is optional and must never invalidate a saved replay."""
    try:
        title = active_window_name()
    except Exception:
        title = ''
    return name_saved_replay(path, folder, title)

@dataclass(frozen=True)
class SavedReplay:
    path: str
    first_is_mix: bool
    track_names: tuple[str, ...]

@dataclass
class CaptureSettings:
    folder: str
    display: str
    seconds: int = 60
    fps: int = 60
    codec: str = 'h264'
    container: str = 'mkv'
    quality: str = 'high'
    resolution: str = ''
    audio_devices: list[str] = field(default_factory=list)

    def command(self, executable='gpu-screen-recorder'):
        if not Path(self.folder).is_dir(): raise RecorderError('Clip folder does not exist')
        if not self.display: raise RecorderError('Select a display')
        if self.seconds not in range(1, 3601): raise RecorderError('Invalid replay duration')
        if self.fps not in range(1, 241): raise RecorderError('Invalid frame rate')
        if self.codec not in {'h264', 'hevc', 'av1'}: raise RecorderError('Unsupported codec')
        if self.container not in {'mp4', 'mkv'}: raise RecorderError('Unsupported container')
        if self.quality not in {'medium', 'high', 'very_high', 'ultra'}: raise RecorderError('Unsupported quality')
        if self.resolution and not __import__('re').fullmatch(r'\d{2,5}x\d{2,5}', self.resolution): raise RecorderError('Invalid resolution')
        cmd = [executable, '-w', self.display, '-c', self.container, '-f', str(self.fps), '-k', self.codec, '-r', str(self.seconds), '-o', self.folder, '-q', self.quality]
        if self.resolution: cmd += ['-s', self.resolution]
        sources = [source.strip() for source in self.audio_devices if source.strip()]
        # The first track is a listening mix; individual sources remain editable.
        if len(sources) > 1: cmd += ['-a', '|'.join(sources)]
        for source in sources: cmd += ['-a', source]
        return cmd

class GSRRecorder:
    def __init__(self, executable='gpu-screen-recorder'):
        self.executable = executable
        self.process = None
        self.log = deque(maxlen=100)
        self.reader = None
        self.saved = queue.SimpleQueue()
        self.expect_running = False
        self.first_is_mix = False
    @property
    def running(self):
        return self.process is not None and self.process.poll() is None
    def start(self, settings):
        if sys.platform != 'linux': raise RecorderError('GPU Screen Recorder is available only on Linux')
        if self.running: raise RecorderError('Replay buffer is already running')
        self.log.clear()
        try:
            self.process = subprocess.Popen(settings.command(self.executable), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', start_new_session=True, env=external_environment())
        except OSError as exc:
            raise RecorderError(f'Cannot launch GPU Screen Recorder: {exc}') from exc
        process = self.process
        sources = tuple(source.strip() for source in settings.audio_devices if source.strip())
        first_is_mix = len(sources) > 1
        track_names = (('Mix',) if first_is_mix else ()) + sources
        def read_log():
            with process.stdout:
                for line in process.stdout:
                    line = line.strip(); self.log.append(line)
                    candidate = line
                    for prefix in ('Saved video to ', 'Saved replay to '):
                        if line.startswith(prefix): candidate = line[len(prefix):].strip()
                    if Path(candidate).is_absolute() and Path(candidate).suffix.casefold() in ('.mp4', '.mkv'):
                        try:
                            if Path(candidate).parent.resolve() == Path(settings.folder).resolve() and Path(candidate).is_file():
                                candidate = name_replay_for_active_window(candidate, settings.folder)
                        except OSError:
                            pass  # Keep reporting the actual saved path if lookup fails.
                        self.saved.put(SavedReplay(candidate, first_is_mix, track_names))
        self.reader = threading.Thread(target=read_log, daemon=True); self.reader.start()
        try:
            code = self.process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            self.expect_running = True
            self.first_is_mix = first_is_mix
            return
        self.reader.join(timeout=1)
        raise RecorderError(f'GPU Screen Recorder exited ({code}):\n' + '\n'.join(self.log)[-3000:])
    def save(self):
        if not self.running: raise RecorderError('Replay buffer is not running')
        try: self.process.send_signal(signal.SIGUSR1)
        except OSError as exc: raise RecorderError(str(exc)) from exc
    def stop(self):
        self.expect_running = False
        if not self.running: return
        self.process.terminate()
        try: self.process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            self.process.kill(); self.process.wait(timeout=3)
        if self.reader: self.reader.join(timeout=2)

def audio_sources():
    """List PulseAudio/PipeWire source identifiers (including output monitors)."""
    try:
        result = subprocess.run(['pactl', 'list', 'short', 'sources'], capture_output=True, text=True, timeout=5, check=True, env=external_environment())
    except (OSError, subprocess.SubprocessError) as exc:
        raise RecorderError(f'Cannot list audio devices: {exc}') from exc
    result_sources = []
    for line in result.stdout.splitlines():
        columns = line.split('\t')
        if len(columns) > 1 and columns[1]: result_sources.append(columns[1])
    return result_sources
