"""Non-destructive video editor using Qt Multimedia for playback."""
import os
import tempfile
from fractions import Fraction
from pathlib import Path
from PyQt6 import sip
# Unreliable hardware backends can fail indefinitely for an unsupported codec.
# Prefer software decoding; an explicit environment override remains available.
os.environ.setdefault("QT_FFMPEG_DECODING_HW_DEVICE_TYPES", ",")
from PyQt6.QtCore import Qt, QTimer, QUrl, QRectF, QRect, QSize, pyqtSignal
from PyQt6.QtWidgets import (QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
    QPushButton, QSlider, QVBoxLayout, QWidget, QCheckBox, QScrollArea, QStyle, QStyleOptionSlider, QGroupBox, QSplitter, QFrame)
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink
from PyQt6.QtGui import QPainter, QColor, QPixmap, QPen, QIcon
from .media import duration, probe, first_track_is_named_mix
from .proxy import PreviewProxy
from .waveforms import Waveforms
from .audio_preview import AudioPreview

class VideoSurface(QWidget):
    """Paint video frames inside Qt, including on Wayland and offscreen backends."""
    frameChanged = pyqtSignal(object)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.sink = QVideoSink(self); self.image = None; self.poster = None
        self.sink.videoFrameChanged.connect(self.set_frame)
    def videoSink(self): return self.sink
    def set_poster(self, pixmap):
        if pixmap and not pixmap.isNull():
            self.poster = pixmap.toImage(); self.update()
    def set_frame(self, frame):
        if frame.isValid():
            image = frame.toImage()
            if not image.isNull(): self.image = image; self.frameChanged.emit(image); self.update()
    def paintEvent(self, event):
        painter = QPainter(self); painter.fillRect(self.rect(), QColor('#080a0f'))
        image = self.image or self.poster
        if image:
            size = image.size(); size.scale(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
            rectangle = QRectF((self.width()-size.width())/2, (self.height()-size.height())/2, size.width(), size.height())
            painter.drawImage(rectangle, image)
        else:
            painter.setPen(QColor('#778398'))
            painter.drawText(self.rect().adjusted(24, 20, -24, -20), Qt.AlignmentFlag.AlignCenter, 'Video se načítá…')

class SeekSlider(QSlider):
    """Seek directly to a click while retaining normal handle dragging."""
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            option = QStyleOptionSlider(); self.initStyleOption(option)
            handle = self.style().subControlRect(QStyle.ComplexControl.CC_Slider, option,
                                                  QStyle.SubControl.SC_SliderHandle, self)
            span = max(1, self.width() - handle.width())
            position = round(event.position().x() - handle.width() / 2)
            value = QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), position, span, option.upsideDown)
            self.setValue(value); self.sliderMoved.emit(value)
        super().mousePressEvent(event)

class WaveformView(QWidget):
    seekRequested = pyqtSignal(float)
    startRequested = pyqtSignal(float)
    endRequested = pyqtSignal(float)
    def __init__(self, parent=None):
        super().__init__(parent); self.picture = QPixmap(); self.start = 0.; self.end = 1.; self.position = 0.
        self.dragging = None
        self.setMinimumWidth(200); self.setFixedHeight(48); self.setCursor(Qt.CursorShape.PointingHandCursor)
    def set_image(self, path): self.picture.load(path); self.update()
    def paintEvent(self, event):
        painter = QPainter(self); painter.fillRect(self.rect(), QColor('#171717'))
        if not self.picture.isNull(): painter.drawPixmap(self.rect(), self.picture)
        painter.fillRect(QRectF(0,0,self.width()*self.start,self.height()), QColor(8,10,15,160))
        painter.fillRect(QRectF(self.width()*self.end,0,self.width()*(1-self.end),self.height()), QColor(8,10,15,160))
        painter.setPen(QPen(QColor('#ffb270'),2))
        for value in (self.start,self.end): painter.drawLine(int(self.width()*value),0,int(self.width()*value),self.height())
        painter.setPen(QPen(QColor('#ffffff'),1)); x=int(self.width()*self.position); painter.drawLine(x,0,x,self.height())
    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton: return
        x = event.position().x()
        start_distance = abs(x - self.width() * self.start)
        end_distance = abs(x - self.width() * self.end)
        if min(start_distance, end_distance) <= 8:
            self.dragging = 'start' if start_distance <= end_distance else 'end'
        else:
            self.seekRequested.emit(max(0., min(1., x / max(1, self.width()))))
        event.accept()
    def mouseMoveEvent(self, event):
        if not self.dragging: return
        fraction = max(0., min(1., event.position().x() / max(1, self.width())))
        if self.dragging == 'start': self.startRequested.emit(min(fraction, self.end))
        else: self.endRequested.emit(max(fraction, self.start))
        event.accept()
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton: self.dragging = None; event.accept()


