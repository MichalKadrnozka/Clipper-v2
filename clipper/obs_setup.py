"""Provision an isolated OBS scene collection and profile for Clipper."""
from dataclasses import dataclass
from pathlib import Path
import uuid
from .obs import OBSError

PROFILE = 'Clipper Capture'
COLLECTION = 'Clipper Capture'
SCENE = 'Clipper Screen'

@dataclass(frozen=True)
class ExtraAudioSource:
    name: str
    kind: str  # output (loopback) or input (microphone)
    device: str = 'default'
    gain: float = 1.0

    def validate(self):
        if not self.name.strip() or len(self.name) > 80: raise OBSError('Invalid audio track name')
        if self.kind not in ('output', 'input'): raise OBSError('Invalid audio source type')
        if not isinstance(self.device, str) or not self.device: raise OBSError('Invalid audio device')
        if not 0 <= self.gain <= 2: raise OBSError('Invalid audio gain')

@dataclass(frozen=True)
class OBSSettings:
    folder: str
    fps: int = 60
    seconds: int = 60
    width: int = 1920
    height: int = 1080
    container: str = 'mkv'
    desktop_audio: bool = True
    microphone: bool = True
    encoder: str = ''
    quality: str = 'HQ'
    desktop_gain: float = 1.0
    microphone_gain: float = 1.0
    capture_mode: str = 'display'
    extra_audio: tuple[ExtraAudioSource, ...] = ()

    def validate(self):
        if not Path(self.folder).is_dir(): raise OBSError('Clip folder does not exist')
        if not 1 <= self.fps <= 240 or not 1 <= self.seconds <= 3600: raise OBSError('Invalid capture settings')
        if not (16 <= self.width <= 4096 and 16 <= self.height <= 4096): raise OBSError('Invalid output resolution')
        if self.container not in ('mkv', 'mp4'): raise OBSError('Invalid recording format')
        if self.encoder not in ('', 'x264', 'nvenc', 'nvenc_hevc', 'nvenc_av1', 'qsv', 'qsv_av1', 'amd', 'amd_hevc', 'amd_av1'): raise OBSError('Invalid recording encoder')
        if self.capture_mode not in ('display', 'game'): raise OBSError('Invalid capture source')
        if self.quality not in ('Small', 'HQ'): raise OBSError('Invalid quality')
        if not 0 <= self.desktop_gain <= 2 or not 0 <= self.microphone_gain <= 2: raise OBSError('Invalid audio gain')
        if len(self.extra_audio) > 3: raise OBSError('OBS supports at most three additional tracks')
        for source in self.extra_audio: source.validate()

