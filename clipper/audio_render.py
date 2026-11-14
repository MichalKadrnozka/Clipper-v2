"""Render a temporary mixed-audio preview when Qt output cannot amplify."""
from pathlib import Path
from PyQt6.QtCore import QObject, QProcess, QTimer, pyqtSignal
from .tools import executable, configure_external_process


class AudioRender(QObject):
    ready = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, source, destination, levels, parent=None):
        super().__init__(parent)
        self.source = Path(source); self.destination = Path(destination)
        self.levels = tuple(levels); self.cancelled = False
        self.process = QProcess(self); configure_external_process(self.process)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._error)
        self.timed_out = False
        self.watchdog = QTimer(self); self.watchdog.setSingleShot(True); self.watchdog.setInterval(60000)
        self.watchdog.timeout.connect(self._watchdog_expired)
        self.process.readyReadStandardOutput.connect(self._activity)

    def start(self):
        if self.cancelled: return
        filters = [f'[0:{index}]volume={gain}[a{i}]' for i, (index, gain) in enumerate(self.levels)]
        filters.append(''.join(f'[a{i}]' for i in range(len(self.levels))) + f'amix=inputs={len(self.levels)}:normalize=0[aout]')
        self.watchdog.start()
        self.process.start(executable('ffmpeg'), ['-nostdin', '-v', 'error', '-progress', 'pipe:1', '-stats_period', '0.5', '-y', '-i', str(self.source),
            '-filter_complex', ';'.join(filters), '-map', '[aout]', '-vn', '-c:a', 'aac', '-b:a', '192k', str(self.destination)])

    def _activity(self):
        if not self.cancelled:
            self.process.readAllStandardOutput(); self.watchdog.start()
    def _watchdog_expired(self):
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.timed_out = True; self.process.kill()
    def _finished(self, code, status):
        self.watchdog.stop()
        if self.cancelled: return
        if code == 0 and self.destination.is_file() and self.destination.stat().st_size:
            self.ready.emit(str(self.destination)); return
        message = bytes(self.process.readAllStandardError()).decode('utf-8', 'replace')[-1000:]
        try: self.destination.unlink(missing_ok=True)
        except OSError: pass
        self.failed.emit('Příprava zvukového náhledu překročila časový limit.' if self.timed_out else message or 'Zvukový náhled se nepodařilo připravit.')

    def _error(self, error):
        if not self.cancelled and error == QProcess.ProcessError.FailedToStart:
            self.failed.emit(self.process.errorString())

    def cancel(self):
        self.cancelled = True; self.watchdog.stop()
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill(); self.process.waitForFinished(3000)
        try: self.destination.unlink(missing_ok=True)
        except OSError: pass
