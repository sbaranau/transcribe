@echo off
setlocal
set "BASE=%~dp0"
set "DATA=%LOCALAPPDATA%\Live Transcription"
set "TRANSCRIBE_DATA_DIR=%DATA%"
set "TRANSCRIBE_CONFIG_DIR=%DATA%"
set "TRANSCRIBE_VERSION_FILE=%BASE%VERSION"
set "TRANSCRIBE_CHECK_UPDATES=1"
set "HF_HOME=%DATA%\huggingface"
set "HF_HUB_DISABLE_SYMLINKS_WARNING=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "PYTHONPATH=%BASE%packages"
chcp 65001 >nul

if "%~1"=="" (
    echo Drag an audio or video recording onto this shortcut.
    echo.
    pause
    exit /b 2
)

"%BASE%runtime\python.exe" "%BASE%app\bootstrap.py" %* --srt --ask
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" echo Transcription finished with an error. See the messages above.
pause
exit /b %RC%
