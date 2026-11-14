"""A single, silent hover player shared by all cards in the library."""
from __future__ import annotations

import json
import math
import os
import sqlite3
import tempfile
import time
from pathlib import Path

# Keep preview decoding consistent with the editor on systems where Qt's
# hardware decoder cannot handle a particular recording.
os.environ.setdefault('QT_FFMPEG_DECODING_HW_DEVICE_TYPES', ',')

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QModelIndex, QObject, QPersistentModelIndex, QProcess, QTimer, QUrl, Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtMultimedia import QMediaPlayer, QVideoSink
from .tools import configure_external_process, executable


class GalleryPreview(QObject):
    frameReady = pyqtSignal()

    def __init__(self, view, library, parent=None):
        super().__init__(parent)
        self.view = view
        self.viewport = view.viewport()
        self.library = library
        self.path = None
        self.index = QPersistentModelIndex()
        self.player = None
        self.sink = None
        self.process = None
        self.tempdir = None
        self.frame = QPixmap()
        self.generation = 0
        self.last_frame_time = 0.
        self.start_ms = 0
        self.end_ms = 0
        self.range_start = 0.
        self.range_end = 1.
        self.saved_range = (0., 1.)
        self.source_duration = 0.
        self.using_proxy = False
        self.proxy_attempted = False
        self.initial_seek = False
        self.delay = QTimer(self)
        self.delay.setSingleShot(True)
        self.delay.setInterval(350)
        self.delay.timeout.connect(self._start)
        self.watchdog = QTimer(self)
        self.watchdog.setSingleShot(True)
        self.watchdog.setInterval(3000)
        self.watchdog.timeout.connect(self._watchdog_expired)
        self.view.setMouseTracking(True)
        self.viewport.setMouseTracking(True)
        self.viewport.installEventFilter(self)
        self.view.verticalScrollBar().valueChanged.connect(lambda _: self.stop())
        self.view.horizontalScrollBar().valueChanged.connect(lambda _: self.stop())

    def eventFilter(self, watched, event):
        if watched is self.viewport and not sip.isdeleted(self.view):
            kind = event.type()
            if kind == QEvent.Type.MouseMove:
                index = self.view.indexAt(event.position().toPoint())
                value = index.data(Qt.ItemDataRole.UserRole) if index.isValid() else None
                path = str(value) if value else None
                if path != self.path:
                    self.stop()
                    self.path = path
                    if path:
                        self.index = QPersistentModelIndex(index)
                        self.delay.start()
            elif kind in (QEvent.Type.Leave, QEvent.Type.Hide, QEvent.Type.MouseButtonPress, QEvent.Type.Wheel):
                self.stop()
        return False

    def pixmap_for(self, index):
        if self.path and index.data(Qt.ItemDataRole.UserRole) == self.path:
            return self.frame
        return QPixmap()

    def _start(self):
        if not self.path or not Path(self.path).is_file(): return
        try:
            edit = self.library.edit_for(self.path)
            start, end = float(edit.get('in', 0)), float(edit.get('out', 1))
            if not (math.isfinite(start) and math.isfinite(end) and 0 <= start < end <= 1):
                start, end = 0., 1.
        except (OSError, sqlite3.Error, TypeError, ValueError):
            start, end = 0., 1.
        self.saved_range = (start, end)
        self.source_duration = 0.
        self.proxy_attempted = False
        self.generation += 1
        generation = self.generation
        process = self._new_process(generation, self._probed, 8000)
        process.start(executable('ffprobe'), ['-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'stream=codec_name:format=duration', '-of', 'json', self.path])

    def _new_process(self, generation, callback, timeout):
        process = QProcess(self)
        configure_external_process(process)
        self.process = process
        timer = QTimer(process); timer.setSingleShot(True); timer.timeout.connect(process.kill); timer.start(timeout)
        process.finished.connect(lambda code, status: callback(generation, process, code))
        process.errorOccurred.connect(lambda error: self._process_error(generation, process, error))
        return process

    def _process_error(self, generation, process, error):
        if error == QProcess.ProcessError.FailedToStart and generation == self.generation and self.process is process:
            self.process = None; process.deleteLater(); self._release()

    def _probed(self, generation, process, code):
        if generation != self.generation or self.process is not process: return
        self.process = None
        output = bytes(process.readAllStandardOutput())
        process.deleteLater()
        if code != 0: return
        try:
            info = json.loads(output)
            codec = info['streams'][0]['codec_name']
            self.source_duration = float(info['format']['duration'])
            if not math.isfinite(self.source_duration) or self.source_duration <= 0: return
        except (KeyError, IndexError, TypeError, ValueError):
            return
        if codec == 'h264': self._play(generation, self.path, False)
        else: self._make_proxy(generation)

    def _make_proxy(self, generation):
        if generation != self.generation or not self.path or self.source_duration <= 0: return
        self.proxy_attempted = True
        try:
            self.tempdir = tempfile.TemporaryDirectory(prefix='clipper-hover-')
            output = Path(self.tempdir.name) / 'preview.mp4'
        except OSError:
            self._release(); return
        start, end = self.saved_range
        offset = self.source_duration * start
        length = min(4., self.source_duration * (end - start))
        process = self._new_process(generation, lambda gen, proc, code: self._proxy_ready(gen, proc, code, output), 20000)
        process.start(executable('ffmpeg'), ['-nostdin', '-v', 'error', '-y', '-threads', '2',
            '-ss', str(offset), '-i', self.path, '-t', str(length), '-map', '0:v:0', '-an',
            '-vf', "fps=12,scale='min(640,iw)':-2", '-c:v', 'libx264', '-threads', '2',
            '-preset', 'ultrafast', '-crf', '30', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(output)])

    def _proxy_ready(self, generation, process, code, output):
        if generation != self.generation or self.process is not process: return
        self.process = None; process.deleteLater()
        try: valid = code == 0 and output.is_file() and output.stat().st_size > 0
        except OSError: valid = False
        if not valid:
            self._release(); return
        self._play(generation, str(output), True)

    def _play(self, generation, path, proxy):
        if generation != self.generation: return
        self.using_proxy = proxy
        self.range_start, self.range_end = (0., 1.) if proxy else self.saved_range
        self.start_ms = self.end_ms = 0
        self.initial_seek = False
        self.last_frame_time = 0.
        player = QMediaPlayer(self)
        sink = QVideoSink(self)
        self.player, self.sink = player, sink
        player.setVideoSink(sink)
        sink.videoFrameChanged.connect(lambda frame: self._frame(generation, frame))
        player.durationChanged.connect(lambda duration: self._duration(generation, duration))
        player.positionChanged.connect(lambda position: self._position(generation, position))
        player.mediaStatusChanged.connect(lambda status: self._status(generation, status))
        player.errorOccurred.connect(lambda *_: QTimer.singleShot(0, lambda: self._player_failed(generation, player)))
        player.setSource(QUrl.fromLocalFile(str(Path(path).resolve())))
        self.watchdog.start()
        player.play()

    def _duration(self, generation, duration):
        if generation != self.generation or self.player is None or duration <= 0: return
        self.start_ms = int(duration * self.range_start)
        self.end_ms = max(self.start_ms + 1, int(duration * self.range_end))
        if not self.initial_seek:
            self.initial_seek = True
            if self.start_ms: self.player.setPosition(self.start_ms)

    def _position(self, generation, position):
        if generation != self.generation or self.player is None: return
        if self.end_ms and position >= self.end_ms:
            self.player.setPosition(self.start_ms)

    def _status(self, generation, status):
        if generation != self.generation or self.player is None: return
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.player.setPosition(self.start_ms)
            self.player.play()

    def _frame(self, generation, frame):
        if generation != self.generation or self.player is None or sip.isdeleted(self.view) or not frame.isValid(): return
        if self.range_start and (not self.initial_seek or self.player.position() < max(0, self.start_ms - 150)):
            return
        now = time.monotonic()
        if now - self.last_frame_time < .08: return
        image = frame.toImage()
        if image.isNull(): return
        self.watchdog.stop()
        self.last_frame_time = now
        self.frame = QPixmap.fromImage(image).scaled(self.view.iconSize(), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.FastTransformation)
        self._update_card()
        self.frameReady.emit()

    def _watchdog_expired(self):
        if self.player is not None and self.frame.isNull(): self._failed(self.generation)

    def _player_failed(self, generation, player):
        if self.player is player: self._failed(generation)

    def _failed(self, generation):
        if generation != self.generation: return
        if not self.using_proxy and not self.proxy_attempted and self.source_duration > 0:
            self.watchdog.stop(); self._dispose_player(); self._make_proxy(generation)
        else:
            self._release()

    def _dispose_player(self):
        player, sink = self.player, self.sink
        self.player = self.sink = None
        if player is not None:
            player.stop(); player.setVideoSink(None); player.setSource(QUrl())
            sip.delete(player)
        if sink is not None: sip.delete(sink)

    def _release(self):
        self.generation += 1
        self.watchdog.stop()
        process, self.process = self.process, None
        if process is not None:
            process.kill(); process.waitForFinished(3000); process.deleteLater()
        self._dispose_player()
        if self.tempdir is not None:
            try: self.tempdir.cleanup()
            except OSError: pass
            self.tempdir = None
        self.frame = QPixmap()
        self._update_card()

    def _update_card(self):
        if sip.isdeleted(self.view) or sip.isdeleted(self.viewport) or not self.index.isValid(): return
        rect = self.view.visualRect(QModelIndex(self.index))
        if rect.isValid(): self.viewport.update(rect)

    def stop(self):
        self.delay.stop()
        if self.player is not None or self.process is not None or self.tempdir is not None or not self.frame.isNull(): self._release()
        self.path = None
        self.index = QPersistentModelIndex()
