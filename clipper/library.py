"""Persistent clip metadata and non-destructive folder discovery."""
from pathlib import Path
import json
import sqlite3

VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.mov', '.webm', '.avi'}

class Library:
    def __init__(self, database):
        self.db = sqlite3.connect(database)
        self.db.execute('PRAGMA foreign_keys = ON')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS tags (name TEXT PRIMARY KEY COLLATE NOCASE, color TEXT NOT NULL DEFAULT '#ff7300');
        CREATE TABLE IF NOT EXISTS clip_tags (path TEXT NOT NULL, tag TEXT NOT NULL COLLATE NOCASE REFERENCES tags(name) ON DELETE CASCADE, PRIMARY KEY(path, tag));
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS edits (path TEXT PRIMARY KEY, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS versions (path TEXT PRIMARY KEY, group_name TEXT NOT NULL, kind TEXT NOT NULL);
        ''')
        self.db.commit()

    def close(self):
        self.db.close()

    def set_setting(self, key, value):
        with self.db:
            self.db.execute('INSERT INTO settings VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, value))

    def setting(self, key, default=''):
        row = self.db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return row[0] if row else default

    def add_tag(self, name, color='#ff7300'):
        name = name.strip()
        if not name:
            raise ValueError('Tag cannot be empty')
        with self.db:
            self.db.execute('INSERT INTO tags(name,color) VALUES (?,?) ON CONFLICT(name) DO UPDATE SET color=excluded.color', (name, color))

    def ensure_tag(self, name):
        """Create a missing tag without changing an existing tag's color."""
        name = name.strip()
        if not name:
            raise ValueError('Tag cannot be empty')
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO tags(name) VALUES (?)', (name,))

    def tags(self):
        return self.db.execute('SELECT name, color FROM tags ORDER BY name').fetchall()

    def delete_tag(self, name):
        with self.db:
            self.db.execute('DELETE FROM tags WHERE name=?', (name,))

    def tag_clip(self, path, tag, enabled=True):
        self.tag_clips([path], tag, enabled)

    def tag_clips(self, paths, tag, enabled=True):
        rows = [(str(Path(path).resolve()), tag) for path in paths]
        if not rows: return
        with self.db:
            if enabled:
                self.db.executemany('INSERT OR IGNORE INTO clip_tags(path,tag) VALUES (?,?)', rows)
            else:
                self.db.executemany('DELETE FROM clip_tags WHERE path=? AND tag=?', rows)

    def tags_for(self, path):
        return [r[0] for r in self.db.execute('SELECT tag FROM clip_tags WHERE path=? ORDER BY tag', (str(Path(path).resolve()),))]

    def save_edit(self, path, data):
        with self.db:
            self.db.execute('INSERT INTO edits(path,data) VALUES (?,?) ON CONFLICT(path) DO UPDATE SET data=excluded.data', (str(Path(path).resolve()), json.dumps(data)))

    def edit_for(self, path):
        row = self.db.execute('SELECT data FROM edits WHERE path=?', (str(Path(path).resolve()),)).fetchone()
        return json.loads(row[0]) if row else {}

    def set_version(self, path, group_name, kind):
        if kind not in ('trim', 'export'):
            raise ValueError('Invalid version kind')
        with self.db:
            self.db.execute('INSERT INTO versions VALUES (?, ?, ?) ON CONFLICT(path) DO UPDATE SET group_name=excluded.group_name, kind=excluded.kind',
                            (str(Path(path).resolve()), group_name, kind))

    def replace_version_metadata(self, path, group_name, kind, edit, tags):
        """Replace stale metadata atomically when an output file is overwritten."""
        if kind not in ('trim', 'export'):
            raise ValueError('Invalid version kind')
        key = str(Path(path).resolve())
        with self.db:
            self.db.execute('DELETE FROM clip_tags WHERE path=?', (key,))
            self.db.execute('INSERT INTO versions VALUES (?, ?, ?) ON CONFLICT(path) DO UPDATE SET group_name=excluded.group_name, kind=excluded.kind', (key, group_name, kind))
            self.db.execute('INSERT INTO edits(path,data) VALUES (?,?) ON CONFLICT(path) DO UPDATE SET data=excluded.data', (key, json.dumps(edit)))
            for tag in tags:
                self.db.execute('INSERT OR IGNORE INTO clip_tags(path,tag) SELECT ?,name FROM tags WHERE name=?', (key, tag))

    def versions(self):
        return {path: (name, kind) for path, name, kind in self.db.execute('SELECT path, group_name, kind FROM versions')}

    def forget_paths(self, paths):
        with self.db:
            values = [(str(Path(path).resolve()),) for path in paths]
            self.db.executemany('DELETE FROM clip_tags WHERE path=?', values)
            self.db.executemany('DELETE FROM edits WHERE path=?', values)
            self.db.executemany('DELETE FROM versions WHERE path=?', values)

    def scan(self, folder, query=''):
        folder = Path(folder)
        if not folder.is_dir():
            return []
        query = query.casefold().strip()
        entries = []
        try:
            for path in folder.iterdir():
                try:
                    if path.is_file() and path.suffix.casefold() in VIDEO_EXTENSIONS:
                        entries.append((path.stat().st_mtime_ns, path))
                except OSError:
                    continue  # A recorder or another app may remove a file during discovery.
        except OSError:
            return []
        entries.sort(key=lambda entry: entry[0], reverse=True)
        return [p for _, p in entries if not query or query in p.name.casefold() or any(query in t.casefold() for t in self.tags_for(p))]

def group_clips(paths, versions=None):
    """Group the legacy original / _trim / _export convention without moving files.

    Multiple files of the same kind remain visible rather than silently losing
    one when two originals share a stem but have different extensions.
    """
    groups = {}
    versions = versions or {}
    for path in paths:
        path = Path(path)
        stem = path.stem
        kind = 'original'
        for suffix, version in (('_trim', 'trim'), ('_export', 'export')):
            if stem.casefold().endswith(suffix):
                stem, kind = stem[:-len(suffix)], version
                break
        mapped = versions.get(str(path.resolve()))
        if mapped and mapped[1] in ('trim', 'export'):
            stem, kind = mapped
        groups.setdefault(stem, {'original': [], 'trim': [], 'export': []})[kind].append(path)
    return groups
