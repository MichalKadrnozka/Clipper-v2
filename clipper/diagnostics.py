"""Non-destructive checks for the components used by Clipper."""
from __future__ import annotations
import subprocess
import sys
from .obs import OBSClient
from .tools import executable, external_environment


def _run(args, timeout=5):
    try:
        result = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace',
                                timeout=timeout, env=external_environment(), creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    output = ((result.stdout or result.stderr) if result.returncode == 0 else (result.stderr or result.stdout)).strip()
    return result.returncode == 0, output


def diagnose(url, password):
    """Check tools and OBS connectivity without changing recorder settings."""
    result = []
    for name in ('ffmpeg', 'ffprobe'):
        path = executable(name)
        ok, output = _run([path, '-version'])
        detail = output.splitlines()[0] if output else ('OK' if ok else 'Nelze spustit')
        if not ok: detail += ' — ověř úplnou instalaci FFmpeg nebo stažený balíček Clipperu.'
        result.append((name, ok, detail[:400]))
    if result[0][1]:
        ok, output = _run([executable('ffmpeg'), '-hide_banner', '-encoders'], timeout=10)
        has_h264 = ok and any('libx264' in line.split() for line in output.splitlines())
        result.append(('H.264 export', has_h264, 'libx264 dostupný' if has_h264 else 'FFmpeg neobsahuje enkodér libx264'))
    if sys.platform.startswith('linux'):
        ok, output = _run(['gpu-screen-recorder', '--version'])
        detail = output.splitlines()[0] if output else ('OK' if ok else 'Nelze spustit')
        if not ok: detail += ' — ověř instalaci rekordéru a jeho systémové knihovny.'
        result.append(('GPU Screen Recorder', ok, detail[:400]))
    try:
        client = OBSClient(url, password, timeout=3)
        version = client.request('GetVersion')
        result.append(('OBS WebSocket', True, 'Připojeno: ' + str(version.get('obsVersion', 'OBS'))))
        try:
            active = client.status()
            result.append(('Replay buffer', active, 'Běží' if active else 'Není spuštěný'))
        except Exception as exc:
            result.append(('Replay buffer', False, str(exc)[:300]))
    except Exception as exc:
        result.append(('OBS WebSocket', False, str(exc)[:300] + ' — spusť OBS, povol WebSocket a zkontroluj adresu a heslo.'))
    return result
