import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import tempfile
import unittest
from pathlib import Path
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication
from clipper.media import run
from clipper.waveforms import Waveforms

class WaveformTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])
    def test_waveform_is_generated_and_cached(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); source=root/'audio.wav'
            run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=440','-t','1',str(source)])
            worker=Waveforms(source,root/'cache'); result=[]; loop=QEventLoop()
            worker.ready.connect(lambda index,path:(result.append(path),loop.quit()))
            worker.failed.connect(lambda index:loop.quit())
            timer=QTimer(loop); timer.setSingleShot(True); timer.timeout.connect(loop.quit); timer.start(15000)
            worker.request(0); loop.exec(); worker.shutdown()
            self.assertEqual(len(result),1); self.assertTrue(Path(result[0]).is_file())
