import asyncio
import importlib.util
import unittest
from types import SimpleNamespace
from unittest.mock import patch


class PortalTriggerTests(unittest.TestCase):
    def test_converts_ui_shortcuts_to_xdg_trigger_names(self):
        from clipper.portal_hotkeys import portal_trigger

        self.assertEqual(portal_trigger('F10'), 'F10')
        self.assertEqual(portal_trigger('Ctrl+Shift+A'), 'CTRL+SHIFT+a')
        self.assertEqual(portal_trigger('Win+PageDown'), 'LOGO+Next')
        self.assertEqual(portal_trigger('Alt+Space'), 'ALT+space')
        self.assertEqual(portal_trigger('Escape'), 'Escape')


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
        bind = next(m for m in bus.calls if m.member == 'BindShortcuts')
        self.assertEqual(
            {item[0]: item[1]['preferred_trigger'].value for item in bind.body[1]},
            {'save': 'F10', 'toggle': 'F9'},
        )

        custom_bus = Bus()
        custom = PortalHotkeys(bindings={'save': 'Ctrl+Shift+A', 'toggle': 'Win+PageDown'})
        with patch('clipper.portal_hotkeys.ensure_desktop_entry'), patch('dbus_next.aio.MessageBus', return_value=custom_bus), patch.object(custom, 'isInterruptionRequested', return_value=True):
            asyncio.run(custom._run())
        bind = next(m for m in custom_bus.calls if m.member == 'BindShortcuts')
        self.assertEqual(
            {item[0]: item[1]['preferred_trigger'].value for item in bind.body[1]},
            {'save': 'CTRL+SHIFT+a', 'toggle': 'LOGO+Next'},
        )
