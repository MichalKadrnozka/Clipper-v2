"""Media operations. Original files are never modified."""
from __future__ import annotations
import json
from fractions import Fraction
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import sys
import threading
from .tools import executable, external_environment
from .mp4_duration import limit_presentation, ContainerTimingError

class MediaError(RuntimeError):
    pass

class MediaCancelled(Exception):
    """A media operation was cancelled before its output was committed."""


class Cancellation:
    def __init__(self):
        self.lock = threading.Lock()
        self.cancelled = False
        self.committed = False
        self.process = None

    def cancel(self):
        with self.lock:
            if self.committed: return False
            self.cancelled = True
            if self.process and self.process.poll() is None:
                try: self.process.kill()
                except OSError: pass
            return True

    def check(self):
        with self.lock:
            if self.cancelled: raise MediaCancelled()

    def attach(self, process):
        with self.lock:
            if self.cancelled:
                try: process.kill()
                except OSError: pass
                raise MediaCancelled()
            self.process = process

    def detach(self, process):
        with self.lock:
            if self.process is process: self.process = None

    def commit(self, temporary, destination):
        # Cancelling and replacing the destination are mutually exclusive.
        with self.lock:
            if self.cancelled: raise MediaCancelled()
            os.replace(temporary, destination)
            self.committed = True

def run(args, timeout=None):
    try:
        p = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout, env=external_environment(), creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
    except subprocess.TimeoutExpired as exc:
        raise MediaError('Načítání souboru trvalo příliš dlouho.') from exc
    except OSError as exc:
        raise MediaError(str(exc)) from exc
    if p.returncode:
        raise MediaError(p.stderr[-4000:] or f'Process failed: {p.returncode}')
    return p.stdout

def run_progress(args, seconds, progress=None, cancellation=None):
    """Run FFmpeg and report timestamps without filling a stderr pipe."""
    if progress is None and cancellation is None:
        return run(args)
    command = [args[0], '-progress', 'pipe:1', '-stats_period', '0.5'] + args[1:]
    try:
        with tempfile.TemporaryFile(mode='w+t', encoding='utf-8', errors='replace') as errors:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors, text=True,
                encoding='utf-8', errors='replace', env=external_environment(), creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
            try:
                if cancellation: cancellation.attach(process)
                with process.stdout:
                    for line in process.stdout:
                        key, _, value = line.strip().partition('=')
                        if progress and key == 'out_time_us':
                            try: progress(max(0., min(1., int(value) / (seconds * 1_000_000))))
                            except ValueError: pass
                result = process.wait()
            except BaseException:
                process.kill(); process.wait(); raise
            finally:
                if cancellation: cancellation.detach(process)
            if cancellation: cancellation.check()
            if result:
                errors.seek(0, os.SEEK_END); size = errors.tell(); errors.seek(max(0, size - 4000))
                raise MediaError(errors.read() or f'Process failed: {result}')
    except OSError as exc:
        raise MediaError(str(exc)) from exc