class VideoTimelineStrip(QWidget):
    seekRequested = pyqtSignal(float)
    startRequested = pyqtSignal(float)
    endRequested = pyqtSignal(float)
    def __init__(self, duration, parent=None):
        super().__init__(parent); self.length=max(float(duration), .001); self.image=None
        self.start=0.; self.end=1.; self.position=0.; self.dragging=None
        self.setMinimumHeight(76); self.setMaximumHeight(92); self.setMinimumWidth(280)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
    def set_image(self, image): self.image=image; self.update()
    def set_range(self, start, end, position):
        self.start=max(0.,min(1.,start)); self.end=max(self.start,min(1.,end)); self.position=max(0.,min(1.,position)); self.update()
    def paintEvent(self, event):
        painter=QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect=self.rect().adjusted(0,19,0,-2); painter.fillRect(self.rect(),QColor('#171717'))
        painter.fillRect(rect,QColor('#27528f'))
        painter.setPen(QColor(255,255,255,125))
        painter.drawText(QRectF(rect.left()+10,rect.top(),90,rect.height()),Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignLeft,'VIDEO')
        painter.fillRect(QRectF(rect.left(),rect.top(),rect.width()*self.start,rect.height()),QColor(0,0,0,175))
        painter.fillRect(QRectF(rect.left()+rect.width()*self.end,rect.top(),rect.width()*(1-self.end),rect.height()),QColor(0,0,0,175))
        interval=max(1.,self.length/8); power=10**int(__import__('math').log10(interval)); interval=min((1,2,5,10),key=lambda n:abs(n*power-interval))*power
        painter.setPen(QColor('#b7b7b7')); tick=0.
        while tick<=self.length:
            x=rect.left()+rect.width()*tick/self.length
            painter.drawLine(int(x),2,int(x),15)
            label=f'{int(tick)//60}:{int(tick)%60:02d}'
            painter.drawText(QRectF(x+3,0,48,17),Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,label)
            tick+=interval
        painter.setPen(QPen(QColor('#ff7300'),2))
        for value in (self.start,self.end):
            x=int(rect.left()+rect.width()*value); painter.drawLine(x,rect.top(),x,rect.bottom())
        x=int(rect.left()+rect.width()*self.position); painter.setPen(QPen(QColor('#ffffff'),2)); painter.drawLine(x,rect.top(),x,rect.bottom())
    def mousePressEvent(self,event):
        if event.button()!=Qt.MouseButton.LeftButton:return
        rect=self.rect().adjusted(0,19,0,-2); x=event.position().x(); start=rect.left()+rect.width()*self.start; end=rect.left()+rect.width()*self.end
        if abs(x-start)<=9:self.dragging='start'
        elif abs(x-end)<=9:self.dragging='end'
        else:self.seekRequested.emit(max(0.,min(1.,(x-rect.left())/max(1,rect.width()))))
        event.accept()
    def mouseMoveEvent(self,event):
        if not self.dragging:return
        rect=self.rect().adjusted(0,19,0,-2); fraction=max(0.,min(1.,(event.position().x()-rect.left())/max(1,rect.width())))
        if self.dragging=='start':self.startRequested.emit(min(fraction,self.end))
        else:self.endRequested.emit(max(fraction,self.start))
        event.accept()
    def mouseReleaseEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:self.dragging=None;event.accept()

