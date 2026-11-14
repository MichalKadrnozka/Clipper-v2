"""Controls for GSR recording inputs and optional Windows OBS audio sources."""
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget


class _RecordingAudioRow(QWidget):
    def __init__(self, editor, data):
        super().__init__(editor)
        layout = QHBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0)
        self.name = QLineEdit(str(data.get('name', ''))); self.name.setPlaceholderText('Název stopy'); self.name.setMinimumWidth(150); self.name.setCursorPosition(0)
        self.device = QComboBox(); self.device.setMinimumWidth(190)
        self.gain = QSpinBox(); self.gain.setRange(0, 150); self.gain.setSuffix(' %')
        try: self.gain.setValue(round(float(data.get('gain', 1)) * 100))
        except (TypeError, ValueError): self.gain.setValue(100)
        self.up = QPushButton('↑'); self.up.setToolTip('Posunout stopu nahoru')
        self.down = QPushButton('↓'); self.down.setToolTip('Posunout stopu dolů')
        self.remove = QPushButton('×'); self.remove.setToolTip('Odebrat stopu')
        for widget in (self.name, self.device, self.gain, self.up, self.down, self.remove): layout.addWidget(widget)
        self.name.textChanged.connect(editor.changed)
        self.device.currentIndexChanged.connect(editor.changed)
        self.gain.valueChanged.connect(editor.changed)
        self.up.clicked.connect(lambda: editor.move_track(self, -1))
        self.down.clicked.connect(lambda: editor.move_track(self, 1))
        self.remove.clicked.connect(lambda: editor.remove_track(self))


class RecordingAudioEditor(QWidget):
    """Ordered GSR audio tracks; saved custom devices survive device refreshes."""
    changed = pyqtSignal()
    def __init__(self, saved=(), parent=None):
        super().__init__(parent)
        self.devices = []
        self.rows = []
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout = QVBoxLayout(); self.rows_layout.setContentsMargins(0, 0, 0, 0); layout.addLayout(self.rows_layout)
        self.add_button = QPushButton('Přidat audio stopu'); self.add_button.clicked.connect(self.add_track); layout.addWidget(self.add_button)
        for data in saved or ():
            self.add_track(data)

    def add_track(self, data=None):
        if isinstance(data, str):
            data = {'device': data}
        elif not isinstance(data, dict):
            data = {'device': getattr(data, 'device', 'default_output'),
                    'name': getattr(data, 'name', ''), 'gain': getattr(data, 'gain', 1.0)}
        row = _RecordingAudioRow(self, data)
        self.rows.append(row); self.rows_layout.addWidget(row)
        self._fill_device(row.device, data.get('device', 'default_output'))
        self._update_buttons()
        return row

    def remove_track(self, row):
        if row not in self.rows:
            return
        self.rows.remove(row); self.rows_layout.removeWidget(row); row.deleteLater()
        self._update_buttons()

    def move_track(self, row, offset):
        old = self.rows.index(row); new = old + offset
        if new not in range(len(self.rows)):
            return
        self.rows.pop(old); self.rows.insert(new, row)
        self.rows_layout.removeWidget(row); self.rows_layout.insertWidget(new, row)
        self._update_buttons()

    def _update_buttons(self):
        for index, row in enumerate(self.rows):
            row.up.setEnabled(index > 0); row.down.setEnabled(index + 1 < len(self.rows))
            row.name.setPlaceholderText(f'Stopa {index + 1}')
        self.changed.emit()

    def _fill_device(self, combo, selected):
        selected = str(selected or 'default_output')
        combo.blockSignals(True); combo.clear()
        aliases = {'default_output': 'Výchozí výstup (mix)', 'default_input': 'Výchozí vstup (mikrofon)'}
        for device in self.devices:
            combo.addItem(aliases.get(device, device), device)
        index = combo.findData(selected)
        if index < 0:
            combo.addItem(f'Uložené zařízení: {selected}', selected); index = combo.count() - 1
        combo.setCurrentIndex(index); combo.blockSignals(False)

    def set_devices(self, devices):
        self.devices = list(dict.fromkeys(str(device).strip() for device in devices if str(device).strip()))
        for row in self.rows:
            self._fill_device(row.device, row.device.currentData())
        self.changed.emit()

    def values(self):
        return [{'device': row.device.currentData() or 'default_output', 'name': row.name.text().strip() or f'Stopa {index + 1}',
                 'gain': row.gain.value() / 100}
                for index, row in enumerate(self.rows)]


class ExtraAudioEditor(QWidget):
    def __init__(self, saved=(), parent=None):
        super().__init__(parent)
        self.devices = {'output': [], 'input': []}
        self.rows = []
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0)
        for index in range(3):
            data = saved[index] if index < len(saved) and isinstance(saved[index], dict) else {}
            row = QHBoxLayout(); layout.addLayout(row)
            enabled = QCheckBox(f'Zdroj {index + 1}'); enabled.setChecked(bool(data))
            enabled.setToolTip('Vybrané zdroje budou zařazeny postupně za základní stopy.')
            title = QLineEdit(str(data.get('name', f'Zdroj {index + 1}'))); title.setPlaceholderText('Název'); title.setMinimumWidth(110)
            kind = QComboBox(); kind.addItem('Výstup', 'output'); kind.addItem('Vstup', 'input')
            kind.setCurrentIndex(max(0, kind.findData(data.get('kind', 'output'))))
            device = QComboBox(); device.setMinimumWidth(170)
            gain = QSpinBox(); gain.setRange(0, 200); gain.setSuffix(' %')
            try: gain.setValue(round(float(data.get('gain', 1)) * 100))
            except (TypeError, ValueError): gain.setValue(100)
            self.rows.append((enabled, title, kind, device, gain))
            for widget in (enabled, title, kind, device, gain): row.addWidget(widget)
            self._fill_device(device, kind.currentData(), data.get('device', 'default'))
            kind.currentIndexChanged.connect(lambda _, combo=device, typ=kind: self._fill_device(combo, typ.currentData(), 'default'))

    def _fill_device(self, combo, kind, selected):
        combo.clear(); combo.addItem('Výchozí zařízení', 'default')
        for item in self.devices.get(kind, []):
            value = item.get('itemValue')
            if item.get('itemEnabled', True) and isinstance(value, str) and value and value != 'default':
                combo.addItem(str(item.get('itemName') or value), value)
        index = combo.findData(selected)
        if index < 0 and selected and selected != 'default':
            combo.addItem(f'Uložené zařízení: {selected}', selected); index = combo.count() - 1
        combo.setCurrentIndex(max(0, index))

    def set_devices(self, options):
        self.devices = {'output': options.get('Clipper Desktop Audio', {}).get('items', []),
                        'input': options.get('Clipper Microphone', {}).get('items', [])}
        for _, _, kind, combo, _ in self.rows:
            self._fill_device(combo, kind.currentData(), combo.currentData())

    def values(self):
        return [{'name': title.text().strip() or f'Zdroj {i + 1}', 'kind': kind.currentData(),
                 'device': device.currentData(), 'gain': gain.value() / 100}
                for i, (enabled, title, kind, device, gain) in enumerate(self.rows) if enabled.isChecked()]
