import tempfile
import unittest
from clipper.obs import OBSError
from clipper.obs_setup import configure_windows, OBSSettings

class FakeOBS:
    def __init__(self, active=False): self.calls=[]; self.active=active
    def request(self, name, data=None):
        self.calls.append((name, data))
        if name == 'GetSceneItemList':
            return {'sceneItems': [{'sourceName': data['inputName']} for call, data in self.calls if call == 'CreateInput']}
        if name in ('GetStreamStatus', 'GetRecordStatus', 'GetReplayBufferStatus'): return {'outputActive': self.active}
        return {'GetProfileList': {'profiles': ['Untitled']}, 'GetSceneCollectionList': {'sceneCollections': []},
                'GetSceneList': {'scenes': []}, 'GetInputList': {'inputs': []}, 'GetSceneItemId': {'sceneItemId': 1}, 'GetSpecialInputs': {},
                'GetInputPropertiesListPropertyItems': {'propertyItems': [{'itemValue': 'DUMMY', 'itemEnabled': False}, {'itemValue': 'DISPLAY1', 'itemEnabled': True}]},
                'GetInputSettings': {'inputSettings': {}}}.get(name, {})

class OBSSetupTests(unittest.TestCase):
    def test_dedicated_profile_and_multitrack_sources(self):
        with tempfile.TemporaryDirectory() as folder:
            client = FakeOBS(); configure_windows(client, OBSSettings(folder))
            created = [data['inputKind'] for name, data in client.calls if name == 'CreateInput']
            self.assertEqual(created, ['monitor_capture', 'wasapi_output_capture', 'wasapi_input_capture'])
            self.assertIn(('CreateProfile', {'profileName': 'Clipper Capture'}), client.calls)
            self.assertEqual(len([x for x in client.calls if x[0] == 'SetInputAudioTracks']), 2)
            self.assertIn(('SetInputSettings', {'inputName': 'Clipper Display', 'inputSettings': {'monitor_id': 'DISPLAY1'}, 'overlay': True}), client.calls)
            self.assertIn(('SetProfileParameter', {'parameterCategory': 'Output', 'parameterName': 'Mode', 'parameterValue': 'Simple'}), client.calls)
            self.assertIn(('SetProfileParameter', {'parameterCategory': 'SimpleOutput', 'parameterName': 'RecEncoder', 'parameterValue': None}), client.calls)
    def test_refuses_to_switch_profile_with_active_output(self):
        with tempfile.TemporaryDirectory() as folder:
            client = FakeOBS(True)
            with self.assertRaises(OBSError): configure_windows(client, OBSSettings(folder))
            self.assertEqual([call[0] for call in client.calls], ['GetStreamStatus'])

class DeviceTests(unittest.TestCase):
    def test_query_and_update_known_devices(self):
        from clipper.obs_setup import device_options, set_devices
        class Devices:
            def __init__(self): self.calls=[]
            def request(self, name, data=None):
                self.calls.append((name, data))
                if name == 'GetInputList': return {'inputs': [{'inputName': 'Clipper Display'}]}
                if name == 'GetInputPropertiesListPropertyItems': return {'propertyItems': [{'itemName': 'Screen', 'itemValue': 'id', 'itemEnabled': True}]}
                if name == 'GetInputSettings': return {'inputSettings': {'monitor_id':'id'}}
                return {}
        client=Devices(); values=device_options(client)
        self.assertEqual(values['Clipper Display']['current'], 'id')
        set_devices(client, {'Clipper Display':'id'})
        self.assertEqual(client.calls[-1][1]['inputSettings'], {'monitor_id':'id'})
        with self.assertRaises(ValueError): set_devices(client, {'Unrelated source':'id'})

