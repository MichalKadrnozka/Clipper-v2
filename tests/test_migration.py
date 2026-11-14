import json
import tempfile
import unittest
from pathlib import Path
from clipper.library import Library
from clipper.migration import import_legacy

class MigrationTests(unittest.TestCase):
    def test_imports_tags_and_edits_from_other_machine_paths(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); clip = root/'game.mp4'; clip.touch()
            config = root/'old.json'; config.write_text(json.dumps({'ui_scale': 1.25, 'tags': [{'name': 'fun', 'color': '#112233'}], 'clips': {
                r'C:\old\game.mp4': {'tags': [{'name':'fun', 'color':'#112233'}], 'trims': {'in':.2, 'out':.8}, 'track_volumes': {'2': 150}, 'track_names': ['Mix', 'Game', 'Microphone']},
                r'C:\old\missing.mp4': {}}}))
            db = Library(root/'db.sqlite'); self.assertEqual(import_legacy(db, config, root), (1,1))
            self.assertEqual(db.tags_for(clip), ['fun']); self.assertEqual(db.edit_for(clip)['volumes']['2'], 1.5)
            self.assertTrue(db.edit_for(clip)['mix_first'])
            self.assertEqual(db.edit_for(clip)['track_names'], ['Mix', 'Game', 'Microphone'])
            self.assertEqual(db.setting('ui_scale'), '1.25')
            db.close()

    def test_imports_older_top_level_maps_and_preserves_other_edits(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); clip = root / 'game.mp4'; clip.touch(); key = '/old/game.mp4'
            config = root / 'old.json'
            config.write_text(json.dumps({'clips': {key: {'trims': {'in': .1, 'out': .9}}},
                'trims': {key: {'in': .3, 'out': .7}}, 'track_volumes': {key: {'2': 50}},
                'video_tags': {key: [{'name': 'win', 'color': '#112233'}]}}))
            db = Library(root / 'db.sqlite'); db.save_edit(clip, {'track_names': ['Mix', 'Game'], 'custom': 'keep'})
            self.assertEqual(import_legacy(db, config, root), (1, 0))
            edit = db.edit_for(clip)
            self.assertEqual((edit['in'], edit['out']), (.3, .7))
            self.assertEqual(edit['volumes'], {'2': .5})
            self.assertEqual(edit['track_names'], ['Mix', 'Game'])
            self.assertEqual(edit['custom'], 'keep')
            self.assertEqual(db.tags_for(clip), ['win']); db.close()
