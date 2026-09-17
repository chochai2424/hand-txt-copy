@echo off
rem Stop the background hand-txt-copy process. Only kills pythonw processes whose command line
rem mentions this app, so other Python programs are left alone.
setlocal
echo Stopping hand-txt-copy...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'pythonw.exe' -and $_.CommandLine -like '*hand_txt_copy*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
echo Done.
exit /b 0
