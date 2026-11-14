"""Live OBS scene preview, acquired off the UI thread."""
import base64
from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QDialog, QLabel, QVBoxLayout
from .obs import OBSClient

class PreviewWorker(QThread):
    frame = pyqtSignal(bytes)
    error = pyqtSignal(str)
    def __init__(self, url, password, parent=None):
        super().__init__(parent); self.url=url; self.password=password
    def run(self):
        try:
            client = OBSClient(self.url, self.password)
        except Exception as exc:
            self.error.emit(str(exc)); return
        while not self.isInterruptionRequested():
            try:
                scene = client.request('GetCurrentProgramScene')['currentProgramSceneName']
                result = client.request('GetSourceScreenshot', {'sourceName':scene,'imageFormat':'jpg','imageWidth':640,'imageHeight':360,'imageCompressionQuality':70})
                self.frame.emit(base64.b64decode(result['imageData'].split(',',1)[-1], validate=True))
            except Exception as exc:
                self.error.emit(str(exc)); return
            for _ in range(20):
                if self.isInterruptionRequested(): return
                self.msleep(100)

class OBSPreview(QDialog):
    def __init__(self, url, password, parent=None):
        super().__init__(parent); self.setWindowTitle('Náhled OBS'); self.resize(720, 450)
        layout=QVBoxLayout(self); self.image=QLabel('Načítám náhled…'); self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setMinimumSize(320, 180); layout.addWidget(self.image)
        self.pending_result = None
        self.worker=PreviewWorker(url,password,self); self.worker.frame.connect(self.update_frame)
        self.worker.error.connect(self.preview_error); self.worker.finished.connect(self.worker_finished); self.worker.start()
    def update_frame(self, data):
        if self.pending_result is not None: return
        picture=QPixmap()
        if picture.loadFromData(data): self.image.setPixmap(picture.scaled(self.image.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        else: self.image.setText('Náhled nelze načíst')
    def preview_error(self, message):
        if self.pending_result is None: self.image.setText(message)
    def closeEvent(self, event):
        if self.worker.isRunning():
            event.ignore(); self.done(QDialog.DialogCode.Rejected); return
        super().closeEvent(event)
    def worker_finished(self):
        if self.pending_result is not None:
            result = self.pending_result; self.pending_result = None
            super().done(result)
    def done(self, result):
        if self.worker.isRunning():
            self.pending_result = result
            self.image.setText('Ukončuji náhled…')
            self.worker.requestInterruption()
            return
        super().done(result)
