#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python_bin="${CLIPPER_PYTHON:-python3}"
if [[ "${CLIPPER_SKIP_INSTALL:-0}" != 1 ]]; then
    "$python_bin" -m pip install -e ".[linux-hotkeys]" pyinstaller
fi
"$python_bin" -m PyInstaller --noconfirm --clean --windowed --name Clipper \
    --paths "$PWD" --add-data "$PWD/clipper/assets:clipper/assets" --distpath dist/Linux --workpath build/linux \
    --specpath build/linux scripts/launch.py
cp LINUX-README.txt dist/Linux/Clipper/CTI-ME.txt
mkdir -p dist/Linux/Clipper/licence
cp third_party_licenses/{GPL-3,Qt,PyQt6-sip}.txt dist/Linux/Clipper/licence/
