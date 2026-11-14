import json
import unittest
from unittest.mock import patch
from clipper.obs import OBSClient, OBSError, authentication

class FakeWebSocket:
    def __init__(self): self.sent=[]; self.step=0
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def send(self, value): self.sent.append(json.loads(value))
    def recv(self, timeout=None):
        self.step += 1
        if self.step == 1: return json.dumps({'op': 0, 'd': {'rpcVersion': 1, 'authentication': {'salt': 'salt', 'challenge': 'challenge'}}})
        if self.step == 2: return json.dumps({'op': 2, 'd': {'negotiatedRpcVersion': 1}})
        return json.dumps({'op': 7, 'd': {'requestId': self.sent[-1]['d']['requestId'], 'requestStatus': {'result': True}, 'responseData': {'outputActive': True}}})

class OBSTests(unittest.TestCase):
    def test_authentication_and_request_protocol(self):
        ws = FakeWebSocket()
        with patch('websockets.sync.client.connect', return_value=ws):
            self.assertTrue(OBSClient(password='password').status())
        self.assertEqual(ws.sent[0]['d']['authentication'], authentication('password', 'salt', 'challenge'))
        self.assertEqual(ws.sent[1]['d']['requestType'], 'GetReplayBufferStatus')
    def test_failure_is_surfaced(self):
        with self.assertRaises(OBSError): OBSClient('ws://127.0.0.1:1', timeout=.1).status()
    def test_start_and_stop_are_idempotent(self):
        client = OBSClient()
        with patch.object(client, 'request', return_value={'outputActive': True}) as request:
            client.start(); self.assertEqual(request.call_count, 1)
        with patch.object(client, 'request', return_value={'outputActive': False}) as request:
            client.stop(); self.assertEqual(request.call_count, 1)

class SaveSocket(FakeWebSocket):
    def __init__(self, event_first=False, reject=False, timeout=False):
        super().__init__(); self.event_first=event_first; self.reject=reject; self.timeout=timeout
    def recv(self, timeout=None):
        self.step += 1
        if self.step == 1: return json.dumps({'op': 0, 'd': {'rpcVersion': 1}})
        if self.step == 2: return json.dumps({'op': 2, 'd': {'negotiatedRpcVersion': 1}})
        if self.timeout: raise TimeoutError()
        event = {'op': 5, 'd': {'eventType': 'ReplayBufferSaved', 'eventData': {'savedReplayPath': 'new.mkv'}}}
        response = {'op': 7, 'd': {'requestId': self.sent[-1]['d']['requestId'], 'requestStatus': {'result': not self.reject, 'code': 604, 'comment': 'unavailable'}}}
        is_event = self.step == (3 if self.event_first else 4)
        return json.dumps(event if is_event else response)

class SaveTests(unittest.TestCase):
    def test_save_waits_for_event_and_acknowledgment_in_either_order(self):
        for event_first in (False, True):
            ws = SaveSocket(event_first=event_first)
            with self.subTest(event_first=event_first), patch.object(OBSClient, 'status', side_effect=AssertionError('unnecessary status request')), patch('websockets.sync.client.connect', return_value=ws):
                self.assertEqual(OBSClient().save(), 'new.mkv')
                self.assertEqual(ws.sent[0]['d']['eventSubscriptions'], 64)
                self.assertEqual(ws.sent[1]['d']['requestType'], 'SaveReplayBuffer')
    def test_save_does_not_claim_success_on_timeout(self):
        ws = SaveSocket(timeout=True)
        with patch.object(OBSClient, 'status', return_value=True), patch('websockets.sync.client.connect', return_value=ws):
            with self.assertRaisesRegex(OBSError, 'did not confirm'): OBSClient().save(timeout=1)
    def test_save_rejects_error_even_if_event_arrives_first(self):
        ws = SaveSocket(event_first=True, reject=True)
        with patch.object(OBSClient, 'status', return_value=True), patch('websockets.sync.client.connect', return_value=ws):
            with self.assertRaisesRegex(OBSError, 'unavailable'): OBSClient().save()

class StateTests(unittest.TestCase):
    def test_start_waits_until_obs_reports_active(self):
        client = OBSClient()
        with patch.object(client, 'request', side_effect=[{'outputActive': False}, {}, {'outputActive': False}, {'outputActive': True}]), patch('clipper.obs.time.sleep'):
            client.start()
    def test_start_reports_failed_state_transition(self):
        client = OBSClient()
        with patch.object(client, 'request', side_effect=[{'outputActive': False}, {}]):
            with self.assertRaisesRegex(OBSError, 'did not confirm'): client.start(timeout=0)
