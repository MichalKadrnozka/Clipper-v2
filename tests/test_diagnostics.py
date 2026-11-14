import unittest
from types import SimpleNamespace
from unittest.mock import patch
from clipper.diagnostics import diagnose

class DiagnosticTests(unittest.TestCase):
    def test_reports_broken_tool_and_inactive_replay(self):
        def command(args, **kwargs):
            if args[0] == 'ffprobe': return SimpleNamespace(returncode=1, stdout='', stderr='missing library')
            if '-encoders' in args: return SimpleNamespace(returncode=0, stdout=' V..... libx264 H.264', stderr='')
            return SimpleNamespace(returncode=0, stdout='version 1', stderr='')
        class OBS:
            def __init__(self, *args, **kwargs): pass
            def request(self, name): return {'obsVersion': '32'}
            def status(self): return False
        with patch('clipper.diagnostics.executable', side_effect=lambda name: name), patch('clipper.diagnostics.subprocess.run', side_effect=command), patch('clipper.diagnostics.OBSClient', OBS):
            results = {name: (ok, text) for name, ok, text in diagnose('ws://localhost:4455', '')}
        self.assertFalse(results['ffprobe'][0]); self.assertIn('missing library', results['ffprobe'][1])
        self.assertTrue(results['H.264 export'][0]); self.assertTrue(results['OBS WebSocket'][0])
        self.assertFalse(results['Replay buffer'][0])

    def test_missing_executable_and_obs_are_reported(self):
        with patch('clipper.diagnostics.subprocess.run', side_effect=FileNotFoundError('not installed')), patch('clipper.diagnostics.OBSClient', side_effect=ValueError('bad URL')):
            results = {name: (ok, text) for name, ok, text in diagnose('bad', '')}
        self.assertFalse(results['ffmpeg'][0]); self.assertIn('not installed', results['ffmpeg'][1])
        self.assertFalse(results['OBS WebSocket'][0]); self.assertIn('bad URL', results['OBS WebSocket'][1])