class DisplaySelectionTests(unittest.TestCase):
    def test_existing_valid_display_is_preserved(self):
        from clipper.obs_setup import _ensure_display_selected
        client = FakeOBS()
        original = client.request
        def request(name, data=None):
            if name == 'GetInputSettings': return {'inputSettings': {'monitor_id': 'DISPLAY1'}}
            return original(name, data)
        client.request = request
        _ensure_display_selected(client)
        self.assertFalse(any(name == 'SetInputSettings' for name, _ in client.calls))

    def test_missing_display_reports_error(self):
        from clipper.obs_setup import _ensure_display_selected
        client = FakeOBS()
        client.request = lambda name, data=None: {'propertyItems': [{'itemValue': 'DUMMY', 'itemEnabled': False}]}
        with self.assertRaisesRegex(OBSError, 'displej'):
            _ensure_display_selected(client)

class SceneRecoveryTests(unittest.TestCase):
    def test_missing_scene_items_are_reattached(self):
        class DetachedOBS(FakeOBS):
            def request(self, name, data=None):
                if name == 'GetInputList':
                    return {'inputs': [{'inputName': name} for name in ('Clipper Display', 'Clipper Desktop Audio', 'Clipper Microphone')]}
                if name == 'GetSceneItemList': return {'sceneItems': []}
                return super().request(name, data)
        with tempfile.TemporaryDirectory() as folder:
            client = DetachedOBS(); configure_windows(client, OBSSettings(folder))
            attached = [data['sourceName'] for name, data in client.calls if name == 'CreateSceneItem']
            self.assertEqual(attached, ['Clipper Display', 'Clipper Desktop Audio', 'Clipper Microphone'])

class GameCaptureTests(unittest.TestCase):
    def test_game_mode_uses_fullscreen_capture_and_disables_display(self):
        class ExistingDisplay(FakeOBS):
            def request(self, name, data=None):
                if name == 'GetSceneItemList':
                    return {'sceneItems': [{'sourceName': 'Clipper Display', 'sceneItemId': 42, 'sceneItemEnabled': True}]}
                return super().request(name, data)
        with tempfile.TemporaryDirectory() as folder:
            client = ExistingDisplay(); configure_windows(client, OBSSettings(folder, capture_mode='game'))
            created = [data for name, data in client.calls if name == 'CreateInput']
            self.assertIn({'sceneName': 'Clipper Screen', 'inputName': 'Clipper Game', 'inputKind': 'game_capture',
                           'inputSettings': {'capture_mode': 'any_fullscreen'}}, created)
            self.assertIn(('SetSceneItemEnabled', {'sceneName': 'Clipper Screen', 'sceneItemId': 42, 'sceneItemEnabled': False}), client.calls)
            self.assertFalse(any(name == 'GetInputPropertiesListPropertyItems' for name, data in client.calls))

class ExtraAudioTests(unittest.TestCase):
    def test_extra_sources_use_independent_tracks_and_mute_stale_inputs(self):
        from clipper.obs_setup import ExtraAudioSource
        class Existing(FakeOBS):
            def request(self, name, data=None):
                if name == 'GetInputList': return {'inputs': [{'inputName': 'Clipper Extra 1 input'}]}
                return super().request(name, data)
        with tempfile.TemporaryDirectory() as folder:
            client = Existing()
            settings = OBSSettings(folder, extra_audio=(ExtraAudioSource('Chat', 'output', 'device-id', .7),))
            configure_windows(client, settings)
            self.assertIn(('SetProfileParameter', {'parameterCategory': 'SimpleOutput', 'parameterName': 'RecTracks', 'parameterValue': '15'}), client.calls)
            self.assertIn(('SetInputMute', {'inputName': 'Clipper Extra 1 input', 'inputMuted': True}), client.calls)
            routes = [data for name, data in client.calls if name == 'SetInputAudioTracks']
            route = next(value['inputAudioTracks'] for value in routes if value['inputName'] == 'Clipper Extra 1 output')
            self.assertEqual([key for key, enabled in route.items() if enabled], ['1', '4'])
            desktop = next(value['inputAudioTracks'] for value in routes if value['inputName'] == 'Clipper Desktop Audio')
            self.assertFalse(desktop['4'])
    def test_rejects_more_tracks_than_obs_can_record(self):
        from clipper.obs_setup import ExtraAudioSource
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(OBSError):
                OBSSettings(folder, extra_audio=tuple(ExtraAudioSource(str(i), 'input') for i in range(4))).validate()