def probe(path):
    info = json.loads(run([executable('ffprobe'), '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)], timeout=30))
    if not any(s.get('codec_type') == 'video' for s in info.get('streams', [])):
        raise MediaError('File has no video stream')
    return info

def first_track_is_named_mix(info):
    """Only identify a premix when the media explicitly labels it as one."""
    tracks = [stream for stream in info.get('streams', []) if stream.get('codec_type') == 'audio']
    if len(tracks) < 2:
        return False
    tags = tracks[0].get('tags') or {}
    name = str(tags.get('title') or tags.get('name') or '').strip().casefold()
    return name in ('mix', 'mixed', 'master mix', 'stereo mix')

def duration(info):
    try:
        value = float(info['format']['duration'])
        if math.isfinite(value) and value > 0:
            return value
    except (KeyError, ValueError, TypeError):
        pass
    raise MediaError('Could not determine duration')

def _validate(source, dest, start, end):
    source, dest = Path(source), Path(dest)
    if source.resolve() == dest.resolve():
        raise MediaError('Output must differ from original')
    info = probe(source)
    length = duration(info)
    if not (math.isfinite(start) and math.isfinite(end) and 0 <= start < end <= length + 0.05):
        raise MediaError('Invalid selection')
    if not dest.parent.is_dir():
        raise MediaError('Output directory does not exist')
    return info

def _temporary(dest):
    fd, name = tempfile.mkstemp(prefix='.clipper-', suffix=dest.suffix, dir=dest.parent)
    os.close(fd)
    return Path(name)

def trim(source, dest, start, end, volumes=None, mix_first=False, progress=None, cancellation=None):
    """Copy video losslessly; copy unchanged audio or re-encode adjusted tracks."""
    dest = Path(dest)
    if cancellation: cancellation.check()
    info = _validate(source, dest, start, end)
    if cancellation: cancellation.check()
    # Matroska stream copy cannot represent the decoder preroll as an edit list:
    # the supposedly trimmed file would visibly start at the preceding keyframe.
    if start > 0 and dest.suffix.casefold() not in ('.mp4', '.mov', '.m4v'):
        raise MediaError('Bezztrátový střih od zvoleného začátku ulož jako MP4 nebo MOV; tento formát by mohl zobrazit starší snímky.')
    volumes = volumes or {}
    audios = [s for s in info['streams'] if s.get('codec_type') == 'audio']
    for stream in audios:
        volume = float(volumes.get(stream['index'], 1.0))
        if not math.isfinite(volume) or not 0 <= volume <= 4:
            raise MediaError('Invalid audio volume')
    tmp = _temporary(dest)
    try:
        cmd = [executable('ffmpeg'), '-nostdin', '-v', 'error', '-y', '-ss', str(start), '-i', str(source), '-t', str(end-start), '-map', '0:v:0', '-c:v', 'copy']
        # An untouched legacy mix and its stems can all be copied verbatim.
        # Only rebuild the mix when a user actually changes a track level.
        if mix_first and len(audios) > 1 and any(float(volumes.get(s['index'], 1.0)) != 1.0 for s in audios):
            filters = []
            for i, stream in enumerate(audios[1:]):
                volume = float(volumes.get(stream['index'], 1.0))
                if volume == 1.0:
                    # Feed the mix from a decoded copy, but preserve this stem's packets.
                    filters.append(f"[0:{stream['index']}]anull[mix{i}]")
                else:
                    filters.append(f"[0:{stream['index']}]volume={volume},asplit=2[track{i}][mix{i}]")
            inputs = ''.join(f'[mix{i}]' for i in range(len(audios)-1))
            master = float(volumes.get(audios[0]['index'], 1.0))
            filters.append(f'{inputs}amix=inputs={len(audios)-1}:normalize=0,volume={master}[mixout]')
            cmd += ['-filter_complex', ';'.join(filters), '-map', '[mixout]']
            for i, stream in enumerate(audios[1:]):
                unchanged = float(volumes.get(stream['index'], 1.0)) == 1.0
                cmd += ['-map', f"0:{stream['index']}" if unchanged else f'[track{i}]']
            cmd += ['-c:a:0', 'aac', '-b:a:0', '192k']
            for i, stream in enumerate(audios[1:], 1):
                unchanged = float(volumes.get(stream['index'], 1.0)) == 1.0
                cmd += [f'-c:a:{i}', 'copy' if unchanged else 'aac']
                if not unchanged: cmd += [f'-b:a:{i}', '192k']
        else:
            for index, stream in enumerate(audios):
                volume = float(volumes.get(stream['index'], 1.0))
                cmd += ['-map', f"0:{stream['index']}"]
                if volume == 1.0:
                    cmd += [f'-c:a:{index}', 'copy']
                else:
                    cmd += [f'-c:a:{index}', 'aac', f'-b:a:{index}', '192k', f'-filter:a:{index}', f'volume={volume}']
        for index, stream in enumerate(audios):
            cmd += [f'-map_metadata:s:a:{index}', f"0:s:{stream['index']}"]
        run_progress(cmd + [str(tmp)], end-start, (lambda value: progress(int(value * 99))) if progress else None, cancellation)
        if dest.suffix.casefold() in ('.mp4', '.mov', '.m4v'):
            try: limit_presentation(tmp, end - start)
            except ContainerTimingError as exc: raise MediaError('Nelze bezpečně nastavit konec střihu: ' + str(exc)) from exc
        probe(tmp)
        if cancellation: cancellation.commit(tmp, dest)
        else: os.replace(tmp, dest)
        if progress: progress(100)
    finally:
        tmp.unlink(missing_ok=True)

def export(source, dest, start, end, target_mb, volumes=None, progress=None, cancellation=None):
    """Two-pass H.264 export with a bounded size; audio tracks are mixed."""
    dest = Path(dest)
    if cancellation: cancellation.check()
    info = _validate(source, dest, start, end)
    if cancellation: cancellation.check()
    if not math.isfinite(target_mb) or target_mb <= 0:
        raise MediaError('Target size must be positive')
    audios = [s for s in info['streams'] if s.get('codec_type') == 'audio']
    volumes = volumes or {}
    for s in audios:
        vol = float(volumes.get(s['index'], 1.0))
        if not math.isfinite(vol) or not 0 <= vol <= 16:
            raise MediaError('Invalid audio volume')
    seconds = end-start
    limit = int(target_mb * 1_000_000)
    audio_rate = 96000 if audios else 0
    video_rate = int(limit * 8 * .90 / seconds - audio_rate)
    if video_rate < 30000:
        raise MediaError('Target size is too small for this duration')
    tmp = _temporary(dest)
    try:
        with tempfile.TemporaryDirectory(prefix='clipper-pass-') as passdir:
            common = [executable('ffmpeg'), '-nostdin', '-v', 'error', '-y', '-ss', str(start), '-i', str(source), '-t', str(seconds)]
            source_video = next(s for s in info['streams'] if s.get('codec_type') == 'video')
            width, height = int(source_video.get('width', 0)), int(source_video.get('height', 0))
            try: fps = float(Fraction(source_video.get('avg_frame_rate', '30/1')))
            except (ValueError, ZeroDivisionError): fps = 30
            if not math.isfinite(fps) or fps <= 0: fps = 30
            audio = []
            if audios:
                filters = [f"[0:{s['index']}]volume={float(volumes.get(s['index'], 1.0))}[a{i}]" for i, s in enumerate(audios)]
                filters.append(''.join(f'[a{i}]' for i in range(len(audios))) + f'amix=inputs={len(audios)}:normalize=0[aout]')
                audio = ['-filter_complex', ';'.join(filters), '-map', '[aout]', '-c:a', 'aac', '-b:a', str(audio_rate)]
            for attempt in range(3):
                video = ['-c:v', 'libx264', '-b:v', str(video_rate), '-pix_fmt', 'yuv420p', '-passlogfile', str(Path(passdir)/'pass')]
                if width > 0 and height > 0:
                    # Limit spatial complexity for low-bitrate exports; never upscale.
                    max_pixels = max(4096, video_rate / max(fps, 1) / 0.06)
                    factor = min(1.0, math.sqrt(max_pixels / (width * height)))
                    out_width = max(2, int(width * factor) // 2 * 2)
                    out_height = max(2, int(height * factor) // 2 * 2)
                    if out_width != width or out_height != height:
                        video += ['-vf', f'scale={out_width}:{out_height}:flags=lanczos']
                run_progress(common + ['-map', '0:v:0'] + video + ['-pass', '1', '-an', '-f', 'null', os.devnull], seconds,
                             (lambda value: progress(int(value * 49))) if progress else None, cancellation)
                run_progress(common + ['-map', '0:v:0'] + video + ['-pass', '2'] + audio + ['-movflags', '+faststart', str(tmp)], seconds,
                             (lambda value: progress(50 + int(value * 49))) if progress else None, cancellation)
                probe(tmp)
                actual = tmp.stat().st_size
                if actual <= limit: break
                video_rate = int(video_rate * (limit / actual) * .82)
                if video_rate < 30000: break
            else:
                pass
        if tmp.stat().st_size > limit:
            raise MediaError('Export exceeded target size; choose a larger limit or a shorter selection')
        if cancellation: cancellation.commit(tmp, dest)
        else: os.replace(tmp, dest)
        if progress: progress(100)
    finally:
        tmp.unlink(missing_ok=True)
