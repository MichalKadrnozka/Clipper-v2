import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

class SelfTestTests(unittest.TestCase):
    def test_launcher_checks_actual_media_dependencies(self):
        with tempfile.TemporaryDirectory() as d:
            report = Path(d) / 'report.json'
            env = os.environ.copy(); env['QT_QPA_PLATFORM'] = 'offscreen'
            env['PYTHONPATH'] = os.getcwd() + os.pathsep + env.get('PYTHONPATH', '')
            result = subprocess.run([sys.executable, 'scripts/launch.py', '--self-test', str(report)],
                                    env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(report.read_text())
            self.assertTrue(data['ok'])
            self.assertTrue(data['qt_multimedia'])
            self.assertTrue(data['ffmpeg'])
            self.assertTrue(data['ffprobe'])

    def test_launcher_opens_and_closes_an_isolated_main_window(self):
        with tempfile.TemporaryDirectory() as d:
            report = Path(d) / 'ui-report.json'
            env = os.environ.copy(); env['QT_QPA_PLATFORM'] = 'offscreen'
            env['PYTHONPATH'] = os.getcwd() + os.pathsep + env.get('PYTHONPATH', '')
            result = subprocess.run([sys.executable, 'scripts/launch.py', '--self-test-ui', str(report)],
                                    env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(report.read_text())
            self.assertTrue(data['ok'])
            self.assertTrue(data['window_visible'])
            self.assertTrue(data['closed'])
