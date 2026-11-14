"""Create seekable, low-bitrate H.264 preview files for codecs Qt cannot decode."""
import hashlib
import os
import uuid
from pathlib import Path
from PyQt6.QtCore import QObject, QProcess, QTimer, pyqtSignal
from .tools import executable, configure_external_process

class PreviewProxy(QObject):
    ready = pyqtSignal(str)
    failed = pyqtSignal(str)
    progress = pyqtSignal(int)
    def __init__(self, source, cache, parent=None, duration=0):
        super().__init__(parent)
        self.source = Path(source); self.cache = Path(cache); self.cache.mkdir(parents=True, exist_ok=True)
        self.duration = duration; self.progress_buffer = b''
        stat = self.source.stat()
        key = hashlib.sha256(f'{self.source.resolve()}:{stat.st_mtime_ns}:{stat.st_size}:v2'.encode()).hexdigest()
        self.final = self.cache / (key + '.mp4')
        self.temp = self.cache / (key + '.' + uuid.uuid4().hex + '.partial.mp4')
        self.process = QProcess(self)
        configure_external_process(self.process)
        self.process.readyReadStandardOutput.connect(self.read_progress)
        self.process.finished.connect(self.finished)
        self.process.errorOccurred.connect(self.error)
        self.cancelled = False; self.timed_out = False
        self.watchdog = QTimer(self); self.watchdog.setSingleShot(True); self.watchdog.setInterval(120000)
        self.watchdog.timeout.connect(self._watchdog_expired)
    def start(self):
        if self.cancelled: return
        if self.final.is_file() and self.final.stat().st_size:
            self.ready.emit(str(self.final)); return
        args = ['-nostdin', '-v', 'error', '-progress', 'pipe:1', '-stats_period', '0.5', '-y', '-i', str(self.source), '-map', '0:v:0', '-map', '0:a:0?',
                '-vf', "scale=w='trunc(min(1280,iw)/2)*2':h='trunc(ih/2)*2'", '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '30', '-pix_fmt', 'yuv420p',
                '-c:a', 'aac', '-b:a', '96k', '-movflags', '+faststart', str(self.temp)]
        self.watchdog.start(); self.process.start(executable('ffmpeg'), args)
    def read_progress(self):
        self.progress_buffer += bytes(self.process.readAllStandardOutput())
        while b'\n' in self.progress_buffer:
            line, self.progress_buffer = self.progress_buffer.split(b'\n', 1)
            key, sep, value = line.partition(b'=')
            if sep and key == b'out_time_us' and self.duration > 0:
                try:
                    progress = max(0, min(100, int(int(value) / (self.duration * 10000))))
                    self.watchdog.start(); self.progress.emit(progress)
                except ValueError: pass
    def _watchdog_expired(self):
        if self.cancelled or self.process.state() == QProcess.ProcessState.NotRunning: return
        self.timed_out = True; self.process.kill()
    def finished(self, code, status):
        self.watchdog.stop()
        if self.cancelled: return
        if code == 0 and self.temp.is_file() and self.temp.stat().st_size:
            try:
                os.replace(self.temp, self.final); self.prune_cache(); self.ready.emit(str(self.final)); return
            except OSError as exc:
                self.failed.emit(str(exc)); return
        message = bytes(self.process.readAllStandardError()).decode('utf-8', 'replace')[-2000:]
        self.temp.unlink(missing_ok=True)
        self.failed.emit('Příprava náhledu překročila časový limit.' if self.timed_out else message or 'Could not prepare video preview')
    def prune_cache(self, maximum=2_000_000_000):
        try:
            files = sorted((p for p in self.cache.glob('*.mp4') if p != self.final and '.partial.' not in p.name), key=lambda p: p.stat().st_mtime)
            total = self.final.stat().st_size + sum(p.stat().st_size for p in files)
            for path in files:
                if total <= maximum: break
                try:
                    size = path.stat().st_size; path.unlink(); total -= size
                except OSError: pass
        except OSError:
            pass
    def error(self, error):
        if not self.cancelled and error == QProcess.ProcessError.FailedToStart:
            self.failed.emit(self.process.errorString())
    def cancel(self):
        self.cancelled = True; self.watchdog.stop()
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill(); self.process.waitForFinished(3000)
        self.temp.unlink(missing_ok=True)
