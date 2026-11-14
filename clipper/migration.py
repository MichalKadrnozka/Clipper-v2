"""Import metadata from the original school project's JSON file."""
import json
from pathlib import Path
from .scaling import valid_scale

def import_legacy(library, config_path, folder):
    with open(config_path, encoding='utf-8') as stream:
        data = json.load(stream)
    if not isinstance(data, dict) or not isinstance(data.get('clips', {}), dict):
        raise ValueError('This is not a supported Clipper config.json')
    # Older releases stored these maps at the top level. The original loader
    # merged them into clips, with top-level values taking precedence.
    clips = {path: dict(metadata) for path, metadata in data.get('clips', {}).items()
             if isinstance(path, str) and isinstance(metadata, dict)}
    for old_key, field in (('trims', 'trims'), ('video_tags', 'tags'), ('track_volumes', 'track_volumes')):
        values = data.get(old_key, {})
        if not isinstance(values, dict): continue
        for path, value in values.items():
            if isinstance(path, str): clips.setdefault(path, {})[field] = value
    scale = valid_scale(data.get('ui_scale'))
    if scale is not None: library.set_setting('ui_scale', str(scale))
    recording = data.get('recording', {})
    if isinstance(recording, dict):
        for old_key, new_key in (('fps', 'fps'), ('display', 'display_index')):
            value = recording.get(old_key)
            if isinstance(value, (int, float)): library.set_setting(new_key, str(int(value)))
        codec, container = str(recording.get('codec', '')).casefold(), str(recording.get('format', '')).casefold()
        if codec in ('h264', 'hevc', 'av1'): library.set_setting('codec', codec)
        if container in ('mp4', 'mkv'): library.set_setting('format', container)
        resolution = str(recording.get('resolution', ''))
        if resolution and resolution.casefold() != 'native': library.set_setting('resolution', resolution)
        if isinstance(recording.get('crf'), (int, float)):
            quality = 'ultra' if recording['crf'] <= 1 else 'very_high' if recording['crf'] <= 2 else 'high' if recording['crf'] <= 4 else 'medium'
            library.set_setting('quality', quality)
        duration_text = str(recording.get('time_str', ''))
        parts = duration_text.split()
        try:
            amount = int(parts[0]); seconds = amount * (60 if len(parts) > 1 and parts[1].startswith('minute') else 1)
            if 1 <= seconds <= 3600: library.set_setting('seconds', str(seconds))
        except (ValueError, IndexError): pass
        tracks = []
        for track in recording.get('audio_tracks', []):
            if not isinstance(track, dict) or not track.get('device'): continue
            device = str(track['device']).removeprefix('Output: ').removeprefix('Input: ')
            aliases = {'Default Output (Mix)': 'default_output', 'Default Input (Microphone)': 'default_input'}
            device = aliases.get(device, device)
            try: gain = max(0., min(1.5, float(track.get('volume', 100)) / 100))
            except (TypeError, ValueError): gain = 1.
            tracks.append({'device': device, 'name': str(track.get('name', 'Stopa')), 'gain': gain})
        if tracks: library.set_setting('gsr_audio_tracks', json.dumps(tracks, ensure_ascii=False))
        for old_key, new_key in (('hotkey_save', 'save_key'), ('hotkey_toggle', 'toggle_key')):
            value = recording.get(old_key)
            if isinstance(value, str) and value:
                tokens = value.split('+'); converted = []
                for token in tokens:
                    token = token.removeprefix('KEY_')
                    converted.append({'LEFTCTRL': 'Ctrl', 'RIGHTCTRL': 'Ctrl', 'LEFTSHIFT': 'Shift', 'RIGHTSHIFT': 'Shift',
                        'LEFTALT': 'Alt', 'RIGHTALT': 'Alt', 'LEFTMETA': 'Win', 'RIGHTMETA': 'Win',
                        'PAGEUP': 'PageUp', 'PAGEDOWN': 'PageDown', 'ESC': 'Escape'}.get(token, token.capitalize()))
                library.set_setting(new_key, '+'.join(converted))
    for old_key, new_key in (('startup_record', 'linux_auto'), ('startup_record', 'auto_buffer')):
        if isinstance(data.get(old_key), bool): library.set_setting(new_key, '1' if data[old_key] else '0')
    if isinstance(data.get('volume'), (int, float)):
        library.set_setting('master_volume', str(max(0, min(150, data['volume']))))
    export_mode = data.get('export_mode')
    export_size = export_mode if export_mode in (10, 20, 50) else data.get('export_custom_val', 10)
    if isinstance(export_size, (int, float)) and export_size > 0: library.set_setting('export_size', str(export_size))
    if isinstance(data.get('window_geometry'), str): library.set_setting('window_geometry', data['window_geometry'])
    if isinstance(data.get('window_maximized'), bool): library.set_setting('window_maximized', '1' if data['window_maximized'] else '0')
    for tag in data.get('tags', []):
        if isinstance(tag, dict) and tag.get('name'):
            library.add_tag(str(tag['name']), str(tag.get('color', '#ff7300')))
    imported, missing = 0, 0
    for old_path, metadata in clips.items():
        # Legacy paths can originate on another OS; use the filename under the selected folder.
        name = old_path.replace('\\', '/').rsplit('/', 1)[-1]
        candidate = Path(folder) / name
        if not candidate.is_file():
            original = Path(old_path)
            if not original.is_file(): missing += 1; continue
            candidate = original
        for tag in metadata.get('tags', []):
            if not isinstance(tag, dict) or not tag.get('name'): continue
            library.add_tag(str(tag['name']), str(tag.get('color', '#ff7300')))
            library.tag_clip(candidate, str(tag['name']))
        edit = library.edit_for(candidate)
        selection = metadata.get('trims')
        if isinstance(selection, dict):
            if 'in' in selection: edit['in'] = selection['in']
            if 'out' in selection: edit['out'] = selection['out']
        volumes = metadata.get('track_volumes')
        if isinstance(volumes, dict):
            edit['volumes'] = {str(k): float(v)/100 for k, v in volumes.items() if isinstance(v, (int, float))}
        names = metadata.get('track_names')
        if isinstance(names, list):
            edit['track_names'] = [name if isinstance(name, str) else '' for name in names]
        edit.setdefault('mix_first', True)
        library.save_edit(candidate, edit)
        imported += 1
    return imported, missing
