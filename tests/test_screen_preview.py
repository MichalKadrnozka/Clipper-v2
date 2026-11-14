import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PyQt6.QtCore import QRect
from PyQt6.QtGui import QColor, QImage, QPainter
from clipper.app import ScreenPreviewJob


class ScreenPreviewTests(unittest.TestCase):
    def test_large_preview_is_resized_before_reaching_ui(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'frame.png'
            def capture(command, **kwargs):
                image = QImage(3840, 2160, QImage.Format.Format_RGB32)
                image.fill(QColor('blue')); image.save(str(output))
                return SimpleNamespace(returncode=0, stderr=b'')
            job = ScreenPreviewJob(output, 'screen')
            frames, errors = [], []
            job.frame.connect(frames.append); job.failed.connect(errors.append)
            with patch('clipper.app.subprocess.run', side_effect=capture): job.run()
            image = QImage.fromData(frames[0])
            self.assertEqual((image.width(), image.height()), (1280, 720))
            self.assertFalse(errors); self.assertFalse(output.exists())

    def test_spectacle_fallback_crops_selected_monitor_and_cleans_file(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'frame.png'
            def capture(command, **kwargs):
                if command[0] == 'grim':
                    return SimpleNamespace(returncode=1, stderr=b'unsupported compositor')
                image = QImage(200, 100, QImage.Format.Format_RGB32)
                image.fill(QColor('red'))
                painter = QPainter(image); painter.fillRect(100, 0, 100, 100, QColor('blue')); painter.end()
                image.save(str(output))
                return SimpleNamespace(returncode=0, stderr=b'')
            job = ScreenPreviewJob(output, 'screen', screen_geometry=QRect(100, 0, 100, 100), desktop_geometry=QRect(0, 0, 200, 100))
            frames, backends, errors = [], [], []
            job.frame.connect(frames.append); job.backendUsed.connect(backends.append); job.failed.connect(errors.append)
            with patch('clipper.app.subprocess.run', side_effect=capture): job.run()
            image = QImage.fromData(frames[0])
            self.assertEqual((image.width(), image.height()), (100, 100))
            self.assertEqual(image.pixelColor(50, 50), QColor('blue'))
            self.assertEqual(backends, ['spectacle']); self.assertFalse(errors); self.assertFalse(output.exists())

    def test_different_monitor_scales_do_not_show_wrong_monitor(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'frame.png'
            def capture(command, **kwargs):
                if command[0] == 'grim': return SimpleNamespace(returncode=1, stderr=b'unsupported')
                image = QImage(200, 100, QImage.Format.Format_RGB32); image.fill(QColor('red')); image.save(str(output))
                return SimpleNamespace(returncode=0, stderr=b'')
            job = ScreenPreviewJob(output, 'screen', screen_geometry=QRect(100, 0, 100, 100), desktop_geometry=QRect(0, 0, 200, 100), uniform_scale=False)
            frames, errors = [], []
            job.frame.connect(frames.append); job.failed.connect(errors.append)
            with patch('clipper.app.subprocess.run', side_effect=capture): job.run()
            self.assertFalse(frames); self.assertTrue(errors); self.assertFalse(output.exists())