class Editor(QDialog):
    def __init__(self, path, parent=None, info=None):
        super().__init__(parent)
        self.owner = parent
        self.setWindowFlags(Qt.WindowType.Widget)
        self.path = Path(path)
        self.info = info if info is not None else probe(path)
        self.length = duration(self.info)
        self.operation = None
        self.proxy = None
        self.closing = False
        self._play_requested = False
        self.setWindowTitle(f'Clipper · Editor · {self.path.name}')
        self.resize(1320, 850); self.setMinimumSize(0, 0)
        layout = QVBoxLayout(self); layout.setContentsMargins(10, 8, 10, 8); layout.setSpacing(7)
        header = QHBoxLayout(); layout.addLayout(header)
        back = QPushButton('‹  Knihovna'); back.setIcon(QIcon(str(Path(__file__).parent / 'assets/icons/icons8-back-96.png'))); back.clicked.connect(self.reject); header.addWidget(back)
        title = QLabel(self.path.stem); title.setStyleSheet('font-size:17px;font-weight:700;color:#eeeeee;'); header.addWidget(title)
        header.addStretch(1)
        seconds = int(self.length)
        header_info = QLabel(f'{self.path.suffix.upper().lstrip(".")}  ·  {seconds // 60}:{seconds % 60:02d}'); header_info.setStyleSheet('color:#999999;'); header.addWidget(header_info)
        workspace = QSplitter(Qt.Orientation.Vertical); layout.addWidget(workspace, 1)
        video_panel = QFrame(); video_panel.setObjectName('editorVideoPanel'); video_panel.setStyleSheet('#editorVideoPanel {background:#121212;border:0;border-radius:0;}')
        video_layout = QVBoxLayout(video_panel); video_layout.setContentsMargins(0, 0, 0, 2); video_layout.setSpacing(5)
        self.player = QMediaPlayer(self)
        self.video = VideoSurface(); self.video.setMinimumSize(160, 90); self.video.setStyleSheet('background:#050505;')
        self.player.setVideoSink(self.video.videoSink()); video_layout.addWidget(self.video, 1)
        self._thumbnail_service = getattr(parent, 'thumbnails', None)
        self._thumbnail_slot = None
        if self._thumbnail_service is not None:
            poster = self._thumbnail_service.request(self.path)
            if poster:
                pixmap = QPixmap(str(poster)); self.video.set_poster(pixmap)
            else:
                self._thumbnail_slot = self._set_thumbnail_poster
                self._thumbnail_service.ready.connect(self._thumbnail_slot)
        time_row = QHBoxLayout(); video_layout.addLayout(time_row)
        initial_seconds = max(0, int(self.length))
        self.time = QLabel(f'0:00 / {initial_seconds//60}:{initial_seconds%60:02d}'); self.time.setStyleSheet('color:#bbbbbb;font-weight:600;'); time_row.addWidget(self.time)
        time_row.addStretch(1)
        self.range_summary = QLabel('Celý klip'); self.range_summary.setStyleSheet('color:#ff7300;font-weight:600;'); time_row.addWidget(self.range_summary)
        self.seek = SeekSlider(Qt.Orientation.Horizontal); self.seek.setRange(0, int(self.length * 1000)); video_layout.addWidget(self.seek)
        self.seek.sliderMoved.connect(self.player.setPosition)
        range_box = QGroupBox('Rozsah střihu'); range_layout = QHBoxLayout(range_box); range_layout.setContentsMargins(8, 3, 8, 3); range_layout.setSpacing(7)
        self.start = QDoubleSpinBox(); self.end = QDoubleSpinBox()
        for value in (self.start, self.end): value.setRange(0, self.length); value.setDecimals(2); value.setSuffix(' s'); value.setFixedWidth(112); value.setMinimumHeight(30)
        self.end.setValue(self.length); self.start.setToolTip('Přesný čas začátku.'); self.end.setToolTip('Přesný čas konce.')
        range_layout.addWidget(QLabel('IN')); range_layout.addWidget(self.start)
        mark_start = QPushButton(); mark_start.setIcon(QIcon(str(Path(__file__).parent / 'assets/icons/trim_start.png'))); mark_start.setFixedSize(34,30); mark_start.setToolTip('Nastavit začátek na aktuální pozici.'); mark_start.clicked.connect(self.mark_start); range_layout.addWidget(mark_start)
        range_layout.addSpacing(12); range_layout.addWidget(QLabel('OUT')); range_layout.addWidget(self.end)
        mark_end = QPushButton(); mark_end.setIcon(QIcon(str(Path(__file__).parent / 'assets/icons/trim_end.png'))); mark_end.setFixedSize(34,30); mark_end.setToolTip('Nastavit konec na aktuální pozici.'); mark_end.clicked.connect(self.mark_end); range_layout.addWidget(mark_end); range_layout.addStretch(1)
        video_layout.addWidget(range_box)
        controls = QHBoxLayout(); video_layout.addLayout(controls)
        def tool_button(icon, tooltip, handler):
            button=QPushButton(); button.setIcon(QIcon(str(Path(__file__).parent / 'assets/icons' / icon))); button.setIconSize(QSize(20,20)); button.setFixedSize(38,34); button.setToolTip(tooltip); button.clicked.connect(handler); controls.addWidget(button); return button
        tool_button('icons8-skip-to-start-96.png','Přejít na začátek střihu',lambda:self.player.setPosition(int(self.start.value()*1000)))
        tool_button('icons8-undo-96.png','O pět snímků zpět',lambda:self.step_frames(-5))
        self.play_button=QPushButton(); self.play_button.setIcon(QIcon(str(Path(__file__).parent / 'assets/icons/icons8-play-96.png'))); self.play_button.setIconSize(QSize(22,22)); self.play_button.setFixedSize(44,36); self.play_button.setProperty('primary',True); self.play_button.setToolTip('Přehrát / pauza'); self.play_button.clicked.connect(self.toggle); controls.addWidget(self.play_button)
        self.retry_preview = QPushButton('Zkusit náhled znovu'); self.retry_preview.hide(); self.retry_preview.clicked.connect(self.retry_preview_generation); controls.addWidget(self.retry_preview)
        tool_button('icons8-redo-96.png','O pět snímků vpřed',lambda:self.step_frames(5))
        tool_button('icons8-skip-96.png','Přejít na konec střihu',lambda:self.player.setPosition(int(self.end.value()*1000)))
        controls.addSpacing(10)
        self.speed=QPushButton('1×'); self.speed.setFixedHeight(34); self.speed.setToolTip('Rychlost přehrávání'); self.speed.clicked.connect(self.change_speed); controls.addWidget(self.speed)
        self.mute=QPushButton(); self.mute.setIcon(QIcon(str(Path(__file__).parent / 'assets/icons/icons8-volume-96.png'))); self.mute.setIconSize(QSize(20,20)); self.mute.setFixedSize(38,34); self.mute.setCheckable(True); self.mute.setToolTip('Ztlumit zvuk'); controls.addWidget(self.mute)
        self.listen_volume=QSlider(Qt.Orientation.Horizontal); self.listen_volume.setRange(0,100); self.listen_volume.setValue(100); self.listen_volume.setFixedWidth(100); controls.addWidget(self.listen_volume)
        controls.addStretch(1)
        save_trim=QPushButton('Uložit střih'); save_trim.setIcon(QIcon(str(Path(__file__).parent / 'assets/icons/icons8-trim-96.png'))); save_trim.setProperty('primary',True); save_trim.clicked.connect(lambda:self.accept_operation('trim')); controls.addWidget(save_trim)
        export_button=QPushButton('Export…'); export_button.setIcon(QIcon(str(Path(__file__).parent / 'assets/icons/icons8-export-96.png'))); export_button.clicked.connect(lambda:self.accept_operation('export')); controls.addWidget(export_button)
        self.volumes = {}; self.wave_labels = {}
        saved = parent.library.edit_for(self.path) if parent and hasattr(parent, 'library') else {}
        self.track_names = saved.get('track_names', [])
        if not isinstance(self.track_names, list): self.track_names = []
        self.track_names = [name if isinstance(name, str) else '' for name in self.track_names]
        cache_root = parent.data_path if parent and hasattr(parent, 'data_path') else Path(tempfile.gettempdir()) / 'clipper'
        self.waveforms = Waveforms(self.path, cache_root / 'waveforms', self)
        self.waveforms.ready.connect(self.waveform_ready); self.waveforms.failed.connect(self.waveform_failed)
        track_box = QWidget(); track_layout = QVBoxLayout(track_box); track_layout.setContentsMargins(4, 4, 4, 4); track_layout.setSpacing(7)
        track_scroll = QScrollArea(); track_scroll.setWidgetResizable(True); track_scroll.setMinimumHeight(92); track_scroll.setMaximumHeight(190); track_scroll.setWidget(track_box)
        track_group = QGroupBox('Zvukové stopy · klikni na průběh pro posun'); track_group_layout = QVBoxLayout(track_group); track_group_layout.setContentsMargins(8, 8, 8, 8); track_group_layout.setSpacing(5); self.video_timeline=VideoTimelineStrip(self.length); track_group_layout.addWidget(self.video_timeline); track_group_layout.addWidget(track_scroll)
        self.video_timeline.seekRequested.connect(lambda fraction:self.player.setPosition(int(fraction*self.length*1000)))
        self.video_timeline.startRequested.connect(lambda fraction:self.start.setValue(fraction*self.length))
        self.video_timeline.endRequested.connect(lambda fraction:self.end.setValue(fraction*self.length))
        for stream in self.info['streams']:
            if stream.get('codec_type') != 'audio': continue
            slider = QDoubleSpinBox(); slider.setRange(0, 4); slider.setSingleStep(.1); slider.setValue(1); slider.setSuffix('×')
            title = (self.track_names[len(self.volumes)] if len(self.volumes) < len(self.track_names) else '') or stream.get('tags', {}).get('title') or stream.get('tags', {}).get('name') or f"Stopa {stream['index']}"
            row_card = QFrame(); row_card.setObjectName('audioTrackRow'); row_card.setStyleSheet('#audioTrackRow {background:#1e1e1e;border:1px solid #333333;border-radius:4px;}')
            row = QHBoxLayout(row_card); row.setContentsMargins(10, 5, 10, 5)
            track_label = QLabel(title); track_label.setMinimumWidth(130); track_label.setMaximumWidth(190); track_label.setToolTip(title); row.addWidget(track_label)
            slider.setToolTip(f'Hlasitost stopy {title}'); slider.setMinimumWidth(84); row.addWidget(slider)
            wave = WaveformView(); wave.seekRequested.connect(lambda fraction: self.player.setPosition(int(fraction * self.length * 1000)))
            wave.startRequested.connect(lambda fraction: self.start.setValue(fraction * self.length))
            wave.endRequested.connect(lambda fraction: self.end.setValue(fraction * self.length))
            wave.setToolTip('Kliknutím přeskočíš na místo, tažením oranžových úchytů upravíš střih.')
            row.addWidget(wave, 1)
            track_layout.addWidget(row_card); self.volumes[stream['index']] = slider; self.wave_labels[stream['index']] = wave
            self.waveforms.request(stream['index'])
        if not self.volumes:
            no_audio = QLabel('Soubor neobsahuje zvukové stopy.'); no_audio.setStyleSheet('color:#9da8ba;padding:12px;'); track_layout.addWidget(no_audio)
        self.first_is_mix = QCheckBox('První stopa je mix ostatních stop')
        self.first_is_mix.setToolTip('Při střihu a exportu vytvoří nový mix z jednotlivých upravených stop.')
        self.first_is_mix.setChecked(first_track_is_named_mix(self.info))
        if len(self.volumes) > 1: track_group_layout.insertWidget(0, self.first_is_mix)
        self.audio_status = QLabel(''); self.audio_status.setStyleSheet('color:#aeb8c8;')
        self.audio_preview = None
        if self.volumes:
            self.audio_preview = AudioPreview(self.path, self.player, self.volumes, self)
            self.audio_preview.failed.connect(lambda error: self.time.setText('Chyba zvuku: ' + error))
            self.mute.toggled.connect(self.audio_preview.set_muted)
            self.listen_volume.valueChanged.connect(lambda value: self.audio_preview.set_master(value / 100))
            self.first_is_mix.toggled.connect(self.audio_preview.set_first_is_mix)
            self.audio_preview.set_first_is_mix(self.first_is_mix.isChecked())
            for index, slider in self.volumes.items():
                slider.valueChanged.connect(lambda value, i=index: self.audio_preview.set_gain(i, value))
            self.audio_preview.status.connect(self.audio_status.setText)
        else:
            self.mute.setEnabled(False)
            self.listen_volume.setEnabled(False)
        track_group_layout.addWidget(self.audio_status)
        workspace.addWidget(video_panel); workspace.addWidget(track_group)
        workspace.setStretchFactor(0, 7); workspace.setStretchFactor(1, 2); workspace.setSizes([610, 180])
        footer = QHBoxLayout(); layout.addLayout(footer)
        keyboard_hint = QLabel('Mezerník: přehrát / pauza  ·  ← / →: snímek'); keyboard_hint.setStyleSheet('color:#888888;'); footer.addWidget(keyboard_hint); footer.addStretch(1)
        if parent and hasattr(parent, 'library'):
            try:
                self.start.setValue(float(saved.get('in', 0)) * self.length)
                self.end.setValue(float(saved.get('out', 1)) * self.length)
                for index, slider in self.volumes.items(): slider.setValue(float(saved.get('volumes', {}).get(str(index), 1)))
                if 'mix_first' in saved: self.first_is_mix.setChecked(bool(saved['mix_first']))
            except (TypeError, ValueError): pass
        self.start.valueChanged.connect(self.update_waveforms); self.end.valueChanged.connect(self.update_waveforms)
        self.player.positionChanged.connect(self.position_changed)
        self.player.playbackStateChanged.connect(lambda *_: self.update_play_state())
        self.player.errorOccurred.connect(self.player_error)
        self.update_waveforms(); self.update_play_state()
        video_stream = next(stream for stream in self.info['streams'] if stream.get('codec_type') == 'video')
        if video_stream.get('codec_name') == 'av1':
            self.prepare_preview()
        else:
            self.player.setSource(QUrl.fromLocalFile(str(self.path.resolve())))
    def prepare_preview(self):
        if self.proxy or self.closing: return
        self.time.setText('Připravuji náhled… 0 %')
        self.retry_preview.hide()
        self.play_button.setEnabled(False)
        parent = self.owner
        cache = (parent.data_path if parent and hasattr(parent, 'data_path') else Path(tempfile.gettempdir()) / 'clipper') / 'previews'
        self.proxy = PreviewProxy(self.path, cache, self, duration=self.length)
        self.proxy.ready.connect(self.preview_ready)
        self.proxy.progress.connect(lambda value: self.time.setText(f'Připravuji náhled… {value} %'))
        self.proxy.failed.connect(self.preview_failed)
        QTimer.singleShot(0, self.proxy.start)
    def _set_thumbnail_poster(self, path, image_path):
        try:
            if Path(path).resolve() != self.path.resolve(): return
        except OSError: return
        pixmap = QPixmap(image_path)
        if pixmap.isNull(): return
        self.video.set_poster(pixmap)
    def showEvent(self, event):
        super().showEvent(event)
    def preview_failed(self, error):
        if self.closing: return
        self.time.setText('Náhled se nepodařilo připravit: ' + error[-300:])
        self.play_button.setEnabled(False)
        self.retry_preview.show()
    def retry_preview_generation(self):
        if self.closing: return
        if self.proxy:
            self.player.stop(); self.player.setSource(QUrl())
            self.proxy.cancel()
            # A cached file that Qt cannot decode must not be reused forever.
            try: self.proxy.final.unlink(missing_ok=True)
            except OSError as exc:
                self.preview_failed(str(exc)); return
            self.proxy.deleteLater(); self.proxy = None
        self.prepare_preview()
    def update_waveforms(self):
        if self.closing: return
        def stamp(value):
            total = max(0, int(value)); return f'{total//60}:{total%60:02d}'
        self.range_summary.setText(f'{stamp(self.start.value())} – {stamp(self.end.value())}')
        position=min(1.,max(0.,self.player.position()/(self.length*1000)))
        self.video_timeline.set_range(self.start.value()/self.length,self.end.value()/self.length,position)
        for wave in self.wave_labels.values():
            wave.start = self.start.value()/self.length; wave.end = self.end.value()/self.length
            wave.position = position; wave.update()
    def update_play_state(self):
        if self.closing: return
        playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        icon = QStyle.StandardPixmap.SP_MediaPause if playing else QStyle.StandardPixmap.SP_MediaPlay
        self.play_button.setIcon(QIcon(str(Path(__file__).parent / 'assets/icons' / ('icons8-pause-96.png' if playing else 'icons8-play-96.png')))); self.play_button.setToolTip('Pauza' if playing else 'Přehrát')
    def waveform_ready(self, index, path):
        wave = self.wave_labels.get(index)
        if wave: wave.set_image(path); self.update_waveforms()
    def waveform_failed(self, index):
        if index in self.wave_labels: self.wave_labels[index].setToolTip('Průběh není dostupný')
    def preview_ready(self, path):
        self.player.setSource(QUrl.fromLocalFile(path)); self.play_button.setEnabled(True)
        self.time.setText('Náhled připraven')
        if self._play_requested: self.player.play()
    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            self.toggle(); event.accept(); return
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            stream = next(s for s in self.info['streams'] if s.get('codec_type') == 'video')
            try: fps = float(Fraction(stream.get('avg_frame_rate', '30/1')))
            except (ValueError, ZeroDivisionError): fps = 30
            if fps <= 0: fps = 30
            step = max(1, round(1000 / fps))
            if event.key() == Qt.Key.Key_Left: step = -step
            self.player.setPosition(max(0, self.player.position() + step)); event.accept(); return
        super().keyPressEvent(event)
    def position_changed(self, value):
        if self.closing: return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState and value >= int(self.end.value()*1000):
            self.player.pause()
        if not self.seek.isSliderDown(): self.seek.setValue(value)
        def fmt(ms): return f'{ms//60000}:{(ms//1000)%60:02d}'
        self.time.setText(f'{fmt(value)} / {fmt(int(self.length*1000))}')
        self.update_waveforms()
    def player_error(self, *args):
        if self.closing: return
        if not self.proxy:
            self.player.stop()
            self.prepare_preview()
        else:
            self.preview_failed('Chyba přehrávání: ' + self.player.errorString())
    def request_autoplay(self):
        if self.closing: return
        self._play_requested = True
        if self.play_button.isEnabled(): self.player.play()
    def toggle(self):
        if not self.play_button.isEnabled(): return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._play_requested = False; self.player.pause()
        else:
            self._play_requested = True
            if self.player.position() >= int(self.end.value()*1000) or self.player.position() < int(self.start.value()*1000):
                self.player.setPosition(int(self.start.value()*1000))
            self.player.play()
    def step_frames(self, count):
        stream = next(s for s in self.info['streams'] if s.get('codec_type') == 'video')
        try: fps = float(Fraction(stream.get('avg_frame_rate', '30/1')))
        except (ValueError, ZeroDivisionError): fps = 30.
        if fps <= 0: fps = 30.
        self.player.setPosition(max(0, min(int(self.length * 1000), self.player.position() + round(count * 1000 / fps))))
    def mark_start(self): self.start.setValue(self.player.position()/1000)
    def mark_end(self): self.end.setValue(self.player.position()/1000)
    def change_speed(self):
        rates = [1., 1.5, 2., .5]; current = self.player.playbackRate()
        rate = rates[(rates.index(current)+1) % len(rates)] if current in rates else 1.
        self.player.setPlaybackRate(rate); self.speed.setText(f'{rate:g}×')
    def accept_operation(self, operation):
        if self.start.value() >= self.end.value():
            self.time.setText('Konec musí být za začátkem.'); return
        self.operation = operation; self.accept()
    def result_values(self):
        volumes = {i: value.value() for i, value in self.volumes.items()}
        mix_first = self.first_is_mix.isChecked() and len(volumes) > 1
        if self.operation == 'export' and mix_first:
            master = volumes[next(iter(volumes))]
            for index in list(volumes)[1:]: volumes[index] *= master
            volumes[next(iter(volumes))] = 0
        return self.start.value(), self.end.value(), volumes, mix_first
    def done(self, result):
        if self.closing: return
        self.closing = True
        if self.audio_preview is not None: self.audio_preview.close()
        self.player.stop()
        self.player.setVideoSink(None)
        self.player.setSource(QUrl())
        sip.delete(self.player)
        try: self.video.videoSink().videoFrameChanged.disconnect()
        except (TypeError, RuntimeError): pass
        if self.proxy: self.proxy.cancel()
        if self._thumbnail_service is not None and self._thumbnail_slot is not None:
            try: self._thumbnail_service.ready.disconnect(self._thumbnail_slot)
            except (TypeError, RuntimeError): pass
        self.waveforms.shutdown()
        parent = self.owner
        if parent and hasattr(parent, 'library'):
            parent.library.save_edit(self.path, {'in': self.start.value() / self.length, 'out': self.end.value() / self.length,
                'volumes': {str(i): value.value() for i, value in self.volumes.items()}, 'mix_first': self.first_is_mix.isChecked(),
                'track_names': self.track_names})
        super().done(result)
