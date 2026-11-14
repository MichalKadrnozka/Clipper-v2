"""Wayland global shortcuts via xdg-desktop-portal."""
import asyncio
import uuid
from collections.abc import Mapping
from PyQt6.QtCore import QThread, pyqtSignal
from .hotkeys import parse_hotkey
from .linux_identity import APP_ID, ensure_desktop_entry

DEFAULT_BINDINGS = {'save': 'F10', 'toggle': 'F9'}
DESCRIPTIONS = {
    'save': 'Uložit klip',
    'toggle': 'Zapnout nebo vypnout replay buffer',
}
PORTAL_MODIFIERS = ((0x0002, 'CTRL'), (0x0001, 'ALT'), (0x0004, 'SHIFT'), (0x0008, 'LOGO'))
PORTAL_KEYS = {
    0x1B: 'Escape',
    0x20: 'space',
    0x21: 'Prior',
    0x22: 'Next',
    0x23: 'End',
    0x24: 'Home',
    0x2D: 'Insert',
    0x2E: 'Delete',
}


def portal_trigger(text):
    """Translate the UI hotkey syntax to an XDG shortcuts-spec trigger."""
    modifiers, code = parse_hotkey(text)
    if code in PORTAL_KEYS:
        key = PORTAL_KEYS[code]
    elif 0x70 <= code <= 0x87:
        key = f'F{code - 0x70 + 1}'
    elif 0x41 <= code <= 0x5A:
        key = chr(code).lower()
    elif 0x30 <= code <= 0x39:
        key = chr(code)
    else:
        raise ValueError(f'Unsupported portal key code: {code}')
    parts = [name for flag, name in PORTAL_MODIFIERS if modifiers & flag]
    parts.append(key)
    return '+'.join(parts)


class PortalHotkeys(QThread):
    activated = pyqtSignal(str)
    error = pyqtSignal(str)
    bound = pyqtSignal()

    def __init__(self, bindings=None, parent=None):
        # Keep the historical PortalHotkeys(parent) call working while also
        # accepting the same (bindings, parent) convention as WindowsHotkeys.
        if bindings is not None and not isinstance(bindings, Mapping):
            if parent is not None:
                raise TypeError('Specify bindings before parent')
            parent, bindings = bindings, None
        super().__init__(parent)
        self.bindings = dict(DEFAULT_BINDINGS if bindings is None else bindings)
        self.triggers = {name: portal_trigger(key) for name, key in self.bindings.items()}

    def run(self):
        try: asyncio.run(self._run())
        except Exception as exc: self.error.emit('Globální zkratky nejsou dostupné: ' + str(exc))

    async def _run(self):
        from dbus_next import Message, MessageType, Variant, BusType
        from dbus_next.aio import MessageBus
        ensure_desktop_entry()
        bus = await asyncio.wait_for(MessageBus(bus_type=BusType.SESSION).connect(), timeout=5)
        interface = 'org.freedesktop.portal.GlobalShortcuts'
        pending = {}; received = {}; session = None
        def handle(message):
            if message.message_type != MessageType.SIGNAL: return
            if message.interface == 'org.freedesktop.portal.Request' and message.member == 'Response':
                future = pending.pop(message.path, None)
                if future and not future.done(): future.set_result(message.body)
                else: received[message.path] = message.body
            if message.interface == interface and message.member == 'Activated' and len(message.body) >= 2 and message.body[0] == session:
                self.activated.emit(str(message.body[1]))
        bus.add_message_handler(handle)
        async def call(message):
            reply = await asyncio.wait_for(bus.call(message), timeout=5)
            if reply.message_type == MessageType.ERROR: raise RuntimeError(reply.body[0] if reply.body else reply.error_name)
            return reply.body
        async def response(path):
            if path in received: result = received.pop(path)
            else:
                future = asyncio.get_running_loop().create_future(); pending[path] = future
                deadline = asyncio.get_running_loop().time() + 120
                while not future.done():
                    if self.isInterruptionRequested():
                        pending.pop(path, None); future.cancel(); raise RuntimeError('Nastavení zkratek bylo ukončeno.')
                    if asyncio.get_running_loop().time() >= deadline:
                        pending.pop(path, None); future.cancel(); raise RuntimeError('Portál zkratek neodpověděl.')
                    await asyncio.wait([future], timeout=.2)
                result = future.result()
            if result[0] != 0: raise RuntimeError('Nastavení zkratek bylo odmítnuto nebo zrušeno.')
            return result[1]
        try:
            # New portals require host applications to associate their bus
            # connection with an installed desktop entry before any portal call.
            registration = await asyncio.wait_for(bus.call(Message(destination='org.freedesktop.portal.Desktop', path='/org/freedesktop/portal/desktop',
                interface='org.freedesktop.host.portal.Registry', member='Register', signature='sa{sv}', body=[APP_ID, {}])), timeout=5)
            if registration.message_type == MessageType.ERROR and registration.error_name not in ('org.freedesktop.DBus.Error.UnknownMethod', 'org.freedesktop.DBus.Error.UnknownInterface'):
                raise RuntimeError(registration.body[0] if registration.body else registration.error_name)
            for rule in ("type='signal',interface='org.freedesktop.portal.Request',member='Response'", f"type='signal',interface='{interface}',member='Activated'"):
                await call(Message(destination='org.freedesktop.DBus', path='/org/freedesktop/DBus', interface='org.freedesktop.DBus', member='AddMatch', signature='s', body=[rule]))
            token = uuid.uuid4().hex
            body = await call(Message(destination='org.freedesktop.portal.Desktop', path='/org/freedesktop/portal/desktop', interface=interface,
                member='CreateSession', signature='a{sv}', body=[{'handle_token': Variant('s', 'c'+token), 'session_handle_token': Variant('s', 's'+token)}]))
            session = (await response(body[0]))['session_handle'].value
            shortcuts = [
                [name, {
                    'description': Variant('s', DESCRIPTIONS.get(name, name)),
                    'preferred_trigger': Variant('s', self.triggers[name]),
                }]
                for name in self.bindings
            ]
            body = await call(Message(destination='org.freedesktop.portal.Desktop', path='/org/freedesktop/portal/desktop', interface=interface,
                member='BindShortcuts', signature='oa(sa{sv})sa{sv}', body=[session, shortcuts, '', {'handle_token': Variant('s', 'b'+token)}]))
            bound = await response(body[0])
            shortcuts_result = bound.get('shortcuts')
            ids = {item[0] for item in shortcuts_result.value} if shortcuts_result else set()
            if not set(self.bindings).issubset(ids):
                raise RuntimeError('Systém nepřiřadil všechny požadované zkratky.')
            self.bound.emit()
            while not self.isInterruptionRequested(): await asyncio.sleep(.2)
            await call(Message(destination='org.freedesktop.portal.Desktop', path=session, interface='org.freedesktop.portal.Session', member='Close'))
        finally:
            bus.disconnect()
