import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from pathlib import Path
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication
from clipper.media import run
from clipper.thumbnails import Thumbnails

class ThumbnailTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])
    def test_generated_thumbnail_is_cached(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); video = root / 'sample.mp4'
            run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=10', '-t', '2', '-c:v', 'libx264', str(video)])
            thumbs = Thumbnails(root / 'cache'); loop = QEventLoop(); results = []
            thumbs.ready.connect(lambda path, output: (results.append((path, output)), loop.quit()))
            self.assertIsNone(thumbs.request(video)); timer = QTimer(loop); timer.setSingleShot(True); timer.timeout.connect(loop.quit); timer.start(15000); loop.exec()
            thumbs.shutdown()
            self.assertEqual(len(results), 1)
            self.assertTrue(Path(results[0][1]).is_file())
            self.assertEqual(thumbs.request(video), Path(results[0][1]))

    def test_invalid_file_is_not_retried_until_it_changes(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); video = root / 'sample.mp4'; video.write_bytes(b'invalid')
            thumbs = Thumbnails(root / 'cache'); loop = QEventLoop(); failures = []
            thumbs.failed.connect(lambda path: (failures.append(path), loop.quit()))
            timer = QTimer(loop); timer.setSingleShot(True); timer.timeout.connect(loop.quit); timer.start(15000)
            thumbs.request(video); loop.exec(); timer.stop()
            self.assertEqual(failures, [str(video)]); self.assertTrue(thumbs.unavailable(video))
            for _ in range(5): self.assertIsNone(thumbs.request(video))
            self.assertFalse(thumbs.pending)
            run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=10', '-t', '2', '-c:v', 'libx264', str(video)])
            loop = QEventLoop(); results = []
            thumbs.ready.connect(lambda path, output: (results.append(output), loop.quit()))
            timer = QTimer(loop); timer.setSingleShot(True); timer.timeout.connect(loop.quit); timer.start(15000)
            thumbs.request(video); loop.exec(); timer.stop()
            self.assertEqual(len(results), 1); self.assertTrue(Path(results[0]).exists())
            self.assertFalse(thumbs.unavailable(video)); thumbs.shutdown()

    def test_file_replaced_during_generation_is_retried_with_new_contents(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); video = root / 'sample.mp4'; video.write_bytes(b'invalid')
            replacement = root / 'replacement.mp4'
            run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=10', '-t', '2', '-c:v', 'libx264', str(replacement)])
            thumbs = Thumbnails(root / 'cache'); loop = QEventLoop(); results = []
            thumbs.ready.connect(lambda path, output: (results.append(output), loop.quit()))
            timer = QTimer(loop); timer.setSingleShot(True); timer.timeout.connect(loop.quit); timer.start(15000)
            thumbs.request(video); os.replace(replacement, video); loop.exec(); timer.stop()
            self.assertEqual(len(results), 1)
            self.assertEqual(thumbs.request(video), Path(results[0])); thumbs.shutdown()
