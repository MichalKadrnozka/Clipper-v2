"""Controls for optional Windows OBS audio capture sources."""
from PyQt6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLineEdit, QSpinBox, QVBoxLayout, QWidget


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
