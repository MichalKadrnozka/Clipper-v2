import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from PyQt6.QtWidgets import QApplication
from clipper.audio_sources_ui import ExtraAudioEditor, RecordingAudioEditor

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


class RecordingAudioEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def test_loads_names_gains_and_preserves_custom_devices(self):
        editor = RecordingAudioEditor([
            {'device': 'desktop.monitor', 'name': 'Hra', 'gain': .65},
            {'device': 'old-usb-mic', 'name': 'Mikrofon', 'gain': 1.5}])
        editor.set_devices(['default_output', 'default_input', 'desktop.monitor'])
        editor.set_devices(['default_output', 'default_input', 'desktop.monitor'])
        self.assertEqual(editor.values(), [
            {'device': 'desktop.monitor', 'name': 'Hra', 'gain': .65},
            {'device': 'old-usb-mic', 'name': 'Mikrofon', 'gain': 1.5}])
        self.assertEqual(editor.rows[1].device.count(), 4)

    def test_add_rename_reorder_remove_and_default_name(self):
        editor = RecordingAudioEditor([{'device': 'one', 'name': 'První'}])
        editor.set_devices(['default_output', 'one', 'two'])
        editor.add_button.click(); editor.rows[1].device.setCurrentIndex(editor.rows[1].device.findData('two'))
        editor.rows[1].name.setText('Druhá'); editor.rows[1].gain.setValue(125)
        editor.rows[1].up.click()
        self.assertEqual(editor.values(), [
            {'device': 'two', 'name': 'Druhá', 'gain': 1.25},
            {'device': 'one', 'name': 'První', 'gain': 1.0}])
        editor.rows[1].name.setText('')
        self.assertEqual(editor.values()[1]['name'], 'Stopa 2')
        editor.rows[0].remove.click()
        self.assertEqual(editor.values(), [{'device': 'one', 'name': 'Stopa 1', 'gain': 1.0}])

    def test_gain_control_is_limited_to_150_percent(self):
        editor = RecordingAudioEditor([{'device': 'desktop', 'gain': 3}])
        self.assertEqual(editor.values()[0]['gain'], 1.5)
        editor.rows[0].gain.setValue(-1)
        self.assertEqual(editor.values()[0]['gain'], 0)
