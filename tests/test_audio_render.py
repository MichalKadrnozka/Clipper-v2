import array
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication
from clipper.audio_render import AudioRender
from clipper.media import probe, run


class AudioRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def test_amplified_preview_uses_selected_track_levels(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / 'source.mkv'; output = root / 'mix.m4a'
            run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=64x64:rate=10',
                 '-f', 'lavfi', '-i', 'sine=frequency=440', '-f', 'lavfi', '-i', 'sine=frequency=880',
                 '-t', '1', '-map', '0:v', '-map', '1:a', '-map', '2:a', '-c:v', 'libx264', '-c:a', 'aac', str(source)])
            streams = [s['index'] for s in probe(source)['streams'] if s['codec_type'] == 'audio']
            job = AudioRender(source, output, [(streams[0], 2), (streams[1], 0)])
            loop = QEventLoop(); errors = []; ready = []
            job.ready.connect(lambda path: (ready.append(path), loop.quit()))
            job.failed.connect(lambda error: (errors.append(error), loop.quit()))
            QTimer.singleShot(10000, loop.quit); job.start(); loop.exec()
            self.assertFalse(errors, errors); self.assertEqual(ready, [str(output)])
            def rms(path, mapping):
                raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-map', mapping,
                    '-f', 's16le', '-ac', '1', '-ar', '44100', '-'], capture_output=True, check=True).stdout
                samples = array.array('h'); samples.frombytes(raw)
                return (sum(value * value for value in samples) / len(samples)) ** .5
            self.assertAlmostEqual(rms(output, '0:a:0') / rms(source, '0:a:0'), 2, delta=.12)

    def test_preview_switches_to_render_and_back_without_audio_device(self):
        from unittest.mock import patch
        from PyQt6.QtCore import QObject, pyqtSignal
        from PyQt6.QtMultimedia import QMediaPlayer
        from clipper.audio_preview import AudioPreview
        class Player(QObject):
            PlaybackState = QMediaPlayer.PlaybackState
            tracksChanged = pyqtSignal(); errorOccurred = pyqtSignal(object, str)
            playbackStateChanged = pyqtSignal(object); positionChanged = pyqtSignal(int); playbackRateChanged = pyqtSignal(float)
            def __init__(self, parent=None): super().__init__(parent)
            def setAudioOutput(self, output): pass
            def setSource(self, source): pass
            def playbackRate(self): return 1.
            def playbackState(self): return self.PlaybackState.StoppedState
            def position(self): return 0
            def setPlaybackRate(self, rate): pass
            def setPosition(self, position): pass
            def stop(self): pass
            def play(self): pass
            def pause(self): pass
        class Output(QObject):
            def __init__(self, parent=None): super().__init__(parent); self.muted = False
            def setMuted(self, value): self.muted = value
            def setVolume(self, value): pass
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.mkv'
            run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=64x64:rate=10',
                 '-f', 'lavfi', '-i', 'sine=frequency=440', '-t', '1', '-c:v', 'libx264', '-c:a', 'aac', str(path)])
            index = next(s['index'] for s in probe(path)['streams'] if s['codec_type'] == 'audio')
            with patch('clipper.audio_preview.QMediaPlayer', Player), patch('clipper.audio_preview.QAudioOutput', Output):
                video = Player(); preview = AudioPreview(path, video, [index]); errors = []; loop = QEventLoop()
                preview.status.connect(lambda status: loop.quit() if not status and preview.render_ready else None)
                preview.failed.connect(lambda error: (errors.append(error), loop.quit()))
                preview.ready.add(index)
                preview.set_gain(index, 2)
                self.assertFalse(preview.outputs[index].muted, 'Existing audio should continue while rendering')
                QTimer.singleShot(10000, loop.quit); loop.exec()
                self.assertFalse(errors, errors); self.assertTrue(preview.render_ready)
                self.assertTrue(preview.outputs[index].muted)
                preview.set_gain(index, .5)
                self.assertFalse(preview.render_mode); self.assertFalse(preview.render_ready)
                preview.close()
                preview.set_gain(index, 2); preview.set_master(.5); preview.set_muted(True)
                preview.set_first_is_mix(True); preview.close()

    def test_master_amplification_is_included_in_render_levels(self):
        from unittest.mock import patch
        from PyQt6.QtCore import QObject, pyqtSignal
        from PyQt6.QtMultimedia import QMediaPlayer
        from clipper.audio_preview import AudioPreview
        class Player(QObject):
            PlaybackState = QMediaPlayer.PlaybackState
            tracksChanged = pyqtSignal(); errorOccurred = pyqtSignal(object, str)
            playbackStateChanged = pyqtSignal(object); positionChanged = pyqtSignal(int); playbackRateChanged = pyqtSignal(float)
            def __init__(self, parent=None): super().__init__(parent)
            def setAudioOutput(self, output): pass
            def setSource(self, source): pass
            def playbackRate(self): return 1.
            def playbackState(self): return self.PlaybackState.StoppedState
            def position(self): return 0
            def setPlaybackRate(self, rate): pass
            def setPosition(self, position): pass
            def stop(self): pass
            def play(self): pass
            def pause(self): pass
        class Output(QObject):
            def __init__(self, parent=None): super().__init__(parent); self.muted = False; self.volume = None
            def setMuted(self, value): self.muted = value
            def setVolume(self, value): self.volume = value
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.mkv'; source.touch()
            with patch('clipper.audio_preview.QMediaPlayer', Player), patch('clipper.audio_preview.QAudioOutput', Output):
                video = Player(); preview = AudioPreview(source, video, [1]); preview.ready.add(1)
                preview.set_master(1.5)
                self.assertEqual(preview.master, 1.5)
                self.assertTrue(preview.render_mode)
                self.assertEqual(preview.render_signature, ((1, 1.5),))
                self.assertEqual(preview.outputs[1].volume, 1)
                self.assertFalse(preview.outputs[1].muted, 'Limited direct preview remains available while rendering')
                preview._activate_render()
                self.assertTrue(preview.outputs[1].muted)
                self.assertFalse(preview.render_output.muted)
                self.assertEqual(preview.render_output.volume, 1)
                preview.set_master(.5)
                self.assertFalse(preview.render_mode)
                self.assertEqual(preview.outputs[1].volume, .5)
                preview.close()

    def test_hung_render_times_out(self):
        from PyQt6.QtCore import QEventLoop, QTimer
        import sys
        with tempfile.TemporaryDirectory() as d:
            render = AudioRender(Path(d)/'empty', Path(d)/'out.m4a', [(1, 1.5)])
            render.watchdog.setInterval(30); errors = []; loop = QEventLoop()
            render.failed.connect(lambda error: (errors.append(error), loop.quit())); QTimer.singleShot(3000, loop.quit)
            render.process.start(sys.executable, ['-c', 'import time; time.sleep(2)']); render.watchdog.start(); loop.exec(); render.cancel()
            self.assertEqual(errors, ['Příprava zvukového náhledu překročila časový limit.'])

    def test_cancelled_render_does_not_start(self):
        with tempfile.TemporaryDirectory() as directory:
            job = AudioRender(Path(directory) / 'missing', Path(directory) / 'out.m4a', [(1, 2)])
            job.cancel(); job.start()
            self.assertFalse(job.destination.exists())
