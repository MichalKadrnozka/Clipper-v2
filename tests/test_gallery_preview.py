import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QEventLoop, QPointF, QProcess, QSize, QTimer, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication, QListView, QListWidget, QListWidgetItem

from clipper.gallery_preview import GalleryPreview
from clipper.media import run


class GalleryPreviewTests(unittest.TestCase):
    def test_queued_event_after_cleanup_is_ignored(self):
        view = QListWidget(); preview = GalleryPreview(view, type('Library', (), {'edit_for': lambda *_: {}})(), view)
        preview.viewport = None; preview.view = None
        self.assertFalse(preview.eventFilter(view, QEvent(QEvent.Type.Leave)))
        view.close()

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_hover_plays_trimmed_video_and_releases_the_file(self):
        class Library:
            def edit_for(self, path): return {'in': .25, 'out': .75}

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'preview.mp4'
            run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=15',
                 '-t', '3', '-c:v', 'libx264', str(source)])
            other = Path(directory) / 'second.mp4'; shutil.copy2(source, other)
            view = QListWidget(); view.setViewMode(QListView.ViewMode.IconMode)
            view.setGridSize(QSize(220, 160)); view.setIconSize(QSize(200, 112)); view.resize(500, 250)
            item = QListWidgetItem('preview'); item.setData(Qt.ItemDataRole.UserRole, str(source)); view.addItem(item)
            second = QListWidgetItem('second'); second.setData(Qt.ItemDataRole.UserRole, str(other)); view.addItem(second)
            preview = GalleryPreview(view, Library(), view)
            view.show(); self.app.processEvents()
            position = QPointF(view.visualItemRect(item).center())
            event = QMouseEvent(QEvent.Type.MouseMove, position, Qt.MouseButton.NoButton,
                                Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
            loop = QEventLoop(); preview.frameReady.connect(loop.quit)
            timer = QTimer(loop); timer.setSingleShot(True); timer.timeout.connect(loop.quit); timer.start(10000)
            QApplication.sendEvent(view.viewport(), event); loop.exec()
            timer.stop()
            self.assertFalse(preview.frame.isNull(), 'Hover did not deliver a video frame')
            self.assertIsNotNone(preview.player)
            self.assertGreaterEqual(preview.player.position(), preview.start_ms - 150)
            self.assertGreater(preview.start_ms, 0)
            self.assertLess(preview.end_ms, preview.player.duration())
            positions = []
            wrap_loop = QEventLoop()
            def observe(position):
                if positions and position < positions[-1] - 400:
                    positions.append(position); wrap_loop.quit(); return
                positions.append(position)
            preview.player.positionChanged.connect(observe)
            wrap_timer = QTimer(wrap_loop); wrap_timer.setSingleShot(True); wrap_timer.timeout.connect(wrap_loop.quit); wrap_timer.start(6000)
            wrap_loop.exec(); wrap_timer.stop()
            self.assertTrue(any(b < a - 400 for a, b in zip(positions, positions[1:])), 'Trimmed preview did not loop')
            first_player = preview.player
            position = QPointF(view.visualItemRect(second).center())
            event = QMouseEvent(QEvent.Type.MouseMove, position, Qt.MouseButton.NoButton,
                                Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
            QApplication.sendEvent(view.viewport(), event)
            self.assertTrue(sip.isdeleted(first_player))
            renamed = source.with_name('renamed.mp4'); source.rename(renamed)
            loop = QEventLoop(); preview.frameReady.connect(loop.quit)
            timer = QTimer(loop); timer.setSingleShot(True); timer.timeout.connect(loop.quit); timer.start(10000)
            loop.exec(); timer.stop()
            self.assertEqual(preview.path, str(other))
            self.assertFalse(preview.frame.isNull(), 'Switching cards did not start the second preview')
            QApplication.sendEvent(view.viewport(), QEvent(QEvent.Type.Leave))
            self.assertIsNone(preview.player)
            self.assertTrue(preview.frame.isNull())
            self.assertTrue(renamed.exists())
            other.rename(other.with_name('second-renamed.mp4'))
            view.close()

    def test_av1_hover_uses_short_proxy_and_removes_it_on_leave(self):
        class Library:
            def edit_for(self, path): return {'in': .25, 'out': .75}

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'preview.mkv'
            try:
                run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=10',
                     '-t', '2', '-c:v', 'libaom-av1', '-cpu-used', '8', str(source)])
            except Exception as exc:
                self.skipTest(f'AV1 encoder unavailable: {exc}')
            view = QListWidget(); view.setViewMode(QListView.ViewMode.IconMode)
            view.setGridSize(QSize(220, 160)); view.setIconSize(QSize(200, 112)); view.resize(400, 250)
            item = QListWidgetItem('preview'); item.setData(Qt.ItemDataRole.UserRole, str(source)); view.addItem(item)
            preview = GalleryPreview(view, Library(), view)
            view.show(); self.app.processEvents()
            position = QPointF(view.visualItemRect(item).center())
            event = QMouseEvent(QEvent.Type.MouseMove, position, Qt.MouseButton.NoButton,
                                Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
            loop = QEventLoop(); preview.frameReady.connect(loop.quit)
            timer = QTimer(loop); timer.setSingleShot(True); timer.timeout.connect(loop.quit); timer.start(15000)
            QApplication.sendEvent(view.viewport(), event); loop.exec(); timer.stop()
            self.assertFalse(preview.frame.isNull(), 'AV1 proxy did not deliver a video frame')
            self.assertTrue(preview.using_proxy)
            self.assertLessEqual(preview.player.duration(), 1300)
            temporary = Path(preview.tempdir.name)
            QApplication.sendEvent(view.viewport(), QEvent(QEvent.Type.Leave))
            self.assertFalse(temporary.exists())
            source.rename(source.with_name('renamed.mkv'))
            view.close()

    def test_leaving_during_proxy_generation_stops_process_and_releases_file(self):
        class Library:
            def edit_for(self, path): return {}

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.mp4'; source.write_bytes(b'video')
            view = QListWidget(); preview = GalleryPreview(view, Library(), view)
            preview.path = str(source)
            preview.tempdir = tempfile.TemporaryDirectory(prefix='clipper-hover-test-')
            temporary = Path(preview.tempdir.name)
            process = QProcess(preview); preview.process = process
            script = 'import sys,time; f=open(sys.argv[1],"rb"); print("ready",flush=True); time.sleep(30)'
            process.start(sys.executable, ['-u', '-c', script, str(source)])
            self.assertTrue(process.waitForStarted(5000))
            self.assertTrue(process.waitForReadyRead(5000))
            preview.stop()
            self.assertIsNone(preview.process)
            self.assertEqual(process.state(), QProcess.ProcessState.NotRunning)
            self.assertFalse(temporary.exists())
            source.rename(source.with_name('renamed.mp4'))
            view.close()
