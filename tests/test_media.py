import tempfile
import subprocess
import array
import unittest
from pathlib import Path
from clipper.media import MediaError, duration, export, probe, run, trim

class MediaTests(unittest.TestCase):
    def test_real_media_operations_and_original_safety(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source = root / 'source.mp4'
            run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=15', '-f', 'lavfi', '-i', 'sine=frequency=440', '-t', '3', '-c:v', 'libx264', '-g', '15', '-c:a', 'aac', str(source)])
            before = source.read_bytes()
            trimmed = root / 'trim.mp4'
            trim(source, trimmed, 1, 2.5)
            self.assertGreater(duration(probe(trimmed)), 0)
            exported = root / 'export.mp4'
            export(source, exported, 0, 3, 0.3)
            self.assertLessEqual(exported.stat().st_size, 300000)
            self.assertGreater(duration(probe(exported)), 2.5)
            with self.assertRaises(MediaError):
                trim(source, source, 0, 1)
            self.assertEqual(before, source.read_bytes())

if __name__ == '__main__': unittest.main()

class MultiTrackTests(unittest.TestCase):
    def test_audio_adjustment_retains_all_tracks_and_original_video_codec(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); source = root / 'source.mp4'; output = root / 'trim.mp4'
            run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=15',
                 '-f', 'lavfi', '-i', 'sine=frequency=440', '-f', 'lavfi', '-i', 'sine=frequency=880',
                 '-t', '2', '-map', '0:v', '-map', '1:a', '-map', '2:a', '-c:v', 'libx264', '-g', '15', '-c:a', 'aac', str(source)])
            info = probe(source); audio = [s for s in info['streams'] if s['codec_type'] == 'audio']
            trim(source, output, 0, 1.5, {audio[0]['index']: 0, audio[1]['index']: .5})
            result = probe(output)
            self.assertEqual(len([s for s in result['streams'] if s['codec_type'] == 'audio']), 2)
            self.assertEqual(next(s['codec_name'] for s in result['streams'] if s['codec_type'] == 'video'), 'h264')
            def peak(track):
                raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(output), '-map', f'0:a:{track}', '-f', 's16le', '-acodec', 'pcm_s16le', '-'], capture_output=True, check=True).stdout
                samples = array.array('h'); samples.frombytes(raw)
                return max(abs(x) for x in samples)
            self.assertLess(peak(0), 10)
            self.assertGreater(peak(1), 100)
    def test_trim_rebuilds_mix_from_edited_stems(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); source=root/'source.mkv'; output=root/'trim.mkv'
            run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=160x90:rate=10',
                 '-f','lavfi','-i','sine=frequency=440','-f','lavfi','-i','sine=frequency=440',
                 '-f','lavfi','-i','sine=frequency=880','-t','2','-map','0:v','-map','1:a','-map','2:a','-map','3:a',
                 '-c:v','libx264','-c:a','aac',str(source)])
            audios=[s for s in probe(source)['streams'] if s['codec_type']=='audio']
            trim(source,output,0,1.5,{audios[1]['index']:0, audios[2]['index']:0},mix_first=True)
            streams=probe(output)['streams']
            self.assertEqual(len([s for s in streams if s['codec_type']=='audio']),3)
            raw=subprocess.run(['ffmpeg','-v','error','-i',str(output),'-map','0:a:0','-f','s16le','-acodec','pcm_s16le','-'],capture_output=True,check=True).stdout
            samples=array.array('h'); samples.frombytes(raw)
            self.assertLess(max(abs(value) for value in samples),10)

    def test_export_rescales_to_meet_small_size_target(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); source = root / 'source.mp4'; output = root / 'small.mp4'
            run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=640x360:rate=30', '-t', '3', '-c:v', 'libx264', str(source)])
            export(source, output, 0, 3, .12)
            video = next(s for s in probe(output)['streams'] if s['codec_type'] == 'video')
            self.assertLessEqual(output.stat().st_size, 120000)
            self.assertLess(video['width'], 640)

    def test_failed_export_keeps_existing_output(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); source = root / 'source.mp4'; output = root / 'output.mp4'
            run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=80x60:rate=10', '-t', '2', '-c:v', 'libx264', str(source)])
            output.write_bytes(b'unchanged')
            with self.assertRaises(MediaError): export(source, output, 0, 2, .001)
            self.assertEqual(output.read_bytes(), b'unchanged')

    def test_trim_from_between_keyframes_starts_with_selected_frame(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); source = root / 'source.mkv'; output = root / 'trim.mp4'
            run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=10',
                 '-t', '8', '-c:v', 'libx264', '-g', '50', '-keyint_min', '50',
                 '-sc_threshold', '0', str(source)])
            trim(source, output, 2.3, 4.1)
            def frame(path, timestamp):
                result = run(['ffmpeg', '-v', 'error', '-ss', str(timestamp), '-i', str(path),
                              '-frames:v', '1', '-f', 'framemd5', '-'])
                return result.splitlines()[-1].split(',')[-1].strip()
            self.assertEqual(frame(source, 2.3), frame(output, 0))
            with self.assertRaisesRegex(MediaError, 'MP4 nebo MOV'):
                trim(source, root / 'unsafe.mkv', 2.3, 4.1)

    def test_trim_endpoint_and_audio_sync_with_reordered_frames(self):
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / 'source.mkv'; output = Path(d) / 'trim.mp4'
            run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=10',
                 '-f', 'lavfi', '-i', r'aevalsrc=if(between(t\,3\,3.1)\,0.7*sin(2*PI*440*t)\,0):s=48000',
                 '-t', '6', '-c:v', 'libx264', '-g', '50', '-c:a', 'aac', str(source)])
            trim(source, output, 2.3, 4.1)
            self.assertAlmostEqual(duration(probe(output)), 1.8, delta=.02)
            raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(output), '-map', '0:a:0',
                                  '-f', 's16le', '-ac', '1', '-ar', '48000', '-'], capture_output=True, check=True).stdout
            samples = array.array('h'); samples.frombytes(raw)
            first = next(i for i, sample in enumerate(samples) if abs(sample) > 200)
            self.assertAlmostEqual(first / 48000, .7, delta=.05)
            frame_hashes = run(['ffmpeg', '-v', 'error', '-i', str(output), '-map', '0:v:0', '-f', 'framemd5', '-'])
            frames = [line for line in frame_hashes.splitlines() if line and not line.startswith('#')]
            self.assertEqual(len(frames), 18)

    def test_unchanged_mix_preserves_encoded_audio(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / 'source.mkv'; output = Path(d) / 'trim.mkv'
            run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=80x60:rate=10',
                 '-f', 'lavfi', '-i', 'sine=frequency=440', '-f', 'lavfi', '-i', 'sine=frequency=880',
                 '-t', '2', '-map', '0:v', '-map', '1:a', '-map', '2:a', '-c:v', 'libx264',
                 '-c:a', 'aac', str(source)])
            trim(source, output, 0, 1.5, mix_first=True)
            def hashes(path, stream):
                data = run(['ffprobe', '-v', 'error', '-select_streams', f'a:{stream}', '-show_packets',
                            '-show_data_hash', 'sha256', '-show_entries', 'packet=data_hash', '-of', 'json', str(path)])
                return [p['data_hash'] for p in json.loads(data)['packets']][:10]
            for stream in (0, 1):
                self.assertEqual(hashes(source, stream), hashes(output, stream))

