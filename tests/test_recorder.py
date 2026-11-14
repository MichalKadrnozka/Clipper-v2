import sys
import tempfile
import unittest
from pathlib import Path
from clipper.recorder import CaptureSettings, GSRRecorder, RecorderError

class ReplayNamingTests(unittest.TestCase):
    def test_title_lookup_failure_does_not_lose_saved_replay(self):
        from unittest.mock import patch
        from clipper.recorder import name_replay_for_active_window
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / 'Replay_1.mp4'; source.write_bytes(b'video')
            with patch('clipper.recorder.active_window_name', side_effect=RuntimeError('window system unavailable')):
                result = Path(name_replay_for_active_window(source, d))
            self.assertEqual(result.name, 'Desktop_1.mp4')
            self.assertEqual(result.read_bytes(), b'video')

    def test_title_and_collision_preserve_both_recordings(self):
        from clipper.recorder import name_saved_replay
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / 'Replay_2026.mkv'; source.write_bytes(b'new')
            occupied = Path(d) / 'My-Game_2026.mkv'; occupied.write_bytes(b'old')
            result = Path(name_saved_replay(source, d, 'My Game - Server'))
            self.assertEqual(result.name, 'My-Game_2026_2.mkv')
            self.assertEqual(result.read_bytes(), b'new'); self.assertEqual(occupied.read_bytes(), b'old')
            self.assertFalse(source.exists())

    def test_unsafe_title_and_foreign_path(self):
        from clipper.recorder import name_saved_replay
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as other:
            source = Path(d) / 'Replay_1.mp4'; source.write_bytes(b'video')
            self.assertEqual(name_saved_replay(source, other, 'Game'), str(source))
            self.assertEqual(Path(name_saved_replay(source, d, '../<>')).name, 'Desktop_1.mp4')

    def test_failed_rename_keeps_original(self):
        from unittest.mock import patch
        from clipper.recorder import name_saved_replay
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / 'Replay_1.mp4'; source.write_bytes(b'video')
            with patch('clipper.recorder._rename_noreplace', side_effect=OSError('unsupported')):
                self.assertEqual(name_saved_replay(source, d, 'Game'), str(source))
            self.assertEqual(source.read_bytes(), b'video')

    @unittest.skipUnless(sys.platform.startswith('linux'), 'Linux renameat2')
    def test_rename_does_not_require_hardlinks(self):
        from unittest.mock import patch
        from clipper.recorder import name_saved_replay
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / 'Replay_1.mp4'; source.write_bytes(b'video')
            with patch('clipper.recorder.os.link', side_effect=OSError('hardlinks unsupported')):
                result = Path(name_saved_replay(source, d, 'Game'))
            self.assertEqual(result.name, 'Game_1.mp4')
            self.assertEqual(result.read_bytes(), b'video')

    @unittest.skipUnless(sys.platform.startswith('linux'), 'Linux fallback')
    def test_fallback_without_renameat2_still_preserves_collision(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from clipper.recorder import name_saved_replay
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / 'Replay_1.mp4'; source.write_bytes(b'new')
            existing = Path(d) / 'Game_1.mp4'; existing.write_bytes(b'old')
            with patch('ctypes.CDLL', return_value=SimpleNamespace()):
                result = Path(name_saved_replay(source, d, 'Game'))
            self.assertEqual(result.name, 'Game_1_2.mp4')
            self.assertEqual(result.read_bytes(), b'new')
            self.assertEqual(existing.read_bytes(), b'old')

    def test_title_detection_falls_back_after_unsupported_compositor(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from clipper.recorder import active_window_name
        with patch('clipper.recorder.sys.platform', 'linux'), patch.dict('os.environ', {'WAYLAND_DISPLAY': 'wayland-0'}), patch('clipper.recorder.subprocess.run', side_effect=[FileNotFoundError(), SimpleNamespace(stdout='My Game\n')]):
            self.assertEqual(active_window_name(), 'My Game')

class RecorderTests(unittest.TestCase):
    def test_command_and_invalid_values(self):
        with tempfile.TemporaryDirectory() as d:
            s = CaptureSettings(d, 'DP-1', 30, 60, 'h264', 'mkv', 'high', '1920x1080', ['default'])
            cmd = s.command()
            self.assertEqual(cmd[cmd.index('-r')+1], '30')
            self.assertEqual(cmd[cmd.index('-a')+1], 'default')
            s.audio_devices = ['desktop', 'microphone']
            self.assertEqual([s.command()[i+1] for i, v in enumerate(s.command()) if v == '-a'], ['desktop|microphone', 'desktop', 'microphone'])
            s.resolution = 'bad'
            with self.assertRaises(RecorderError): s.command()
    @unittest.skipUnless(sys.platform == 'linux', 'Linux only')
    def test_real_process_failure_contains_diagnostics(self):
        with tempfile.TemporaryDirectory() as d:
            script = Path(d)/'recorder'
            script.write_text('#!/bin/sh\necho broken-driver\nexit 4\n')
            script.chmod(0o755)
            with self.assertRaisesRegex(RecorderError, 'broken-driver'):
                GSRRecorder(str(script)).start(CaptureSettings(d, 'DP-1'))

class SavedReplayTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'linux', 'Linux only')
    def test_saved_event_uses_renamed_path_with_its_track_metadata(self):
        import time
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as d:
            script = Path(d) / 'recorder'; source = Path(d) / 'Replay_1.mkv'
            script.write_text('#!' + sys.executable + '\nimport signal,time\ndef saved(*args):\n open(' + repr(str(source)) + ', "wb").write(b"clip")\n print("Saved replay to " + ' + repr(str(source)) + ', flush=True)\nsignal.signal(signal.SIGUSR1,saved)\nwhile True: time.sleep(.1)\n')
            script.chmod(0o755); recorder = GSRRecorder(str(script))
            try:
                with patch('clipper.recorder.active_window_name', return_value='Game'):
                    recorder.start(CaptureSettings(d, 'display', audio_devices=['desktop', 'mic']))
                    recorder.save(); deadline = time.monotonic() + 3
                    while recorder.saved.empty() and time.monotonic() < deadline: time.sleep(.02)
                    event = recorder.saved.get_nowait()
                self.assertEqual(Path(event.path).name, 'Game_1.mkv')
                self.assertEqual(Path(event.path).read_bytes(), b'clip')
                self.assertEqual(event.track_names, ('Mix', 'desktop', 'mic'))
            finally: recorder.stop()

    @unittest.skipUnless(sys.platform == 'linux', 'Linux only')
    def test_pending_events_keep_their_own_recording_track_configuration(self):
        import queue, time
        with tempfile.TemporaryDirectory() as d:
            script = Path(d) / 'recorder'
            script.write_text('#!' + sys.executable + '\nimport signal,time\ndef saved(*args): print("Saved replay to /tmp/fake-clip.mkv", flush=True)\nsignal.signal(signal.SIGUSR1,saved)\nwhile True: time.sleep(.1)\n')
            script.chmod(0o755)
            recorder = GSRRecorder(str(script))
            def capture(sources):
                recorder.start(CaptureSettings(d, 'display', audio_devices=sources))
                recorder.save()
                deadline = time.monotonic() + 3
                while recorder.saved.empty() and time.monotonic() < deadline: time.sleep(.02)
                event = recorder.saved.get_nowait()
                recorder.stop()
                return event
            try:
                first = capture(['desktop', 'microphone'])
                second = capture(['microphone'])
                self.assertTrue(first.first_is_mix)
                self.assertEqual(first.track_names, ('Mix', 'desktop', 'microphone'))
                self.assertFalse(second.first_is_mix)
                self.assertEqual(second.track_names, ('microphone',))
            finally:
                recorder.stop()

class AudioSourcesTests(unittest.TestCase):
    def test_parses_pulseaudio_sources(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from clipper.recorder import audio_sources
        with patch('clipper.recorder.subprocess.run', return_value=SimpleNamespace(stdout='1\tdevice.monitor\tmodule\n2\tmicrophone\tmodule\n')):
            self.assertEqual(audio_sources(), ['device.monitor', 'microphone'])

class RecorderLifecycleTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'linux', 'Linux only')
    def test_replay_signal_saved_event_and_shutdown(self):
        import time, queue
        with tempfile.TemporaryDirectory() as d:
            script = Path(d)/'recorder'
            script.write_text('#!' + sys.executable + '\nimport signal,time\ndef saved(*args): print("Saved replay to /tmp/fake-clip.mkv", flush=True)\nsignal.signal(signal.SIGUSR1,saved)\nwhile True: time.sleep(.1)\n')
            script.chmod(0o755); recorder = GSRRecorder(str(script))
            try:
                recorder.start(CaptureSettings(d, 'test-display')); self.assertTrue(recorder.running)
                recorder.save(); deadline = time.monotonic()+3; result = None
                while time.monotonic() < deadline:
                    try: result=recorder.saved.get_nowait(); break
                    except queue.Empty: time.sleep(.02)
                self.assertEqual(result.path, '/tmp/fake-clip.mkv')
                self.assertFalse(result.first_is_mix)
                self.assertEqual(result.track_names, ())
            finally: recorder.stop()
            self.assertFalse(recorder.running)
