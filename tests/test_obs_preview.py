import base64
import unittest
from unittest.mock import patch
from clipper.obs_preview import PreviewWorker

class PreviewTests(unittest.TestCase):
    def test_preview_decodes_obs_image(self):
        requests = []
        class Client:
            def __init__(self, *args): pass
            def request(self, name, data=None):
                if name == 'GetCurrentProgramScene': return {'currentProgramSceneName':'Game with overlays'}
                requests.append((name, data))
                return {'imageData':'data:image/png;base64,' + base64.b64encode(b'image').decode()}
        worker = PreviewWorker('', ''); frames=[]; worker.frame.connect(frames.append)
        with patch('clipper.obs_preview.OBSClient', Client), patch.object(worker, 'isInterruptionRequested', side_effect=[False, True]): worker.run()
        self.assertEqual(frames, [b'image'])
        self.assertEqual(requests[0][0], 'GetSourceScreenshot')
        self.assertEqual(requests[0][1]['sourceName'], 'Game with overlays')

    def test_invalid_url_is_reported_as_error(self):
        worker = PreviewWorker('invalid', ''); errors = []
        worker.error.connect(errors.append); worker.run()
        self.assertTrue(errors)

    def test_close_during_request_waits_without_blocking_ui(self):
        import time
        from PyQt6.QtCore import QEventLoop, QTimer
        from PyQt6.QtWidgets import QApplication, QDialog
        from clipper.obs_preview import OBSPreview
        app = QApplication.instance() or QApplication([])
        class SlowClient:
            def __init__(self, *args): pass
            def request(self, name, data=None):
                time.sleep(.3)
                if name == 'GetCurrentProgramScene': return {'currentProgramSceneName': 'Scene'}
                return {'imageData': 'data:image/png;base64,' + base64.b64encode(b'image').decode()}
        with patch('clipper.obs_preview.OBSClient', SlowClient):
            dialog = OBSPreview('ws://example', ''); dialog.show()
            elapsed = []
            start = time.monotonic(); dialog.close(); elapsed.append(time.monotonic() - start)
            self.assertLess(elapsed[0], .2)
            self.assertTrue(dialog.worker.isRunning())
            self.assertIsNotNone(dialog.pending_result)
            loop = QEventLoop(); dialog.finished.connect(loop.quit); QTimer.singleShot(3000, loop.quit); loop.exec()
            self.assertFalse(dialog.worker.isRunning())
            self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)
            dialog.deleteLater()