class AudioMixIdentificationTests(unittest.TestCase):
    def test_three_independent_tracks_do_not_imply_a_mix(self):
        from clipper.media import first_track_is_named_mix
        streams = [{'codec_type': 'audio', 'tags': {'title': label}} for label in ('Game', 'Chat', 'Mic')]
        self.assertFalse(first_track_is_named_mix({'streams': streams}))
        streams[0]['tags']['title'] = 'Mix'
        self.assertTrue(first_track_is_named_mix({'streams': streams}))

class MediaProgressTests(unittest.TestCase):
    def test_trim_and_export_report_completion_after_output_exists(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); source = root / 'source.mp4'
            run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=15',
                 '-t', '2', '-c:v', 'libx264', str(source)])
            for name, action in [
                ('trim.mp4', lambda dest, callback: trim(source, dest, .2, 1.5, progress=callback)),
                ('export.mp4', lambda dest, callback: export(source, dest, 0, 2, .25, progress=callback)),
            ]:
                destination = root / name; events = []
                action(destination, lambda value: events.append((value, destination.exists())))
                self.assertTrue(events)
                self.assertEqual(events[-1], (100, True))
                self.assertTrue(all(0 <= value <= 100 for value, _ in events))

class MediaCancellationTests(unittest.TestCase):
    def test_cancel_export_keeps_destination_and_removes_temporary_files(self):
        from clipper.media import Cancellation, MediaCancelled
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); source = root / 'source.mp4'; destination = root / 'export.mp4'
            run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=30',
                 '-t', '5', '-c:v', 'libx264', str(source)])
            destination.write_bytes(b'old output')
            token = Cancellation(); events = []
            def progress(value):
                events.append(value); token.cancel()
            with self.assertRaises(MediaCancelled):
                export(source, destination, 0, 5, .5, progress=progress, cancellation=token)
            self.assertTrue(events)
            self.assertEqual(destination.read_bytes(), b'old output')
            self.assertFalse(list(root.glob('.clipper-*')))

    def test_cancel_cannot_undo_a_committed_file(self):
        from clipper.media import Cancellation
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); temp = root / 'tmp'; output = root / 'out'
            temp.write_bytes(b'finished'); token = Cancellation(); token.commit(temp, output)
            self.assertFalse(token.cancel())
            self.assertEqual(output.read_bytes(), b'finished')

class MixPreservationTests(unittest.TestCase):
    def test_rebuilt_mix_does_not_reencode_unchanged_stems(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); source = root / 'source.mkv'; output = root / 'trim.mkv'
            run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=80x60:rate=10',
                 '-f', 'lavfi', '-i', 'sine=frequency=440', '-f', 'lavfi', '-i', 'sine=frequency=440',
                 '-f', 'lavfi', '-i', 'sine=frequency=880', '-t', '2', '-map', '0:v', '-map', '1:a',
                 '-map', '2:a', '-map', '3:a', '-c:v', 'libx264', '-c:a', 'libopus', str(source)])
            audio = [s for s in probe(source)['streams'] if s['codec_type'] == 'audio']
            trim(source, output, 0, 1.5, {audio[1]['index']: .5}, mix_first=True)
            result_audio = [s for s in probe(output)['streams'] if s['codec_type'] == 'audio']
            self.assertEqual([s['codec_name'] for s in result_audio], ['aac', 'aac', 'opus'])
            def hashes(path, stream):
                data = run(['ffprobe', '-v', 'error', '-select_streams', f'a:{stream}', '-show_packets',
                            '-show_data_hash', 'sha256', '-show_entries', 'packet=data_hash', '-of', 'json', str(path)])
                return [p['data_hash'] for p in json.loads(data)['packets']][:10]
            self.assertEqual(hashes(source, 2), hashes(output, 2))

class ProbeTimeoutTests(unittest.TestCase):
    def test_probe_reports_timeout(self):
        from unittest.mock import patch
        with patch('clipper.media.subprocess.run', side_effect=subprocess.TimeoutExpired('ffprobe', 30)):
            with self.assertRaisesRegex(MediaError, 'příliš dlouho'):
                probe('slow-video.mp4')
