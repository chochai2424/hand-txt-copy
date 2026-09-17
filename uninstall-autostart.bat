@echo off
rem Remove the login auto-start shortcut created by install-autostart.bat.
setlocal
set "LNK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\hand-txt-copy.lnk"
if exist "%LNK%" del "%LNK%"
echo Auto-start removed (if it was installed).
pause
exit /b 0
