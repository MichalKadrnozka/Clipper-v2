# Clipper remaster

Clipper is a replay-clipping and video-library desktop application. **This project is still in development:** Windows is the primary target, but the Windows capture path, packaging, shortcuts, and startup integration have not yet been tested on a real Windows machine. Linux capture still needs broader hardware testing, and Wayland shortcut activation needs interactive end-to-end verification.

The current code provides a library grouping originals, trims and exports; tags, thumbnails and legacy metadata import; an editor with playback, trim points and per-track audio levels; size-limited exports; and replay-buffer control through OBS Studio. On Linux there is also a GPU Screen Recorder adapter. Both backends need the corresponding recorder installed; Clipper does not yet bundle OBS.

The desktop interface is split into **Knihovna**, **Nahrávání**, and **Nastavení**. On Linux, choose OBS Studio or GPU Screen Recorder in the recording tab. Hover over a card for a silent video preview of its saved trim range. For formats that Qt cannot play directly, a short temporary preview is generated; if that fails, the thumbnail stays visible. Select a clip to see its versions and actions, or double-click it to open the editor. The right-click menu provides tag selection, copying files or exports, and batch deletion of exports or originals that have a retained trim.

The legacy import supports both the old top-level metadata maps and the later per-clip format, including trim ranges, tags, track volumes and track names. It matches files by name in the chosen folder and leaves the original configuration untouched.

## Run from source

Install Python 3.10+, FFmpeg with `ffprobe` and H.264 encoding, and OBS Studio 28+ (or GPU Screen Recorder on Linux). Create and activate a virtual environment, then run:

```sh
python -m pip install -e .
python -m clipper
```

Use “Zkontrolovat aplikaci…” in Nastavení to check FFmpeg, encoder availability, recorder startup and the OBS WebSocket connection. Choose the clips folder in Knihovna. On Windows, enable the OBS WebSocket server and enter its password in Nahrávání. The experimental setup action creates and activates a separate `Clipper Capture` profile and scene, configures the replay buffer and creates screen and audio sources. The recording setup offers display capture or fullscreen game capture, two standard audio sources and up to three additional input/output devices, each recorded to a separate track alongside the compatibility mix. Extra track labels are stored in the Clipper library and follow trims. The source selector can choose available devices. Fullscreen game capture requires a compatible game and OBS hook; check the preview for the game you intend to record. Setup refuses to switch profiles while an OBS output is active. OBS startup, the app's login startup, password storage using Windows DPAPI, and global hotkeys are opt-in.

On Linux, the system shortcuts button asks the desktop portal to register shortcuts. It creates a per-user desktop entry for the application identity. Support depends on the desktop environment and portal. GPU Screen Recorder must be compatible with the system libraries and graphics driver.

When a replay is saved in the selected clips folder, Clipper names it after the active window, as in the original application. Window detection uses the Windows foreground window or, on Linux, `hyprctl`, `kdotool`, or `xdotool` depending on the desktop; if no title is available, it uses `Desktop`. The saved file is left under its original name if safe renaming is unavailable or OBS saves it outside the selected clips folder.

## Build and test

```sh
python -m unittest discover -s tests -v
```

`scripts/build-windows.ps1` builds a Windows directory using PyInstaller and bundles the FFmpeg executables found on PATH. The GitHub Actions workflow is configured to run tests on Windows and Linux, build both packages, check the wheel's icons and open and close each packaged main window; it has not been executed in this workspace. On Linux, `scripts/build-linux.sh` creates `dist/Linux/Clipper`, which uses FFmpeg from PATH and requires OBS or GPU Screen Recorder separately; the whole output directory must be kept together. The Linux package passed its dependency and main-window smoke tests locally. A Windows directory build is available at `dist/Clipper`; its packaged dependency and main-window smoke tests and selected video playback tests passed under Wine. This does not validate real Windows hardware, audio or OBS capture. Copy the whole directory, including `_internal`, to run it.

## Media behavior

Trim copies the video stream without re-encoding. For a selection starting after zero, use MP4 or MOV: Matroska cannot reliably hide the earlier reference frames required for decoding. For MP4/MOV, the presentation edit list limits the selected endpoint while retaining reordered reference packets for decoding. Audio packet boundaries can still produce small timing differences; other containers may extend past the selected end. Audio tracks with changed volume are re-encoded, while unmodified tracks are copied. Export uses two-pass H.264, mixes the chosen audio tracks and verifies the file against the requested decimal-MB limit. It can reduce resolution to fit small targets. Output is written to a temporary file first so a failed or cancelled operation leaves the destination intact. The processing button can cancel a running trim or export.

For AV1 files, Qt's distributed decoder may not provide software AV1 decoding. The editor therefore generates a seekable H.264 preview in the app's cache, with a nominal 2 GB limit; the source file is still used for trims and exports. The first preview can take time to generate. Preview plays independent audio tracks together and applies their individual levels. For older files with a pre-mixed first track, select the mix option to avoid hearing it twice; imported legacy edits and new captures made with the dedicated Clipper profile remember this automatically. Other files are treated as independent tracks unless the first track is explicitly named Mix. Linux GPU Screen Recorder saves the configured audio source names and mix status with each replay, even when recording settings change before the library processes the notification. For amplification above 1×, a temporary mixed-audio preview is rendered in the background; the editor reports preparation while preview volume remains limited to 1×. Rendering can take time for long clips and uses temporary disk space.

OBS saves are confirmed by the `ReplayBufferSaved` event. While a save is being confirmed, Clipper currently rejects another recording command and reports that it was not performed; it does not queue a delayed replay as though it captured the original keypress. After confirmation, naming and optional metadata lookup run separately, so they do not delay the next request. Rapid consecutive saves before OBS confirms the first remain a limitation to resolve.

## Remaining verification

An isolated OBS 32.1 test saved a replay with a compatibility mix and three independently routed audio tracks. Three synthetic tones were used to verify that the mix contained all sources and each individual track contained only its own tone. The Windows capture inputs were substituted with Linux test sources, so this verifies OBS routing, not WASAPI device capture. The headless test OBS process crashed during signal-driven shutdown; that shutdown path has not been validated. On one Wayland/Intel machine, GPU Screen Recorder 5.13.4 saved an actual 4K replay with three audio streams; its trim, compressed export and editor playback were also checked. That test used temporary compatible FFmpeg libraries because the installed recorder was linked against unavailable libraries, so it does not prove the installed package works without repair. Tests also cover audio-track adjustment, metadata migration, thumbnails and AV1 preview. Windows capture and desktop integration, long-running operation, and other drivers still need end-to-end verification. Do not rely on a development build for irreplaceable footage.
