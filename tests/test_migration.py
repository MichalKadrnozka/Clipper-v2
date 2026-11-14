import json
import tempfile
import unittest
from pathlib import Path
from clipper.library import Library
from clipper.migration import import_legacy

class MigrationTests(unittest.TestCase):
    def test_imports_recording_hotkeys_and_application_preferences(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); config = root / 'old.json'
            config.write_text(json.dumps({'clips': {}, 'volume': 125, 'export_mode': 0, 'export_custom_val': 75,
                'startup_record': True, 'window_geometry': '0102', 'window_maximized': True,
                'recording': {'display': 1, 'resolution': '1920x1080', 'fps': 120, 'codec': 'H264',
                    'format': 'MKV', 'crf': 2, 'time_str': '2 minutes', 'hotkey_save': 'KEY_PAGEUP',
                    'hotkey_toggle': 'KEY_LEFTCTRL+KEY_P', 'audio_tracks': [
                        {'device': 'Default Output (Mix)', 'name': 'Hra', 'volume': 80},
                        {'device': 'Input: usb-microphone', 'name': 'Mic', 'volume': 100}]}}))
            db = Library(root / 'db.sqlite'); import_legacy(db, config, root)
            self.assertEqual(db.setting('master_volume'), '125')
            self.assertEqual(db.setting('export_size'), '75')
            self.assertEqual(db.setting('save_key'), 'PageUp')
            self.assertEqual(db.setting('toggle_key'), 'Ctrl+P')
            self.assertEqual(db.setting('linux_auto'), '1')
            self.assertEqual(db.setting('window_geometry'), '0102')
            self.assertEqual(db.setting('seconds'), '120')
            self.assertEqual(json.loads(db.setting('gsr_audio_tracks'))[0], {'device': 'default_output', 'name': 'Hra', 'gain': .8})
            db.close()

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
