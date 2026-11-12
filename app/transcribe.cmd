@echo off
rem Command-line entry point, for options the questions of drop-files-here.cmd do not cover.
rem Run "app\transcribe.cmd --help" for all options.
setlocal
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "HF_HUB_DISABLE_SYMLINKS_WARNING=1"
set "APP=%~dp0"
for %%T in ("%~dp0..") do set "TOOL_DIR=%%~fT\"

if not exist "%APP%venv\Scripts\python.exe" (
    echo The environment is missing. Run setup.cmd in %TOOL_DIR% first.
    exit /b 3
)
if "%~1"=="" (
    echo Usage: app\transcribe.cmd ^<file^> [more files] [--language ru^|multi] [--speakers [N]] [--check] [--summary] [--ai claude^|codex^|local] [--srt] [--terms FILE] [--out-dir DIR] [--cpu] [--force]
    echo        app\transcribe.cmd ^<file^> --ask                  ask the questions, as drop-files-here.cmd does
    echo        app\transcribe.cmd ^<transcript.txt^> --check --summary   check and summarize an existing transcript
    echo Existing results are kept; --force overwrites them. All options: app\transcribe.cmd --help
    echo For everyday use, drag files onto drop-files-here.cmd in %TOOL_DIR%
    exit /b 2
)

"%APP%venv\Scripts\python.exe" "%APP%transcribe.py" %*
exit /b %ERRORLEVEL%
