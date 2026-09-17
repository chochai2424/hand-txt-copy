@echo off
rem Open the visible video-call-style monitor window (webcam + hand tracking + status).
rem Good for setup, demos, and checking the camera/gestures. Does not copy/paste — use
rem start-hand-txt-copy.bat for the hands-free overlay that actually copies and pastes.
setlocal
cd /d "%~dp0"

set "PY=.venv\Scripts\pythonw.exe"
if not exist "%PY%" goto :novenv

set "PYTHONPATH=%~dp0src"

set "CFG="
if exist "config\station.yaml" set "CFG=--config config\station.yaml"

start "" "%PY%" -m hand_txt_copy --console %CFG% %*
exit /b 0

:novenv
echo(
echo   Could not find %PY%
echo(
echo   Create the runtime virtual environment first, using Python 3.11 or 3.12
echo   (MediaPipe has no wheels for newer versions yet^):
echo(
echo       py -3.12 -m venv .venv
echo       .venv\Scripts\python.exe -m pip install -r requirements.txt
echo(
pause
exit /b 1
