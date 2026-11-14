import asyncio
import importlib.util
import unittest
from types import SimpleNamespace
from unittest.mock import patch

@unittest.skipUnless(importlib.util.find_spec('dbus_next'), 'dbus-next unavailable')
class PortalTests(unittest.TestCase):
    def test_registers_identity_binds_shortcuts_and_filters_other_sessions(self):
        from dbus_next import MessageType, Variant
        from clipper.portal_hotkeys import PortalHotkeys
        class Bus:
            def __init__(self, *args, **kwargs): self.handler=None; self.calls=[]
            async def connect(self): return self
            def add_message_handler(self, handler): self.handler=handler
            def disconnect(self): pass
            async def call(self, message):
                self.calls.append(message)
                if message.member in ('CreateSession', 'BindShortcuts'):
                    path='/org/freedesktop/portal/desktop/request/test/' + message.member
                    value = {'session_handle':Variant('s','/org/freedesktop/portal/desktop/session/test/x')} if message.member=='CreateSession' else {'shortcuts':Variant('a(sa{sv})', [['save',{}],['toggle',{}]])}
                    self.handler(SimpleNamespace(message_type=MessageType.SIGNAL, interface='org.freedesktop.portal.Request', member='Response', path=path, body=[0,value]))
                    if message.member == 'BindShortcuts':
                        self.handler(SimpleNamespace(message_type=MessageType.SIGNAL, interface='org.freedesktop.portal.GlobalShortcuts', member='Activated', body=['/other','save',0,{}]))
                        self.handler(SimpleNamespace(message_type=MessageType.SIGNAL, interface='org.freedesktop.portal.GlobalShortcuts', member='Activated', body=['/org/freedesktop/portal/desktop/session/test/x','save',0,{}]))
                    return SimpleNamespace(message_type=MessageType.METHOD_RETURN,body=[path])
                return SimpleNamespace(message_type=MessageType.METHOD_RETURN,body=[])
        bus=Bus(); worker=PortalHotkeys(); hits=[]; worker.activated.connect(hits.append)
        with patch('clipper.portal_hotkeys.ensure_desktop_entry'), patch('dbus_next.aio.MessageBus', return_value=bus), patch.object(worker, 'isInterruptionRequested', return_value=True):
            asyncio.run(worker._run())
        self.assertEqual(hits,['save'])
        self.assertEqual([m.member for m in bus.calls if m.member in ('Register','CreateSession','BindShortcuts','Close')],['Register','CreateSession','BindShortcuts','Close'])
