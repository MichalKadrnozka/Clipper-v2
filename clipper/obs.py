"""OBS Studio WebSocket v5 replay-buffer transport.

Each call owns a short-lived connection. The backend never modifies an existing
OBS scene, profile or recording settings implicitly.
"""
from __future__ import annotations
import base64
import hashlib
import json
import time
import uuid
from urllib.parse import urlparse

class OBSError(RuntimeError):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code

def authentication(password: str, salt: str, challenge: str) -> str:
    secret = base64.b64encode(hashlib.sha256((password + salt).encode()).digest()).decode()
    return base64.b64encode(hashlib.sha256((secret + challenge).encode()).digest()).decode()

class OBSClient:
    def __init__(self, url='ws://127.0.0.1:4455', password='', timeout=5):
        parsed = urlparse(url)
        if parsed.scheme not in ('ws', 'wss') or not parsed.hostname:
            raise ValueError('Invalid OBS WebSocket URL')
        self.url, self.password, self.timeout = url, password, timeout

    def request(self, request_type, request_data=None):
        try:
            from websockets.sync.client import connect
        except ImportError as exc:
            raise OBSError('Install the websockets package (version 12 or newer).') from exc
        try:
            with connect(self.url, open_timeout=self.timeout, close_timeout=self.timeout, max_size=4*1024*1024) as ws:
                hello = json.loads(ws.recv(timeout=self.timeout))
                if hello.get('op') != 0:
                    raise OBSError('Invalid OBS greeting')
                identify = {'rpcVersion': 1, 'eventSubscriptions': 0}
                if 'authentication' in hello['d']:
                    auth = hello['d']['authentication']
                    identify['authentication'] = authentication(self.password, auth['salt'], auth['challenge'])
                ws.send(json.dumps({'op': 1, 'd': identify}))
                if json.loads(ws.recv(timeout=self.timeout)).get('op') != 2:
                    raise OBSError('OBS did not accept identification')
                request_id = str(uuid.uuid4())
                ws.send(json.dumps({'op': 6, 'd': {'requestType': request_type, 'requestId': request_id, 'requestData': request_data or {}}}))
                while True:
                    response = json.loads(ws.recv(timeout=self.timeout))
                    data = response.get('d', {})
                    if response.get('op') != 7 or data.get('requestId') != request_id:
                        continue
                    status = data.get('requestStatus', {})
                    if not status.get('result'):
                        raise OBSError(status.get('comment') or f"OBS request failed ({status.get('code', 'unknown')})", status.get('code'))
                    return data.get('responseData', {})
        except OBSError:
            raise
        except Exception as exc:
            raise OBSError(f'Unable to communicate with OBS: {exc}') from exc

    def status(self):
        return bool(self.request('GetReplayBufferStatus').get('outputActive'))

    def _wait_for_status(self, expected, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.status() == expected: return
            time.sleep(.2)
        raise OBSError('OBS did not confirm the replay buffer state change. Check the OBS log.')

    def start(self, timeout=15):
        if not self.status():
            self.request('StartReplayBuffer')
            self._wait_for_status(True, timeout)

    def stop(self, timeout=15):
        if self.status():
            self.request('StopReplayBuffer')
            self._wait_for_status(False, timeout)

    def toggle(self):
        if self.status():
            self.stop(); return False
        self.start(); return True

    def save(self, timeout=30):
        """Request a save and wait for OBS's saved event on the same connection."""
        # SaveReplayBuffer itself reports an inactive buffer. Avoid a separate
        # connection and status round trip before capturing the user's moment.
        try:
            from websockets.sync.client import connect
        except ImportError as exc:
            raise OBSError('Install the websockets package (version 12 or newer).') from exc
        try:
            with connect(self.url, open_timeout=self.timeout, close_timeout=self.timeout, max_size=4*1024*1024) as ws:
                hello = json.loads(ws.recv(timeout=self.timeout))
                if hello.get('op') != 0: raise OBSError('Invalid OBS greeting')
                identify = {'rpcVersion': 1, 'eventSubscriptions': 1 << 6}
                if 'authentication' in hello['d']:
                    auth = hello['d']['authentication']
                    identify['authentication'] = authentication(self.password, auth['salt'], auth['challenge'])
                ws.send(json.dumps({'op': 1, 'd': identify}))
                if json.loads(ws.recv(timeout=self.timeout)).get('op') != 2:
                    raise OBSError('OBS did not accept identification')
                request_id = str(uuid.uuid4())
                ws.send(json.dumps({'op': 6, 'd': {'requestType': 'SaveReplayBuffer', 'requestId': request_id, 'requestData': {}}}))
                deadline = time.monotonic() + timeout
                acknowledged = False; saved_path = ''
                while time.monotonic() < deadline:
                    try: message = json.loads(ws.recv(timeout=max(0.001, deadline - time.monotonic())))
                    except TimeoutError: break
                    data = message.get('d', {})
                    if message.get('op') == 7 and data.get('requestId') == request_id:
                        status = data.get('requestStatus', {})
                        if not status.get('result'):
                            raise OBSError(status.get('comment') or f"OBS request failed ({status.get('code', 'unknown')})", status.get('code'))
                        acknowledged = True
                    elif message.get('op') == 5 and data.get('eventType') == 'ReplayBufferSaved':
                        saved_path = data.get('eventData', {}).get('savedReplayPath') or ''
                    if acknowledged and saved_path: return saved_path
        except OBSError:
            raise
        except Exception as exc:
            raise OBSError(f'Unable to communicate with OBS: {exc}') from exc
        raise OBSError('OBS did not confirm that the replay was saved. Check its recording log and output directory.')
