"""Synchronized independent audio tracks for the editor preview."""
import tempfile
import uuid
from pathlib import Path
from PyQt6 import sip
from PyQt6.QtCore import QObject, QTimer, QUrl, pyqtSignal
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from .audio_render import AudioRender


class AudioPreview(QObject):
    failed = pyqtSignal(str)
    status = pyqtSignal(str)

    def __init__(self, path, video, indices, parent=None):
        super().__init__(parent)
        self.video = video
        self.path = Path(path)
        self.indices = list(indices)
        self.players = {}
        self.outputs = {}
        self.gains = {index: 1.0 for index in self.indices}
        self.master = 1.0
        self.muted = False
        self.first_is_mix = False
        self.closed = False
        self.ready = set()
        self.render_mode = False; self.render_ready = False; self.render = None
        self.render_signature = None; self.render_candidate_signature = None
        self.render_dir = tempfile.TemporaryDirectory(prefix='clipper-audio-preview-')
        self.render_player = QMediaPlayer(self); self.render_output = QAudioOutput(self)
        self.render_player.setAudioOutput(self.render_output)
        self.render_player.errorOccurred.connect(self._render_player_error)
        self.render_player.playbackStateChanged.connect(self._render_player_state)
        self.render_timer = QTimer(self); self.render_timer.setSingleShot(True); self.render_timer.setInterval(350)
        self.render_timer.timeout.connect(self._start_render)
        for ordinal, index in enumerate(self.indices):
            player = QMediaPlayer(self)
            output = QAudioOutput(self)
            player.setAudioOutput(output)
            self.players[index] = player
            self.outputs[index] = output
            player.tracksChanged.connect(lambda i=index, n=ordinal: self._select(i, n))
            player.errorOccurred.connect(lambda error, message, i=index: self._error(i, message))
            player.setSource(QUrl.fromLocalFile(str(path.resolve())))
        video.playbackStateChanged.connect(self._state_changed)
        video.positionChanged.connect(self._position_changed)
        video.playbackRateChanged.connect(self._rate_changed)
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self._correct_drift)
        self.timer.start()
        self._volumes_changed()

    def _select(self, index, ordinal):
        if self.closed: return
        player = self.players[index]
        if len(player.audioTracks()) > ordinal:
            player.setActiveAudioTrack(ordinal)
            self.ready.add(index)
            self._volumes_changed()
            player.setPlaybackRate(self.video.playbackRate())
            player.setPosition(self.video.position())
            if self.video.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                player.play()

    def _error(self, index, message):
        if not self.closed:
            self.failed.emit(f'Stopa {index}: {message}')

    def set_gain(self, index, gain):
        if self.closed: return
        self.gains[index] = gain
        self._levels_changed()

    def set_master(self, value):
        if self.closed: return
        self.master = value
        self._levels_changed()

    def set_muted(self, value):
        if self.closed: return
        self.muted = value
        self._volumes_changed()

    def set_first_is_mix(self, value):
        if self.closed: return
        self.first_is_mix = value
        self._levels_changed()

    def _effective_levels(self):
        levels = [self.gains[index] for index in self.indices]
        if self.first_is_mix and len(levels) > 1:
            master = levels[0]; levels = [0] + [gain * master for gain in levels[1:]]
        return tuple(zip(self.indices, levels))

    def _output_levels(self):
        return tuple((index, gain * self.master) for index, gain in self._effective_levels())

    def _levels_changed(self):
        if self.closed: return
        levels = self._output_levels()
        requires_render = any(gain > 1 for _, gain in levels)
        if requires_render:
            self.render_mode = True
            if levels != self.render_signature:
                self.render_signature = levels; self.render_candidate_signature = None; self.render_ready = False
                self.render_output.setMuted(True)
                self.render_timer.start()
                self.status.emit('Připravuji přesné zesílení zvuku; dočasně je omezené na 1×…')
        else:
            self.render_timer.stop(); self.render_signature = None; self.render_candidate_signature = None
            self.render_mode = False; self.render_ready = False
            self._discard_render()
            self.status.emit('')
        self._volumes_changed()

    def _discard_render(self):
        self.render_player.stop(); self.render_player.setSource(QUrl())
        if self.render:
            self.render.cancel(); self.render.deleteLater(); self.render = None

    def _start_render(self):
        if self.closed or not self.render_mode: return
        self._discard_render()
        signature = self.render_signature
        target = Path(self.render_dir.name) / (uuid.uuid4().hex + '.m4a')
        job = AudioRender(self.path, target, signature, self); self.render = job
        job.ready.connect(lambda path: self._render_finished(job, signature, path))
        job.failed.connect(lambda error: self._render_failed(job, signature, error))
        job.start()

    def _render_finished(self, job, signature, path):
        if self.closed or job is not self.render or signature != self.render_signature: return
        self.render_player.setSource(QUrl.fromLocalFile(path))
        self.render_player.setPlaybackRate(self.video.playbackRate())
        self.render_player.setPosition(self.video.position())
        self.render_candidate_signature = signature
        if self.video.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.render_player.play()
        else:
            self._activate_render()

    def _activate_render(self):
        self.render_ready = True; self._volumes_changed(); self.status.emit('')

    def _render_player_state(self, state):
        if (not self.closed and self.render_mode and not self.render_ready
                and self.render_candidate_signature == self.render_signature
                and self.render_candidate_signature is not None
                and state == QMediaPlayer.PlaybackState.PlayingState):
            self._activate_render()

    def _render_player_error(self, error, message):
        if self.closed or not self.render_mode: return
        self.render_ready = False; self._volumes_changed()
        self.status.emit('Zesílený náhled zvuku nelze přehrát.')
        self.failed.emit('Náhled zvuku: ' + message)

    def _render_failed(self, job, signature, error):
        if self.closed or job is not self.render or signature != self.render_signature: return
        self.render_ready = False; self._volumes_changed()
        self.status.emit('Zesílený náhled zvuku se nepodařilo připravit.')
        self.failed.emit(error)

    def _volumes_changed(self):
        if self.closed: return
        for index, gain in self._output_levels():
            self.outputs[index].setVolume(min(1.0, max(0.0, gain)))
            self.outputs[index].setMuted(self.muted or (self.render_mode and self.render_ready) or index not in self.ready)
        # Rendered samples already include both track gains and master volume.
        self.render_output.setVolume(1.0)
        self.render_output.setMuted(self.muted or not self.render_mode or not self.render_ready)

    def _state_changed(self, state):
        if self.closed: return
        targets = [*self.players.values()] + ([self.render_player] if self.render_ready else [])
        for player in targets:
            if state == QMediaPlayer.PlaybackState.PlayingState:
                player.setPosition(self.video.position())
                player.play()
            elif state == QMediaPlayer.PlaybackState.PausedState:
                player.pause()
            else:
                player.stop()

    def _position_changed(self, position):
        if self.closed: return
        if self.video.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            targets = [*self.players.values()] + ([self.render_player] if self.render_ready else [])
            for player in targets: player.setPosition(position)
        else:
            self._correct_drift()

    def _correct_drift(self):
        if self.closed or self.video.playbackState() != QMediaPlayer.PlaybackState.PlayingState: return
        targets = [*self.players.values()] + ([self.render_player] if self.render_ready else [])
        for player in targets:
            if abs(player.position() - self.video.position()) > 250:
                player.setPosition(self.video.position())

    def _rate_changed(self, rate):
        if self.closed: return
        for player in [*self.players.values(), self.render_player]: player.setPlaybackRate(rate)

    def close(self):
        if self.closed: return
        self.closed = True
        self.timer.stop(); self.render_timer.stop()
        self._discard_render()
        self.render_player.setAudioOutput(None)
        for player in self.players.values():
            player.stop()
            player.setSource(QUrl())
            player.setAudioOutput(None)
        # Qt Multimedia can retain Windows file handles after setSource(QUrl())
        # until the player is destroyed; release it before returning to the library.
        for player in [*self.players.values(), self.render_player]: sip.delete(player)
        for output in [*self.outputs.values(), self.render_output]: sip.delete(output)
        self.players.clear(); self.outputs.clear()
        try: self.render_dir.cleanup()
        except OSError: pass
