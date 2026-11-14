"""Generate cached per-track waveform images with bounded asynchronous work."""
from collections import deque
import hashlib
import os
from pathlib import Path
import uuid
from PyQt6.QtCore import QObject, QProcess, QTimer, pyqtSignal
from .tools import executable, configure_external_process

class Waveforms(QObject):
    ready = pyqtSignal(int, str)
    failed = pyqtSignal(int)
    def __init__(self, source, cache, parent=None):
        super().__init__(parent); self.source=Path(source); self.cache=Path(cache); self.cache.mkdir(parents=True, exist_ok=True)
        self.queue=deque(); self.active={}; self.closing=False
    def request(self, stream_index):
        st=self.source.stat(); key=hashlib.sha256(f'{self.source.resolve()}:{st.st_mtime_ns}:{st.st_size}:{stream_index}:v2'.encode()).hexdigest()
        output=self.cache/(key+'.png')
        if output.is_file() and output.stat().st_size: self.ready.emit(stream_index, str(output)); return
        self.queue.append((stream_index,output)); self._schedule()
    def _schedule(self):
        while not self.closing and self.queue and len(self.active)<2:
            index,output=self.queue.popleft(); tmp=output.with_name(output.stem+'.'+uuid.uuid4().hex+'.tmp.png')
            process=QProcess(self); configure_external_process(process); self.active[process]=(index,output,tmp)
            timer=QTimer(process); timer.setSingleShot(True); timer.timeout.connect(process.kill); timer.start(120000)
            process.finished.connect(lambda code,status,p=process: self._finished(p,code))
            process.errorOccurred.connect(lambda error,p=process: self._failed_start(p,error))
            process.start(executable('ffmpeg'), ['-nostdin','-v','error','-y','-i',str(self.source),'-filter_complex',f'[0:{index}]aformat=channel_layouts=mono,showwavespic=s=1000x64:colors=0xff8c42:filter=peak:scale=sqrt:draw=full[v]','-map','[v]','-frames:v','1',str(tmp)])
    def _failed_start(self, process, error):
        if error==QProcess.ProcessError.FailedToStart: self._finished(process,-1)
    def _finished(self, process, code):
        data=self.active.pop(process,None)
        if data is None: return
        index,output,tmp=data; process.deleteLater()
        if not self.closing and code==0 and tmp.is_file() and tmp.stat().st_size:
            try: os.replace(tmp,output); self.ready.emit(index,str(output))
            except OSError: tmp.unlink(missing_ok=True); self.failed.emit(index)
        else:
            tmp.unlink(missing_ok=True)
            if not self.closing: self.failed.emit(index)
        self._schedule()
    def shutdown(self):
        self.closing=True; self.queue.clear()
        for process in list(self.active): process.kill(); process.waitForFinished(3000)
        self.active.clear()
