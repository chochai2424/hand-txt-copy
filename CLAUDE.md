# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`hand-txt-copy` is a hands-free, webcam-driven copy/paste tool for an AOI (Automated Optical
Inspection) manufacturing station where there is no room for a mouse or keyboard. The operator
controls an on-screen cursor with a finger, pinch-drags to select a screen region, and uses
gestures to copy (image + OCR'd text) and paste into the focused application.

Target platform is **Windows 11**. Language is **Python 3.11+**.

## Commands

Setup (PowerShell):
- `python -m venv .venv; .\.venv\Scripts\Activate.ps1`
- `pip install -r requirements.txt`
- Tesseract OCR must be installed separately (the `pytesseract` package is only a wrapper):
  install the UB-Mannheim Windows build and set its path in `config/default.yaml` (`ocr.tesseract_cmd`).

Run:
- `python -m hand_txt_copy` — start the app with `config/default.yaml`.
- `python -m hand_txt_copy --config path\to\config.yaml` — run with a specific config.
- `python -m hand_txt_copy --calibrate [--out config\station.yaml]` — live tuning UI; writes a
  per-station config (leaves `default.yaml` intact). See `calibration.py`.
- `python scripts/check_camera.py` — list/preview cameras to find the right index.

Background launch (station): `start-hand-txt-copy.bat` runs the app via `pythonw.exe` (no console)
and prefers `config/station.yaml` if present; `stop-hand-txt-copy.bat` stops it;
`install-autostart.bat` / `uninstall-autostart.bat` manage login auto-start. Silent-launch errors
go to `logs/hand-txt-copy.log` (and `logs/startup-error.log` for config errors), since there is no
console — `main()` in `__main__.py` wraps startup so failures are logged, not lost.

Test / quality:
- `pytest` — run all tests.
- `pytest tests/test_gestures.py -k pinch` — run a single test.
- `ruff check src tests` and `black src tests` — lint / format.

The package lives under `src/`, so tests and runs rely on the editable/`PYTHONPATH=src` layout
configured in `pyproject.toml` (`pytest` picks it up automatically via `pythonpath = ["src"]`).

## Architecture

The app is a single real-time loop orchestrated by a **state machine**; each concern is an isolated
module under `src/hand_txt_copy/` so the numeric logic (gestures, cursor mapping) is unit-testable
without a camera, screen, or clipboard.

Data flow per frame:
`camera.py` (threaded grab) → `hand_tracker.py` (MediaPipe landmarks) → `gestures.py`
(landmarks → debounced gesture) → `app.py` state machine → effects (`cursor.py`, `selection.py`,
`capture.py` + `ocr.py` → `clipboard.py`, `paste.py`) → `overlay.py` (visual feedback).

Key boundaries to preserve when editing:
- **Pure vs. impure:** `gestures.py`, `cursor.py`, and `selection.py` take plain numpy/number inputs
  and return values with no I/O — keep them side-effect-free so tests stay fast. All OS interaction
  (clipboard, screenshot, synthetic input, overlay, camera) lives behind `clipboard.py`,
  `capture.py`, `paste.py`, `overlay.py`, `camera.py`, `hand_tracker.py`.
- **State lives in the app, not the modules:** the copy/select/paste FSM is owned by `app.py`.
  Gesture modules report *what gesture is happening*; they do not decide *what it means*.
- **Windows clipboard holds multiple formats at once:** `clipboard.py` sets both `CF_UNICODETEXT`
  (OCR text) and `CF_DIB` (image) in a single open/empty/set sequence, so the paste target chooses.
- **The overlay must never steal keyboard focus** — paste sends Ctrl+V to whatever app is focused.
  The overlay window is topmost + layered + non-activating + transparent-for-input (see `overlay.py`).
- **Running indicator lives in `overlay.py`:** `App.tick` reports liveness via
  `overlay.set_status(camera_ok, hand_present)` each frame; the overlay renders a pulsing HUD dot
  and mirrors it on a `QSystemTrayIcon` (whose menu Quit calls `QApplication.quit()`, so
  `_run_with_overlay`'s `finally` performs the clean shutdown). Keep status derivation in
  `Overlay._status`; the app only reports the two booleans.

## Conventions

- Config is the single source of tunables (camera index, gesture thresholds, cursor smoothing,
  OCR language/path, mapping calibration). Never hard-code thresholds in logic modules — read them
  from the `Config` dataclass in `config.py`.
- Gesture thresholds are expressed in **normalized landmark units** (MediaPipe's 0..1 space) so they
  are resolution-independent.
- Cursor jitter is tamed with a One-Euro filter in `cursor.py`; tune via config, not code.
- MediaPipe landmarks are passed around as a `(21, 3)` numpy array (x, y normalized; z relative
  depth). Landmark indices follow MediaPipe's hand model (see `hand_tracker.LANDMARK`).
