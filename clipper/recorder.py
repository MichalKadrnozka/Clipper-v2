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
class RecordingAudioTrack:
    """One GSR input; gain is applied later by the clip editor, not by GSR."""
    device: str
    name: str = ''
    gain: float = 1.0

    @classmethod
    def from_value(cls, value):
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            return cls(value)
        if isinstance(value, dict):
            return cls(str(value.get('device', '')), str(value.get('name', '')), value.get('gain', 1.0))
        raise RecorderError('Invalid audio track')


def _recording_tracks(settings):
    configured = settings.audio_tracks or settings.audio_devices
    tracks = []
    for value in configured:
        track = RecordingAudioTrack.from_value(value)
        device = track.device.strip()
        if not device:
            continue
        try:
            gain = float(track.gain)
        except (TypeError, ValueError) as exc:
            raise RecorderError('Invalid audio gain') from exc
        if not 0 <= gain <= 1.5:
            raise RecorderError('Audio gain must be between 0 and 150%')
        tracks.append(RecordingAudioTrack(device, track.name.strip() or device, gain))
    return tracks


@dataclass(frozen=True)
class SavedReplay:
    path: str
    first_is_mix: bool
    track_names: tuple[str, ...]
    # Audio stream indexes, including a possible Mix at index 1, to editor gain.
    track_volumes: dict[int, float] = field(default_factory=dict)

    @property
    def track_gains(self):
        return tuple(self.track_volumes.get(index, 1.0)
                     for index in range(1, len(self.track_names) + 1))


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
    audio_tracks: list[RecordingAudioTrack] = field(default_factory=list)

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
        tracks = _recording_tracks(self)
        sources = [track.device for track in tracks]
        # The first track is a listening mix; individual sources remain editable.
        if len(sources) > 1: cmd += ['-a', '|'.join(sources)]
        for source in sources: cmd += ['-a', source]
        return cmd

class GSRRecorder:
    def __init__(self, executable='gpu-screen-recorder'):
        self.executable = executable
        self.process = None
        self.log = deque(maxlen=100)
        self._log_lock = threading.Lock()
        self._save_lock = threading.Lock()
        self._pending_saves = 0
        self.reader = None
        self.saved = queue.SimpleQueue()
        self.expect_running = False
        self.first_is_mix = False
    @property
    def running(self):
        return self.process is not None and self.process.poll() is None
    @property
    def pending_saves(self):
        with self._save_lock: return self._pending_saves
    def log_snapshot(self):
        with self._log_lock: return '\n'.join(self.log)
    def _save_completed(self):
        with self._save_lock:
            if self._pending_saves: self._pending_saves -= 1
    def start(self, settings):
        if sys.platform != 'linux': raise RecorderError('GPU Screen Recorder is available only on Linux')
        if self.running: raise RecorderError('Replay buffer is already running')
        with self._log_lock: self.log.clear()
        with self._save_lock: self._pending_saves = 0
        try:
            self.process = subprocess.Popen(settings.command(self.executable), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', start_new_session=True, env=external_environment())
        except OSError as exc:
            raise RecorderError(f'Cannot launch GPU Screen Recorder: {exc}') from exc
        process = self.process
        tracks = _recording_tracks(settings)
        first_is_mix = len(tracks) > 1
        track_names = (('Mix',) if first_is_mix else ()) + tuple(track.name for track in tracks)
        track_volumes = {index: track.gain for index, track in enumerate(
            tracks, start=2 if first_is_mix else 1)}
        if first_is_mix:
            track_volumes[1] = 1.0
            track_volumes = dict(sorted(track_volumes.items()))
        def read_log():
            with process.stdout:
                for line in process.stdout:
                    line = line.strip()
                    with self._log_lock: self.log.append(line)
                    candidate = line
                    for prefix in ('Saved video to ', 'Saved replay to '):
                        if line.startswith(prefix): candidate = line[len(prefix):].strip()
                    if Path(candidate).is_absolute() and Path(candidate).suffix.casefold() in ('.mp4', '.mkv'):
                        try:
                            if Path(candidate).parent.resolve() == Path(settings.folder).resolve() and Path(candidate).is_file():
                                candidate = name_replay_for_active_window(candidate, settings.folder)
                        except OSError:
                            pass  # Keep reporting the actual saved path if lookup fails.
                        self.saved.put(SavedReplay(candidate, first_is_mix, track_names, track_volumes))
                        self._save_completed()
        self.reader = threading.Thread(target=read_log, daemon=True); self.reader.start()
        try:
            code = self.process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            self.expect_running = True
            self.first_is_mix = first_is_mix
            return
        self.reader.join(timeout=1)
        raise RecorderError(f'GPU Screen Recorder exited ({code}):\n' + self.log_snapshot()[-3000:])
    def save(self):
        if not self.running: raise RecorderError('Replay buffer is not running')
        with self._save_lock: self._pending_saves += 1
        try: self.process.send_signal(signal.SIGUSR1)
        except OSError as exc:
            self._save_completed(); raise RecorderError(str(exc)) from exc
    def stop(self):
        self.expect_running = False
        error = None
        try:
            if self.running:
                self.process.terminate()
                try: self.process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    self.process.kill(); self.process.wait(timeout=3)
        except OSError as exc: error = RecorderError(str(exc))
        except subprocess.SubprocessError as exc: error = RecorderError(str(exc))
        finally:
            if self.reader: self.reader.join(timeout=2)
        if error: raise error

DEFAULT_AUDIO_OUTPUT = 'default_output'
DEFAULT_AUDIO_INPUT = 'default_input'


def default_audio_output():
    """A safe GSR alias which follows the current PulseAudio/PipeWire output."""
    return DEFAULT_AUDIO_OUTPUT


def audio_sources():
    """List GSR default aliases and PulseAudio/PipeWire source identifiers."""
    try:
        result = subprocess.run(['pactl', 'list', 'short', 'sources'], capture_output=True, text=True, timeout=5, check=True, env=external_environment())
    except (OSError, subprocess.SubprocessError) as exc:
        raise RecorderError(f'Cannot list audio devices: {exc}') from exc
    result_sources = [DEFAULT_AUDIO_OUTPUT, DEFAULT_AUDIO_INPUT]
    for line in result.stdout.splitlines():
        columns = line.split('\t')
        if len(columns) > 1 and columns[1] and columns[1] not in result_sources:
            result_sources.append(columns[1])
    return result_sources