def configure_windows(client, settings):
    """Switch to a dedicated profile/collection, configuring only Clipper sources.

    OBS may require its output to be reloaded for changes to profile fields to
    take effect. The caller must surface errors; this routine never starts a
    buffer automatically.
    """
    settings.validate()
    for request in ('GetStreamStatus', 'GetRecordStatus', 'GetReplayBufferStatus'):
        try:
            active = client.request(request).get('outputActive')
        except OBSError as exc:
            if request == 'GetReplayBufferStatus' and exc.code == 604: continue
            raise
        if active: raise OBSError('Stop active OBS outputs before changing the Clipper profile.')
    profiles = client.request('GetProfileList')['profiles']
    client.request('SetCurrentProfile' if PROFILE in profiles else 'CreateProfile', {'profileName': PROFILE})
    collections = client.request('GetSceneCollectionList')['sceneCollections']
    client.request('SetCurrentSceneCollection' if COLLECTION in collections else 'CreateSceneCollection', {'sceneCollectionName': COLLECTION})
    client.request('SetProfileParameter', {'parameterCategory': 'Output', 'parameterName': 'Mode', 'parameterValue': 'Simple'})
    parameters = {'RecRB': 'true', 'RecRBTime': str(settings.seconds), 'RecRBSize': str(max(512, min(16384, settings.seconds * 8))),
                  'FilePath': str(Path(settings.folder).resolve()), 'RecFormat2': settings.container,
                  'RecQuality': settings.quality, 'RecTracks': str(7 | sum(1 << (i + 3) for i in range(len(settings.extra_audio))))}
    # Null restores OBS's hardware-aware default after a previous explicit selection.
    parameters['RecEncoder'] = settings.encoder or None
    for name, value in parameters.items():
        client.request('SetProfileParameter', {'parameterCategory': 'SimpleOutput', 'parameterName': name, 'parameterValue': value})
    # OBS only constructs the replay output when a profile is activated.
    # Setting RecRB in a live profile does not rebuild that output.
    alternate = next((name for name in profiles if name != PROFILE), None)
    temporary = alternate is None
    if temporary:
        alternate = 'Clipper activation ' + uuid.uuid4().hex[:8]
        client.request('CreateProfile', {'profileName': alternate})
    else:
        client.request('SetCurrentProfile', {'profileName': alternate})
    client.request('SetCurrentProfile', {'profileName': PROFILE})
    if temporary: client.request('RemoveProfile', {'profileName': alternate})
    client.request('SetVideoSettings', {'fpsNumerator': settings.fps, 'fpsDenominator': 1,
        'baseWidth': settings.width, 'baseHeight': settings.height, 'outputWidth': settings.width, 'outputHeight': settings.height})
    scenes = client.request('GetSceneList')['scenes']
    if not any(scene['sceneName'] == SCENE for scene in scenes): client.request('CreateScene', {'sceneName': SCENE})
    existing = {item['inputName'] for item in client.request('GetInputList')['inputs']}
    video_name = 'Clipper Game' if settings.capture_mode == 'game' else 'Clipper Display'
    video_kind = 'game_capture' if settings.capture_mode == 'game' else 'monitor_capture'
    video_settings = {'capture_mode': 'any_fullscreen'} if settings.capture_mode == 'game' else {}
    specs = [(video_name, video_kind, video_settings)]
    # Keep both device selectors available even when their tracks are muted.
    specs.append(('Clipper Desktop Audio', 'wasapi_output_capture', {'device_id': 'default'}))
    specs.append(('Clipper Microphone', 'wasapi_input_capture', {'device_id': 'default'}))
    for i, source in enumerate(settings.extra_audio, 1):
        name = f'Clipper Extra {i} {source.kind}'
        kind = 'wasapi_output_capture' if source.kind == 'output' else 'wasapi_input_capture'
        specs.append((name, kind, {'device_id': source.device}))
    for name, kind, values in specs:
        if name not in existing:
            client.request('CreateInput', {'sceneName': SCENE, 'inputName': name, 'inputKind': kind, 'inputSettings': values})
    # Existing inputs can outlive their scene items after a user edits the scene.
    # Reattach only missing items instead of assuming CreateInput ran this time.
    items = client.request('GetSceneItemList', {'sceneName': SCENE}).get('sceneItems', [])
    attached = {item.get('sourceName'): item for item in items}
    for name, _, _ in specs:
        if name not in attached:
            client.request('CreateSceneItem', {'sceneName': SCENE, 'sourceName': name, 'sceneItemEnabled': True})
        elif not attached[name].get('sceneItemEnabled', True):
            client.request('SetSceneItemEnabled', {'sceneName': SCENE, 'sceneItemId': attached[name]['sceneItemId'], 'sceneItemEnabled': True})
    other_name = 'Clipper Display' if settings.capture_mode == 'game' else 'Clipper Game'
    if other_name in attached and attached[other_name].get('sceneItemEnabled', True):
        client.request('SetSceneItemEnabled', {'sceneName': SCENE, 'sceneItemId': attached[other_name]['sceneItemId'], 'sceneItemEnabled': False})
    if settings.capture_mode == 'display':
        _ensure_display_selected(client)
    else:
        client.request('SetInputSettings', {'inputName': video_name, 'inputSettings': video_settings, 'overlay': True})
    display_item = client.request('GetSceneItemId', {'sceneName': SCENE, 'sourceName': video_name})['sceneItemId']
    client.request('SetSceneItemTransform', {'sceneName': SCENE, 'sceneItemId': display_item,
        'sceneItemTransform': {'positionX': 0, 'positionY': 0, 'boundsType': 'OBS_BOUNDS_SCALE_INNER', 'boundsWidth': settings.width, 'boundsHeight': settings.height}})
    configured = existing | {spec[0] for spec in specs}
    for name, enabled in [('Clipper Desktop Audio', settings.desktop_audio), ('Clipper Microphone', settings.microphone)]:
        if name in configured: client.request('SetInputMute', {'inputName': name, 'inputMuted': not enabled})
    for name, gain in [('Clipper Desktop Audio', settings.desktop_gain), ('Clipper Microphone', settings.microphone_gain)]:
        if name in configured: client.request('SetInputVolume', {'inputName': name, 'inputVolumeMul': gain})
    def route(name, track):
        tracks = {str(i): i in (1, track) for i in range(1, 7)}
        client.request('SetInputAudioTracks', {'inputName': name, 'inputAudioTracks': tracks})
    route('Clipper Desktop Audio', 2); route('Clipper Microphone', 3)
    active_extras = set()
    for i, source in enumerate(settings.extra_audio, 1):
        name = f'Clipper Extra {i} {source.kind}'; active_extras.add(name)
        client.request('SetInputSettings', {'inputName': name, 'inputSettings': {'device_id': source.device}, 'overlay': True})
        client.request('SetInputMute', {'inputName': name, 'inputMuted': False})
        client.request('SetInputVolume', {'inputName': name, 'inputVolumeMul': source.gain})
        route(name, i + 3)
    # Switching kind or removing a slot must not leave an old source audible.
    for name in existing:
        if name.startswith('Clipper Extra ') and name not in active_extras:
            client.request('SetInputMute', {'inputName': name, 'inputMuted': True})
    # Do not double the default OBS desktop/microphone sources in our scene collection.
    for name in client.request('GetSpecialInputs').values():
        if name: client.request('SetInputMute', {'inputName': name, 'inputMuted': True})
    client.request('SetCurrentProgramScene', {'sceneName': SCENE})


