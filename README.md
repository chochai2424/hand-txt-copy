# hand-txt-copy

[![tests](https://github.com/chochai2424/hand-txt-copy/actions/workflows/tests.yml/badge.svg)](https://github.com/chochai2424/hand-txt-copy/actions/workflows/tests.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Hands-free, webcam-driven **copy/paste** for an AOI (Automated Optical Inspection) station where
there is no room for a mouse or keyboard. The operator points at the screen with a finger to move a
cursor, **pinch-drags** to select a region, and gestures to **copy** (both the image *and* OCR'd
text) and **paste** into whatever application is focused.

Target platform: **Windows 11**, **Python 3.11+**.

## How it works

Per camera frame: `camera` → `hand_tracker` (MediaPipe landmarks) → `gestures` (debounced) →
`app` state machine → effects (`cursor`, `selection`, `capture` + `ocr` → `clipboard`, `paste`) →
`overlay`. See `CLAUDE.md` for the architecture and module boundaries.

### Gestures

| Gesture | Action |
|---------|--------|
| Point (index finger) | Move the on-screen cursor |
| Pinch (thumb + index) and drag | Draw the selection rectangle |
| Release the pinch | Copy the region: image **and** OCR text → clipboard |
| Open palm | Paste into the focused app (Ctrl+V) |
| Fist | Cancel / reset |

## Setup (PowerShell)

Use **Python 3.11 or 3.12** — MediaPipe has no wheels for 3.13 yet, and installing on 3.13 fails
with `metadata-generation-failed`. Check your version with `py -0p`.

```powershell
py -3.12 -m venv .venv                 # 3.11 also fine; NOT 3.13
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-dev.txt   # for tests/lint
```

**Tesseract OCR** is a separate native install (the `pytesseract` package is only a wrapper).
Install the UB-Mannheim Windows build, then set its path in `config/default.yaml`:

```yaml
ocr:
  tesseract_cmd: "C:\\Program Files\\Tesseract-OCR\\tesseract.exe"
```

If Tesseract is absent, copying still works — only the image is placed on the clipboard.

**Hand model:** on first run the app downloads Google's `hand_landmarker.task` (~7.5 MB) to
`models/` (needs internet once). To pre-stage it offline, download it from
`https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task`
and set `hand_tracker.model_path` in the config to its location.

## Run

```powershell
python scripts\check_camera.py          # find your webcam index
python -m hand_txt_copy                  # run with config/default.yaml
python -m hand_txt_copy --config my.yaml # run with a custom config
```

### Monitor window (video-call style)

A visible window for setup, demos, and checking that the camera and gestures work — double-click
`console-hand-txt-copy.bat`, or:

```powershell
python -m hand_txt_copy --console
```

It shows a large dashboard (status, live gesture, FPS, gesture legend) with a small **webcam
self-view** in the corner, like a video call. **Click the self-view (or press `F`)** to expand it
to **fullscreen** with the full HUD — hand skeleton, fingertip cursor, pinch distance, the cursor
active region, and status. Press `Esc` or click again to return.

This window is for monitoring only; it does not copy/paste. For the hands-free tool that actually
copies over other apps, use `start-hand-txt-copy.bat` (the transparent overlay).

## Run in the background (double-click, no console)

For the station, use the launcher scripts instead of a terminal:

| File | Action |
|------|--------|
| **`start-hand-txt-copy.bat`** | Double-click to start the app **silently in the background** (uses `pythonw.exe`, so no console window). The overlay floats over all windows and never steals keyboard focus, so the operator drives it with gestures. Automatically uses `config\station.yaml` if it exists, else `config\default.yaml`. |
| **`stop-hand-txt-copy.bat`** | Stop the background app (only kills *this* app's process). |
| **`install-autostart.bat`** | Make it launch automatically at login (adds a shortcut to the Windows Startup folder). |
| **`uninstall-autostart.bat`** | Remove the auto-start shortcut. |

The launcher needs the runtime venv at `.venv\` (Python 3.11/3.12 — see Setup); if it's missing,
`start-hand-txt-copy.bat` explains how to create it.

**Troubleshooting a silent launch:** because there is no console, startup problems are written to
`logs\hand-txt-copy.log` (and config errors to `logs\startup-error.log`). To see errors live during
setup, run it in a terminal instead: `python -m hand_txt_copy`.

### Running indicator

Since the app runs with no console, it shows that it is alive two ways:
- **On-screen status dot** (top-right of the overlay), pulsing so it reads as live even when idle:
  🟢 green = hand tracking, 🟡 amber = running but no hand in view, 🔴 red = no camera frames.
- **System-tray icon** whose color mirrors the dot; hover for status, and right-click → **Quit
  hand-txt-copy** to stop it with a mouse (handy for admins, since operators have no keyboard).

## Calibrate (per station)

Launch the live tuning UI, adjust the sliders while watching the hand skeleton and the pinch
distance, then save a per-station config (leaving `config/default.yaml` untouched):

```powershell
python -m hand_txt_copy --calibrate                       # saves to config\station.yaml
python -m hand_txt_copy --calibrate --out config\line3.yaml
```

In the window:
- **Sliders** tune the pinch on/off thresholds, cursor active-region margins, and the One-Euro
  smoothing (`min_cutoff`, `beta`), plus the debounce frame count.
- **Cursor preview**: a red ring marks the raw fingertip target and a blue dot (with a motion
  trail) marks the One-Euro-smoothed cursor — the gap between them is *lag*, and a trembling dot
  under a steady hand is *jitter*. It uses the real monitor size, so the feel matches the app;
  raise `min_cutoff`/`beta` to cut lag, lower them to cut jitter.
- Press **`a`** while holding a pinch to auto-set the pinch thresholds from your hand.
- Press **`s`** to save, **`q`**/`Esc` to quit.

Then run with the tuned file: `python -m hand_txt_copy --config config\station.yaml`.

## Test

```powershell
pytest                                   # all tests (pure logic + mocked clipboard)
pytest tests\test_gestures.py -k pinch   # a single test
ruff check src tests
black src tests
```

## Calibration notes

- **Camera index**: `scripts/check_camera.py` lists which indices open; set `camera.index`.
- **Cursor feel**: tune `cursor.margin_*` (active region) and the One-Euro filter
  (`one_euro_min_cutoff`, `one_euro_beta`) — larger values reduce lag, smaller values reduce jitter.
- **Pinch sensitivity**: `gestures.pinch_on_distance` / `pinch_off_distance` (hysteresis).
- **Monitor**: `screen.monitor` selects which display to capture and map the cursor onto.

## Status

Working prototype (end-to-end: camera → gesture → select → copy → paste). Not yet hardened for
24/7 line use — see the "Open items" in the project plan.
