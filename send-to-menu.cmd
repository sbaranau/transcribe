@echo off
rem Optional: adds an entry to the Explorer "Send To" menu (right-click a recording ->
rem Send To), pointing to drop-files-here.cmd, or removes it again.
rem   send-to-menu.cmd add | remove | status
rem Without an argument it asks. Only the tool's own shortcuts in your SendTo folder are touched.
setlocal
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "TOOL_DIR=%~dp0"
set "PY=%TOOL_DIR%venv\Scripts\python.exe"

if not exist "%PY%" (
    echo The environment is missing. Run setup.cmd in %TOOL_DIR% first.
    exit /b 3
)
chcp 65001 >nul
if not "%~1"=="" goto run

"%PY%" "%TOOL_DIR%send_to_menu.py" status
choice /c ARC /m "Add to the Send To menu, Remove from it, or Cancel"
if errorlevel 3 exit /b 0
if errorlevel 2 (set "ACTION=remove") else (set "ACTION=add")
"%PY%" "%TOOL_DIR%send_to_menu.py" %ACTION%
set "RC=%ERRORLEVEL%"
pause
exit /b %RC%

:run
"%PY%" "%TOOL_DIR%send_to_menu.py" %1
exit /b %ERRORLEVEL%
