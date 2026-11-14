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
