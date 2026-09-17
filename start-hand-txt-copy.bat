@echo off
rem Launch hand-txt-copy silently in the background (no console window).
rem Double-click this file. The transparent overlay floats over all windows and never steals
rem keyboard focus, so the operator controls it with gestures only.
setlocal
cd /d "%~dp0"

set "PY=.venv\Scripts\pythonw.exe"
if not exist "%PY%" goto :novenv

rem Make the src/ layout importable without an editable install.
set "PYTHONPATH=%~dp0src"

rem Prefer a calibrated per-station config if one exists, else the documented default.
set "CFG="
if exist "config\station.yaml" set "CFG=--config config\station.yaml"

rem "start" detaches so this window closes immediately; pythonw.exe shows no console.
start "" "%PY%" -m hand_txt_copy %CFG% %*
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
