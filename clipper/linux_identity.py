"""Register a per-user desktop identity for the global shortcuts portal."""
import os
from pathlib import Path
import sys

APP_ID = 'app.clipper.Remaster'

def ensure_desktop_entry(data_home=None):
    root = Path(data_home or os.environ.get('XDG_DATA_HOME') or Path.home() / '.local' / 'share')
    directory = root / 'applications'; directory.mkdir(parents=True, exist_ok=True)
    path = directory / (APP_ID + '.desktop')
    if path.exists(): return path
    exe = str(Path(sys.executable).resolve())
    # Desktop Entry Exec uses percent escapes and double-quoted arguments.
    escaped = exe.replace('%', '%%').replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$').replace('`', '\\`')
    arguments = '' if getattr(sys, 'frozen', False) else ' -m clipper'
    content = f'[Desktop Entry]\nType=Application\nName=Clipper\nExec="{escaped}"{arguments}\nTerminal=false\nCategories=AudioVideo;Video;\n'
    try:
        with path.open('x', encoding='utf-8') as stream: stream.write(content)
    except FileExistsError:
        pass
    return path

def set_login_start(enabled, data_home=None, config_home=None):
    root = Path(config_home or os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
    target = root / 'autostart' / (APP_ID + '.desktop')
    if enabled:
        source = ensure_desktop_entry(data_home)
        target.parent.mkdir(parents=True, exist_ok=True)
        content = source.read_text(encoding='utf-8')
        temporary = target.with_suffix('.tmp')
        try:
            temporary.write_text(content, encoding='utf-8'); temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    else:
        target.unlink(missing_ok=True)

def starts_on_login(config_home=None):
    root = Path(config_home or os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
    return (root / 'autostart' / (APP_ID + '.desktop')).is_file()
