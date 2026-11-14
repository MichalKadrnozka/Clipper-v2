"""Bounded, disk-cached thumbnail generation using asynchronous QProcesses."""
from collections import deque, OrderedDict
import hashlib
import os
import time
import uuid
from pathlib import Path
from PyQt6.QtCore import QObject, QProcess, QTimer, pyqtSignal
from .tools import executable, configure_external_process

class Thumbnails(QObject):
    ready = pyqtSignal(str, str)
    failed = pyqtSignal(str)
    def __init__(self, cache, parent=None):
        super().__init__(parent)
        self.cache = Path(cache); self.cache.mkdir(parents=True, exist_ok=True)
        self.pending = set(); self.queue = deque(); self.active = {}; self.closing = False
        self.failed_until = OrderedDict()
    def _output_for(self, path):
        stat = path.stat()
        key = hashlib.sha256(f'{path.resolve()}:{stat.st_mtime_ns}:{stat.st_size}'.encode()).hexdigest()
        return self.cache / (key + '.jpg')
    def request(self, path):
        path = Path(path)
        try:
            output = self._output_for(path)
        except OSError: return None
        if output.is_file() and output.stat().st_size: return output
        deadline = self.failed_until.get(output)
        if deadline is not None:
            if time.monotonic() < deadline: return None
            del self.failed_until[output]
        if str(path) not in self.pending:
            self.pending.add(str(path)); self.queue.append((path, output)); self._schedule()
        return None
    def unavailable(self, path):
        try: return self.failed_until.get(self._output_for(Path(path)), 0) > time.monotonic()
        except OSError: return False
    def _schedule(self):
        while not self.closing and self.queue and len(self.active) < 2:
            path, output = self.queue.popleft(); self._start(path, output, 1)
    def _start(self, path, output, offset):
        process = QProcess(self)
        configure_external_process(process)
        temporary = output.with_name(output.stem + '.' + uuid.uuid4().hex + '.tmp.jpg')
        self.active[process] = (path, output, offset, temporary)
        process.setStandardErrorFile(QProcess.nullDevice())
        timer = QTimer(process); timer.setSingleShot(True); timer.timeout.connect(process.kill); timer.start(20000)
        process.finished.connect(lambda code, status, p=process: self._finished(p, code))
        process.errorOccurred.connect(lambda error, p=process: self._error(p, error))
        process.start(executable('ffmpeg'), ['-nostdin', '-v', 'error', '-y', '-ss', str(offset), '-i', str(path), '-frames:v', '1', '-vf', 'scale=320:-2', str(temporary)])
    def _error(self, process, error):
        if error == QProcess.ProcessError.FailedToStart: self._finished(process, -1)
    def _finished(self, process, code):
        data = self.active.pop(process, None)
        if data is None: return
        path, output, offset, temporary = data
        process.deleteLater()
        try: current = self._output_for(path)
        except OSError: current = None
        if current != output:
            temporary.unlink(missing_ok=True); self.pending.discard(str(path))
            if current is not None and not self.closing: self.request(path)
            self._schedule(); return
        if not self.closing and code == 0 and temporary.is_file() and temporary.stat().st_size:
            try:
                os.replace(temporary, output)
            except OSError:
                temporary.unlink(missing_ok=True); self.pending.discard(str(path)); self._schedule(); return
            self.pending.discard(str(path)); self.ready.emit(str(path), str(output))
        elif not self.closing and offset == 1:
            temporary.unlink(missing_ok=True); self._start(path, output, 0)
        else:
            temporary.unlink(missing_ok=True); self.pending.discard(str(path))
            if not self.closing:
                self.failed_until[output] = time.monotonic() + 30
                self.failed_until.move_to_end(output)
                while len(self.failed_until) > 512: self.failed_until.popitem(last=False)
                self.failed.emit(str(path))
        self._schedule()
    def shutdown(self):
        self.closing = True; self.queue.clear()
        for process in list(self.active):
            process.kill(); process.waitForFinished(3000)
        self.active.clear(); self.pending.clear(); self.failed_until.clear()
