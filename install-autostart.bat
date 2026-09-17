@echo off
rem Make hand-txt-copy start automatically when this user logs in, by placing a shortcut to the
rem silent launcher in the Windows Startup folder.
setlocal
set "TARGET=%~dp0start-hand-txt-copy.bat"
set "WORKDIR=%~dp0"
set "LNK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\hand-txt-copy.lnk"

powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:LNK); $s.TargetPath=$env:TARGET; $s.WorkingDirectory=$env:WORKDIR; $s.WindowStyle=7; $s.Save()"

echo(
echo   Auto-start installed. hand-txt-copy will launch at login.
echo   Shortcut: %LNK%
echo(
pause
exit /b 0
