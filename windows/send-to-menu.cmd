@echo off
rem Optional: adds an entry to the Explorer "Send To" menu (right-click a recording ->
rem Send To), pointing to drop-files-here.cmd, or removes it again.
rem   windows\send-to-menu.cmd add | remove | status
rem Without an argument it asks. Only the tool's own shortcuts in your SendTo folder are touched.
setlocal
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
for %%T in ("%~dp0..") do set "ROOT=%%~fT\"
set "APP=%ROOT%app\"
set "PY=%APP%venv\Scripts\python.exe"

if not exist "%PY%" (
    echo The environment is missing. Run windows\setup.cmd in %ROOT% first.
    exit /b 3
)
chcp 65001 >nul
if not "%~1"=="" goto run

"%PY%" "%APP%shortcuts.py" sendto-status
choice /c ARC /m "Add to the Send To menu, Remove from it, or Cancel"
if errorlevel 3 exit /b 0
if errorlevel 2 (set "ACTION=sendto-remove") else (set "ACTION=sendto-add")
"%PY%" "%APP%shortcuts.py" %ACTION%
set "RC=%ERRORLEVEL%"
pause
exit /b %RC%

:run
"%PY%" "%APP%shortcuts.py" sendto-%1
exit /b %ERRORLEVEL%
