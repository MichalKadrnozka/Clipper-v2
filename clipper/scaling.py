"""UI scale is applied before QApplication initializes Qt's screen handling."""
import math
import os
import sqlite3
from contextlib import closing
from pathlib import Path


def data_directory():
    return Path(os.environ.get('APPDATA') or os.environ.get('XDG_DATA_HOME') or Path.home() / '.local' / 'share') / 'Clipper'


def valid_scale(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and .5 <= number <= 2 else None
    except (TypeError, ValueError):
        return None


def apply_saved_scale(database=None):
    """Respect an explicit Qt environment override; ignore missing/corrupt settings."""
    if 'QT_SCALE_FACTOR' in os.environ:
        return
    database = Path(database) if database is not None else data_directory() / 'library.sqlite3'
    if not database.is_file():
        return
    try:
        with closing(sqlite3.connect(database)) as db:
            row = db.execute("SELECT value FROM settings WHERE key = 'ui_scale'").fetchone()
        scale = valid_scale(row[0]) if row else None
    except (sqlite3.Error, OSError):
        return
    if scale is not None:
        os.environ['QT_SCALE_FACTOR'] = str(scale)