def _ensure_display_selected(client):
    """Keep a valid selection, otherwise select a real monitor instead of OBS's placeholder."""
    name = 'Clipper Display'
    items = client.request('GetInputPropertiesListPropertyItems',
        {'inputName': name, 'propertyName': 'monitor_id'}).get('propertyItems', [])
    available = [item.get('itemValue') for item in items
                 if item.get('itemEnabled', True) and item.get('itemValue') not in (None, '', 'DUMMY')]
    if not available:
        raise OBSError('OBS nenašlo žádný dostupný displej. Zkontroluj zdroj obrazovky v OBS.')
    current = client.request('GetInputSettings', {'inputName': name}).get('inputSettings', {}).get('monitor_id')
    if current not in available:
        client.request('SetInputSettings', {'inputName': name, 'inputSettings': {'monitor_id': available[0]}, 'overlay': True})

DEVICE_PROPERTIES = {
    'Clipper Display': 'monitor_id',
    'Clipper Desktop Audio': 'device_id',
    'Clipper Microphone': 'device_id',
}

def device_options(client):
    existing = {item['inputName'] for item in client.request('GetInputList')['inputs']}
    result = {}
    for name, prop in DEVICE_PROPERTIES.items():
        if name not in existing: continue
        options = client.request('GetInputPropertiesListPropertyItems', {'inputName': name, 'propertyName': prop})['propertyItems']
        current = client.request('GetInputSettings', {'inputName': name}).get('inputSettings', {}).get(prop)
        result[name] = {'property': prop, 'items': options, 'current': current}
    return result

def set_devices(client, choices):
    for name, value in choices.items():
        if name not in DEVICE_PROPERTIES: raise ValueError('Unknown capture input')
        client.request('SetInputSettings', {'inputName': name, 'inputSettings': {DEVICE_PROPERTIES[name]: value}, 'overlay': True})
