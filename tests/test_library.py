import tempfile
import unittest
from pathlib import Path
from clipper.library import Library

class LibraryTests(unittest.TestCase):
    def test_metadata_persists_and_searches(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            clip = p / 'video.mp4'
            clip.touch()
            db = Library(p / 'library.db')
            db.add_tag('Funny')
            db.tag_clip(clip, 'Funny')
            db.set_setting('folder', str(p))
            db.close()
            db = Library(p / 'library.db')
            self.assertEqual(db.scan(p, 'funny'), [clip])
            self.assertEqual(db.setting('folder'), str(p))
            db.delete_tag('Funny')
            self.assertEqual(db.tags_for(clip), [])
            self.assertEqual(db.scan(p, 'funny'), [])
            db.close()

class VersionReplacementTests(unittest.TestCase):
    def test_replacing_output_removes_stale_metadata_and_keeps_source_tags(self):
        with tempfile.TemporaryDirectory() as d:
            db = Library(Path(d) / 'library.db'); output = Path(d) / 'out.mp4'
            db.add_tag('old'); db.add_tag('new')
            db.tag_clip(output, 'old'); db.save_edit(output, {'in': .8})
            db.set_version(output, 'unrelated', 'trim')
            db.replace_version_metadata(output, 'game', 'export', {}, ['new'])
            self.assertEqual(db.tags_for(output), ['new'])
            self.assertEqual(db.edit_for(output), {})
            self.assertEqual(db.versions()[str(output.resolve())], ('game', 'export'))
            db.close()

    def test_failure_rolls_back_old_tags_and_version(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as d:
            db = Library(Path(d) / 'library.db'); output = Path(d) / 'out.mp4'
            db.add_tag('old'); db.tag_clip(output, 'old'); db.set_version(output, 'old', 'trim')
            db.db.execute("CREATE TRIGGER fail_edit BEFORE INSERT ON edits BEGIN SELECT RAISE(ABORT, 'failed'); END")
            with self.assertRaises(sqlite3.IntegrityError):
                db.replace_version_metadata(output, 'new', 'export', {}, [])
            self.assertEqual(db.tags_for(output), ['old'])
            self.assertEqual(db.versions()[str(output.resolve())], ('old', 'trim'))
            db.close()

class GroupTests(unittest.TestCase):
    def test_legacy_versions_and_duplicate_originals_are_preserved(self):
        from clipper.library import group_clips
        groups = group_clips([Path('a.mp4'), Path('a.mkv'), Path('a_trim.mp4'), Path('a_export.mp4'), Path('other.mp4')])
        self.assertEqual(len(groups['a']['original']), 2)
        self.assertEqual(groups['a']['trim'], [Path('a_trim.mp4')])
        self.assertEqual(groups['a']['export'], [Path('a_export.mp4')])
        self.assertEqual(len(groups), 2)

    def test_existing_tag_color_is_preserved_when_assigning(self):
        with tempfile.TemporaryDirectory() as d:
            db = Library(Path(d) / 'library.db')
            db.add_tag('Funny', '#123456')
            db.ensure_tag('funny')
            self.assertEqual(db.tags(), [('Funny', '#123456')])
            db.close()
