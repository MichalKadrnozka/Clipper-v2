import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from PyQt6.QtWidgets import QApplication
from clipper.audio_sources_ui import ExtraAudioEditor

class ExtraAudioEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])
    def test_preserves_custom_device_when_options_arrive(self):
        editor = ExtraAudioEditor([{'name':'Discord', 'kind':'output', 'device':'dev1', 'gain':.7}])
        self.assertEqual(editor.values()[0]['device'], 'dev1')
        editor.set_devices({'Clipper Desktop Audio': {'items': [
            {'itemName':'Discord output', 'itemValue':'dev1', 'itemEnabled':True},
            {'itemName':'Unavailable', 'itemValue':'bad', 'itemEnabled':False}]}})
        self.assertEqual(editor.values(), [{'name':'Discord', 'kind':'output', 'device':'dev1', 'gain':.7}])
        self.assertEqual(editor.rows[0][3].findData('bad'), -1)
    def test_reorders_selected_slots_by_visible_order(self):
        editor = ExtraAudioEditor()
        editor.rows[2][0].setChecked(True); editor.rows[2][1].setText('Mic')
        editor.rows[2][2].setCurrentIndex(1)
        self.assertEqual(editor.values(), [{'name':'Mic', 'kind':'input', 'device':'default', 'gain':1.0}])
