import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import importlib.util
import tempfile
import unittest
from pathlib import Path
from PyQt6.QtWidgets import QApplication, QDialog
from clipper.media import run

@unittest.skipUnless(importlib.util.find_spec('PyQt6.QtMultimedia'), 'Qt Multimedia bindings not installed')
class EditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])
    def test_editor_marks_and_closes(self):
        from clipper.editor import Editor
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'sample.mp4'
            run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=10', '-t', '2', '-c:v', 'libx264', str(path)])
            editor = Editor(path)
            self.assertIsNone(editor.audio_preview)
            self.assertFalse(editor.mute.isEnabled())
            self.assertFalse(editor.listen_volume.isEnabled())
            editor.start.setValue(.25); editor.end.setValue(1.5)
            editor.accept_operation('trim')
            self.assertEqual(editor.result(), QDialog.DialogCode.Accepted)
            self.assertAlmostEqual(editor.result_values()[0], .25)

    def test_playback_delivers_video_frames(self):
        from PyQt6.QtCore import QEventLoop, QTimer
        from clipper.editor import Editor
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'sample.mp4'
            run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=10', '-t', '2', '-c:v', 'libx264', str(path)])
            editor = Editor(path); frames = []; loop = QEventLoop()
            def received(frame):
                if frame.isValid(): frames.append(frame); loop.quit()
            editor.video.videoSink().videoFrameChanged.connect(received)
            timer = QTimer(loop); timer.setSingleShot(True); timer.timeout.connect(loop.quit); timer.start(10000)
            editor.player.play(); loop.exec()
            editor.reject()
            self.assertTrue(frames, 'Video playback did not deliver a frame')
            self.assertIsNotNone(editor.video.image, 'Video frame was not painted into the editor')

    def test_av1_is_playable_through_generated_proxy(self):
        from PyQt6.QtCore import QEventLoop, QTimer
        from clipper.editor import Editor
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'source.mkv'
            try:
                run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=10', '-t', '1', '-c:v', 'libaom-av1', '-cpu-used', '8', str(path)])
            except Exception as exc:
                self.skipTest(f'AV1 encoder unavailable: {exc}')
            editor = Editor(path); loop = QEventLoop(); frames = []; errors = []
            editor.proxy.ready.connect(lambda _: editor.player.play())
            editor.proxy.failed.connect(lambda msg: (errors.append(msg), loop.quit()))
            editor.video.videoSink().videoFrameChanged.connect(lambda frame: (frames.append(True), loop.quit()) if frame.isValid() else None)
            timer = QTimer(loop); timer.setSingleShot(True); timer.timeout.connect(loop.quit); timer.start(30000)
            loop.exec(); editor.reject()
            self.assertFalse(errors, errors)
            self.assertTrue(frames, 'AV1 proxy did not produce a video frame')

    def test_autoplay_waits_for_av1_preview(self):
        from PyQt6.QtCore import QEventLoop, QTimer
        from clipper.editor import Editor
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'source.mkv'
            try:
                run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=10', '-t', '1', '-c:v', 'libaom-av1', '-cpu-used', '8', str(path)])
            except Exception as exc:
                self.skipTest(f'AV1 encoder unavailable: {exc}')
            editor = Editor(path); loop = QEventLoop(); frames = []; errors = []
            editor.video.videoSink().videoFrameChanged.connect(lambda frame: (frames.append(True), loop.quit()) if frame.isValid() else None)
            editor.proxy.failed.connect(lambda message: (errors.append(message), loop.quit()))
            editor.request_autoplay()
            QTimer.singleShot(30000, loop.quit); loop.exec()
            editor.reject()
            self.assertFalse(errors, errors)
            self.assertTrue(frames, 'Autoplay did not start after preparing the preview')

    def test_failed_preview_can_be_rebuilt_and_played(self):
        from PyQt6.QtCore import QEventLoop, QTimer
        from clipper.editor import Editor
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'sample.mp4'
            run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=10', '-t', '1', '-c:v', 'libx264', str(path)])
            editor = Editor(path)
            editor.prepare_preview()
            editor.proxy.cancel()
            editor.preview_failed('test failure')
            self.assertFalse(editor.retry_preview.isHidden())
            editor.retry_preview_generation()
            loop = QEventLoop(); frames = []; errors = []
            editor.proxy.ready.connect(lambda _: editor.player.play())
            editor.proxy.failed.connect(lambda error: (errors.append(error), loop.quit()))
            editor.video.videoSink().videoFrameChanged.connect(lambda frame: (frames.append(True), loop.quit()) if frame.isValid() else None)
            QTimer.singleShot(30000, loop.quit)
            loop.exec()
            self.assertFalse(errors, errors)
            self.assertTrue(frames, 'Rebuilt proxy did not deliver a video frame')
            editor.reject()

    def test_waveform_click_requests_seek_fraction(self):
        from PyQt6.QtCore import Qt, QPoint
        from PyQt6.QtTest import QTest
        from clipper.editor import WaveformView
        wave=WaveformView(); wave.resize(400,48); values=[]; wave.seekRequested.connect(values.append)
        QTest.mouseClick(wave, Qt.MouseButton.LeftButton, pos=QPoint(100,20))
        self.assertAlmostEqual(values[0], .25, places=2)

    def test_independent_audio_tracks_follow_editor(self):
        from PyQt6.QtCore import QEventLoop, QTimer
        from PyQt6.QtMultimedia import QMediaPlayer
        from clipper.editor import Editor
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'tracks.mkv'
            run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=10',
                 '-f', 'lavfi', '-i', 'sine=frequency=440', '-f', 'lavfi', '-i', 'sine=frequency=880',
                 '-t', '4', '-map', '0:v', '-map', '1:a', '-map', '2:a', '-c:v', 'libx264',
                 '-c:a', 'aac', str(path)])
            editor = Editor(path)
            loop = QEventLoop(); QTimer.singleShot(2200, loop.quit)
            editor.player.play(); loop.exec()
            preview = editor.audio_preview
            players = list(preview.players.values())
            self.assertEqual(len(players), 2)
            self.assertEqual([p.activeAudioTrack() for p in players], [0, 1])
            self.assertTrue(all(p.playbackState() == QMediaPlayer.PlaybackState.PlayingState for p in players))
            self.assertTrue(all(abs(p.position() - editor.player.position()) < 400 for p in players))
            indices = list(preview.players)
            editor.volumes[indices[1]].setValue(.3)
            self.assertAlmostEqual(preview.outputs[indices[1]].volume(), .3, places=2)
            editor.first_is_mix.setChecked(True)
            self.assertEqual(preview.outputs[indices[0]].volume(), 0)
            editor.player.pause()
            self.assertTrue(all(p.playbackState() != QMediaPlayer.PlaybackState.PlayingState for p in players))
            editor.reject()

    def test_closing_editor_releases_playing_multitrack_file(self):
        from PyQt6.QtCore import QEventLoop, QTimer
        from clipper.editor import Editor
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / 'tracks.mkv'
            run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=10',
                 '-f', 'lavfi', '-i', 'sine=frequency=440', '-f', 'lavfi', '-i', 'sine=frequency=880',
                 '-t', '5', '-map', '0:v', '-map', '1:a', '-map', '2:a', '-c:v', 'libx264',
                 '-c:a', 'aac', str(source)])
            editor = Editor(source); editor.player.play()
            loop = QEventLoop(); QTimer.singleShot(2200, loop.quit); loop.exec()
            self.assertEqual(len(editor.audio_preview.ready), 2)
            editor.reject()
            renamed = source.with_name('renamed.mkv')
            source.rename(renamed)
            self.assertTrue(renamed.is_file())

    def test_waveform_trim_handles_can_be_dragged(self):
        from PyQt6.QtCore import Qt, QPoint
        from PyQt6.QtTest import QTest
        from clipper.editor import WaveformView
        wave = WaveformView(); wave.resize(400, 48); wave.show()
        starts = []; ends = []; seeks = []
        wave.startRequested.connect(starts.append); wave.endRequested.connect(ends.append)
        wave.seekRequested.connect(seeks.append)
        QTest.mousePress(wave, Qt.MouseButton.LeftButton, pos=QPoint(1, 20))
        QTest.mouseMove(wave, QPoint(100, 20)); QTest.mouseRelease(wave, Qt.MouseButton.LeftButton, pos=QPoint(100, 20))
        QTest.mousePress(wave, Qt.MouseButton.LeftButton, pos=QPoint(399, 20))
        QTest.mouseMove(wave, QPoint(300, 20)); QTest.mouseRelease(wave, Qt.MouseButton.LeftButton, pos=QPoint(300, 20))
        self.assertAlmostEqual(starts[-1], .25, places=2)
        self.assertAlmostEqual(ends[-1], .75, places=2)
        self.assertFalse(seeks)
        wave.close()

    def test_cancelled_proxy_does_not_start_later(self):
        from clipper.proxy import PreviewProxy
        from PyQt6.QtCore import QProcess
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'source.mp4'; path.touch()
            proxy = PreviewProxy(path, Path(d) / 'cache')
            proxy.cancel(); proxy.start()
            self.assertEqual(proxy.process.state(), QProcess.ProcessState.NotRunning)

    def test_clicking_seek_bar_jumps_to_clicked_position(self):
        from PyQt6.QtCore import Qt, QPoint
        from PyQt6.QtTest import QTest
        from clipper.editor import SeekSlider
        slider = SeekSlider(Qt.Orientation.Horizontal); slider.setRange(0, 1000); slider.resize(400, 30); slider.show()
        positions = []; slider.sliderMoved.connect(positions.append)
        QTest.mouseClick(slider, Qt.MouseButton.LeftButton, pos=QPoint(200, 15))
        self.assertTrue(positions)
        self.assertAlmostEqual(positions[-1], 500, delta=15)
        slider.close()

    def test_preview_timeout_finishes_instead_of_waiting_forever(self):
        from PyQt6.QtCore import QEventLoop, QTimer
        from clipper.proxy import PreviewProxy
        import sys
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'empty.mp4'; path.touch(); proxy = PreviewProxy(path, Path(d)/'cache')
            proxy.watchdog.setInterval(30); errors = []; loop = QEventLoop()
            proxy.failed.connect(lambda error: (errors.append(error), loop.quit()))
            QTimer.singleShot(3000, loop.quit)
            proxy.process.start(sys.executable, ['-c', 'import time; time.sleep(2)']); proxy.watchdog.start(); loop.exec(); proxy.cancel()
            self.assertEqual(errors, ['Příprava náhledu překročila časový limit.'])

    def test_proxy_handles_odd_source_dimensions(self):
        from PyQt6.QtCore import QEventLoop, QTimer
        from clipper.proxy import PreviewProxy
        from clipper.media import probe
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'odd.mkv'
            run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=161x91:rate=10', '-t', '1', '-c:v', 'ffv1', str(path)])
            proxy = PreviewProxy(path, Path(d)/'cache', duration=1); ready = []; errors = []; loop = QEventLoop()
            proxy.ready.connect(lambda result: (ready.append(result), loop.quit())); proxy.failed.connect(lambda error: (errors.append(error), loop.quit()))
            QTimer.singleShot(10000, loop.quit); proxy.start(); loop.exec()
            self.assertFalse(errors, errors); self.assertTrue(ready)
            video = next(stream for stream in probe(ready[0])['streams'] if stream['codec_type'] == 'video')
            self.assertEqual((video['width'], video['height']), (160, 90))

    def test_preview_generation_reports_progress(self):
        from PyQt6.QtCore import QEventLoop, QTimer
        from clipper.proxy import PreviewProxy
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); path = root / 'source.mp4'
            run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=10',
                 '-t', '1', '-c:v', 'libx264', str(path)])
            proxy = PreviewProxy(path, root / 'cache', duration=1)
            loop = QEventLoop(); values = []; errors = []; ready = []
            proxy.progress.connect(values.append)
            proxy.ready.connect(lambda result: (ready.append(result), loop.quit()))
            proxy.failed.connect(lambda error: (errors.append(error), loop.quit()))
            QTimer.singleShot(10000, loop.quit); proxy.start(); loop.exec()
            proxy.cancel()
            self.assertFalse(errors)
            self.assertTrue(ready)
            self.assertTrue(values)
            self.assertTrue(all(0 <= value <= 100 for value in values))

    def test_player_error_falls_back_to_proxy(self):
        from PyQt6.QtCore import QEventLoop, QTimer
        from clipper.editor import Editor
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'source.mp4'
            run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=10',
                 '-t', '1', '-c:v', 'libx264', str(path)])
            editor = Editor(path); editor.player_error()
            self.assertIsNotNone(editor.proxy)
            loop = QEventLoop(); ready = []; errors = []
            editor.proxy.ready.connect(lambda value: (ready.append(value), loop.quit()))
            editor.proxy.failed.connect(lambda value: (errors.append(value), loop.quit()))
            QTimer.singleShot(10000, loop.quit); loop.exec()
            self.assertFalse(errors)
            self.assertTrue(ready)
            self.assertTrue(editor.play_button.isEnabled())
            editor.reject()

    def test_export_preview_hides_trim_controls_but_keeps_seeking(self):
        from PyQt6.QtCore import Qt, QPoint
        from PyQt6.QtTest import QTest
        from clipper.editor import Editor
        info = {'streams': [{'codec_type': 'video', 'index': 0, 'duration': '4',
                             'codec_name': 'h264', 'avg_frame_rate': '30/1'}],
                'format': {'duration': '4'}}
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'preview.mp4'; path.touch()
            editor = Editor(path, info=info, preview_mode=True)
            self.assertIs(editor.save_trim_button, editor.save_trim)
            self.assertTrue(editor.preview_mode)
            self.assertTrue(editor.range_box.isHidden())
            self.assertFalse(editor.range_box.isEnabled())
            self.assertTrue(editor.range_summary.isHidden())
            self.assertTrue(editor.save_trim.isHidden())
            self.assertFalse(editor.save_trim.isEnabled())
            self.assertTrue(editor.export_button.isHidden())
            self.assertFalse(editor.export_button.isEnabled())
            self.assertFalse(editor.start.isEnabled())
            self.assertFalse(editor.end.isEnabled())
            self.assertTrue(editor.seek.isEnabled())
            self.assertTrue(editor.play_button.isEnabled())
            self.assertFalse(editor.video_timeline.trim_enabled)
            seeks = []; starts = []
            editor.video_timeline.seekRequested.connect(seeks.append)
            editor.video_timeline.startRequested.connect(starts.append)
            editor.video_timeline.resize(400, 76)
            QTest.mouseClick(editor.video_timeline, Qt.MouseButton.LeftButton, pos=QPoint(1, 40))
            self.assertTrue(seeks)
            self.assertFalse(starts)
            self.assertIsNone(editor.video_timeline.dragging)
            editor.accept_operation('export')
            self.assertIsNone(editor.operation)
            editor.reject()

    def test_disabled_waveform_trim_handles_still_seek(self):
        from PyQt6.QtCore import Qt, QPoint
        from PyQt6.QtTest import QTest
        from clipper.editor import WaveformView
        wave = WaveformView(); wave.resize(400, 48); wave.set_trim_enabled(False)
        seeks = []; starts = []; ends = []
        wave.seekRequested.connect(seeks.append); wave.startRequested.connect(starts.append); wave.endRequested.connect(ends.append)
        QTest.mouseClick(wave, Qt.MouseButton.LeftButton, pos=QPoint(1, 20))
        self.assertTrue(seeks)
        self.assertFalse(starts)
        self.assertFalse(ends)
        self.assertIsNone(wave.dragging)
        wave.close()

    def test_autoplay_seeks_to_saved_in_even_when_preview_becomes_ready_later(self):
        from unittest.mock import patch
        from PyQt6.QtWidgets import QWidget
        from clipper.library import Library
        from clipper.editor import Editor
        info = {'streams': [{'codec_type': 'video', 'index': 0, 'duration': '4',
                             'codec_name': 'h264', 'avg_frame_rate': '30/1'}],
                'format': {'duration': '4'}}
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); path = root / 'source.mp4'; path.touch()
            parent = QWidget(); parent.library = Library(root / 'db.sqlite'); parent.data_path = root
            parent.library.save_edit(path, {'in': .25, 'out': .75})
            editor = Editor(path, parent, info=info)
            editor.play_button.setEnabled(False)
            with patch.object(editor.player, 'setPosition') as seek, patch.object(editor.player, 'play') as play:
                editor.request_autoplay()
                play.assert_not_called()
                editor.preview_ready(str(path))
                seek.assert_called_once_with(1000)
                play.assert_called_once_with()
            editor.reject(); parent.library.close()

    def test_clicking_video_toggles_playback(self):
        from unittest.mock import patch
        from PyQt6.QtCore import Qt, QPoint
        from PyQt6.QtTest import QTest
        from clipper.editor import Editor
        info = {'streams': [{'codec_type': 'video', 'index': 0, 'duration': '4',
                             'codec_name': 'h264', 'avg_frame_rate': '30/1'}],
                'format': {'duration': '4'}}
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'source.mp4'; path.touch()
            editor = Editor(path, info=info)
            editor.video.resize(320, 180); editor.show(); self.app.processEvents()
            editor.play_button.setEnabled(True)
            with patch.object(editor.player, 'play') as play:
                QTest.mouseClick(editor.video, Qt.MouseButton.LeftButton, pos=QPoint(100, 80))
                play.assert_called_once_with()
            editor.reject()

    def test_i_o_shortcuts_set_trim_points(self):
        from unittest.mock import patch
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        from clipper.editor import Editor
        info = {'streams': [{'codec_type': 'video', 'index': 0, 'duration': '4',
                             'codec_name': 'h264', 'avg_frame_rate': '30/1'}],
                'format': {'duration': '4'}}
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'source.mp4'; path.touch()
            editor = Editor(path, info=info)
            with patch.object(editor.player, 'position', return_value=1250):
                QTest.keyClick(editor, Qt.Key.Key_I)
            with patch.object(editor.player, 'position', return_value=2250):
                QTest.keyClick(editor, Qt.Key.Key_O)
            self.assertAlmostEqual(editor.start.value(), 1.25)
            self.assertAlmostEqual(editor.end.value(), 2.25)
            editor.reject()

    def test_master_volume_is_clamped_and_saved_as_percent(self):
        from PyQt6.QtWidgets import QWidget
        from clipper.library import Library
        from clipper.editor import Editor
        info = {'streams': [{'codec_type': 'video', 'index': 0, 'duration': '4',
                             'codec_name': 'h264', 'avg_frame_rate': '30/1'}],
                'format': {'duration': '4'}}
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); path = root / 'source.mp4'; path.touch()
            parent = QWidget(); parent.library = Library(root / 'db.sqlite'); parent.data_path = root
            parent.library.set_setting('master_volume', '175')
            editor = Editor(path, parent, info=info)
            self.assertEqual(editor.listen_volume.maximum(), 150)
            self.assertEqual(editor.listen_volume.value(), 150)
            editor.listen_volume.setValue(125)
            editor.reject()
            self.assertEqual(parent.library.setting('master_volume'), '125')
            parent.library.close()

    def test_editor_displays_and_preserves_saved_track_names(self):
        from PyQt6.QtWidgets import QLabel, QWidget
        from clipper.library import Library
        from clipper.editor import Editor
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); path = root / 'source.mkv'
            run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=80x60:rate=10',
                 '-f', 'lavfi', '-i', 'sine=frequency=440', '-f', 'lavfi', '-i', 'sine=frequency=880',
                 '-t', '1', '-map', '0:v', '-map', '1:a', '-map', '2:a', '-c:v', 'libx264', '-c:a', 'aac', str(path)])
            parent = QWidget(); parent.library = Library(root / 'db.sqlite'); parent.data_path = root
            parent.library.save_edit(path, {'track_names': ['Mix', 'Discord'], 'mix_first': True})
            editor = Editor(path, parent)
            self.assertIn('Discord', [label.text() for label in editor.findChildren(QLabel)])
            editor.reject()
            self.assertEqual(parent.library.edit_for(path)['track_names'], ['Mix', 'Discord'])
            parent.library.close()
