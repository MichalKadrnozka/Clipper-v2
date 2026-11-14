# Clipper

Clipper is a dark/orange, keyboard-friendly replay-clipping and video-library desktop application for **Windows and Linux**. It is a multiplatform remaster of the original school project, with non-destructive editing, independent audio tracks, OBS support and a native Qt interface.

## What is included

- **Replay recording:** OBS Studio on Windows and Linux, plus GPU Screen Recorder on Linux. Start/stop the replay buffer, save a clip, use global shortcuts and see a live screen/OBS preview and clear recording status.
- **GSR audio:** a usable default output on a fresh installation, selectable PulseAudio/PipeWire devices, custom track names, independent 0–150 % levels and track ordering. Names and levels are carried into the editor metadata; video is not re-encoded after recording.
- **Library:** responsive cards, silent hover previews, version grouping, tags and colors, search and match highlighting, date-aware ordering, multi-selection, clipboard actions, safe deletion and a details/actions panel.
- **Editor:** Qt Multimedia playback, frame stepping, speed, persistent master volume, per-track waveforms and independent levels, accurate IN/OUT controls and autoplay from the saved IN point. Exported files can open in a restricted playback-only mode.
- **Processing:** lossless video trims with appropriate audio handling, two-pass compressed exports, saved size presets/preferences, progress and cancellation. Outputs are committed atomically so a failure or cancellation does not replace an existing destination.
- **Compatibility:** seekable H.264 previews for unsupported codecs and synchronized independent-track audio. Files with a pre-mixed first track can be marked accordingly.
- **Desktop integration:** optional tray controls, start on login, automatic replay activation, Windows DPAPI password storage and saved window geometry/scale.
- **Migration:** imports old clips, tags, trims, track names/volumes, recording configuration, hotkeys, master volume, export preference, startup preference and window geometry without changing the original `config.json`.

The interface is split into **Nahrávání**, **Knihovna** and **Nastavení**, and opens in the library like the original. Select a clip to see versions and actions, or double-click it to open the editor. Right-click offers the complete batch, tag, export, copy and deletion menu. `Ctrl+F` focuses library search, `Escape` clears selection, and `I`/`O` set IN/OUT in the editor.

## Run from source

Install Python 3.10+, FFmpeg with `ffprobe` and H.264 encoding, and OBS Studio 28+ (or GPU Screen Recorder on Linux). Create and activate a virtual environment, then run:

```sh
python -m pip install -e .
python -m clipper
```

To also install the optional Linux `evdev` backend for global shortcuts:

```sh
python -m pip install -e '.[linux-hotkeys]'
python -m clipper
```

On Windows the standard installation already includes everything needed by the OBS integration. Choose the clips folder in Knihovna/Nastavení and use “Zkontrolovat aplikaci…” to check FFmpeg, encoder availability, recorder startup and the OBS WebSocket connection.

### Recording setup

On Windows, enable the OBS WebSocket server and enter its password in Nahrávání. “Nastavit OBS…” creates and activates a separate **Clipper Capture** profile and scene, configures the replay buffer and creates screen/game and audio sources. It refuses to switch profiles while an OBS output is active. Display capture or fullscreen game capture, two standard sources and up to three extra audio devices are supported. Existing device selections are preserved when refreshing the lists. OBS startup, application startup, password storage and global hotkeys are opt-in.

On Linux, select GPU Screen Recorder or OBS Studio. GSR offers independent recording tracks plus the compatibility mix. “Aktualizovat dostupná zařízení” refreshes PulseAudio/PipeWire devices asynchronously. Changes to recording settings are saved immediately; changing settings while recording offers a buffer restart. GPU Screen Recorder must be compatible with the system libraries and graphics driver.

Linux global shortcuts can use the desktop **Global Shortcuts portal** with custom triggers, or the optional **evdev** fallback where the portal is unavailable. The portal creates a per-user desktop identity; support depends on the desktop environment. evdev may require read permission for `/dev/input/event*`.

Saved replays are confirmed by the recorder/OBS event, named after the active window where supported, and then imported with their audio metadata. Additional quick OBS saves are serialized in a short queue instead of being silently rejected. Because OBS processes them after the current save, the queue is not presented as a guarantee that it captured the exact earlier keypress moment. Clipper waits for pending saves during shutdown, with an explicit timeout warning if the recorder does not finish.

## Media behavior

Trim copies the video stream without re-encoding. For a selection starting after zero, use MP4 or MOV: Matroska cannot reliably hide the earlier reference frames required for decoding. Audio tracks with changed levels are re-encoded; compatible unchanged tracks are copied. Incompatible audio (for example Vorbis in MKV exported to MP4) is converted only where required. MP4/MOV presentation metadata limits the selected endpoint.

Export uses two-pass H.264, mixes chosen audio tracks and verifies the actual file against the requested decimal-MB limit. It can reduce resolution for small targets and remembers the last requested size. Processing is cancellable and temporary files are cleaned up.

Qt can play H.264 directly; otherwise a cached preview or a short hovering proxy is generated. AV1 editor previews have a nominal 2 GB cache limit. Stalled preview/audio preparation has a watchdog and a retry action. Independent tracks play together with their levels; enable “První stopa je mix ostatních stop” for legacy pre-mixed captures to avoid hearing doubled audio. Master or track amplification above 1× uses a temporary mixed-audio render.

## Build and test

```sh
python -m unittest discover -s tests -v
```

Tests include real FFmpeg operations, multitrack playback, media timing, codec/container compatibility, cancellation, metadata migration, recorder lifecycle, preview cleanup, OBS transport and interface behavior. `QT_QPA_PLATFORM=offscreen` can be used on a headless machine.

`scripts/build-windows.ps1` builds a Windows directory using PyInstaller and bundles FFmpeg executables found on PATH. On Linux, `scripts/build-linux.sh` creates `dist/Linux/Clipper`; its FFmpeg comes from PATH and OBS or GPU Screen Recorder remains a separate dependency. Keep the whole output directory together. Packaged dependency and main-window self-tests are available through `--self-test` and `--self-test-ui` and are also run by CI.

## Remaining verification

Real Windows capture/WASAPI devices, native Windows global shortcuts, OBS hook behavior on games and every Linux compositor/driver combination cannot be exhaustively verified by unit tests. The local suite and packaged smoke tests do not replace an end-to-end test on the target hardware. Before relying on Clipper for irreplaceable footage, save a test replay and verify its video, audio tracks and playback on the intended machine.
