@echo off
rem Command-line entry point, for options the questions of drop-files-here.cmd do not cover.
rem Run "windows\transcribe.cmd --help" for all options.
setlocal
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "HF_HUB_DISABLE_SYMLINKS_WARNING=1"
for %%T in ("%~dp0..") do set "ROOT=%%~fT\"
set "APP=%ROOT%app\"

if not exist "%APP%venv\Scripts\python.exe" (
    echo The environment is missing. Run windows\setup.cmd in %ROOT% first.
    exit /b 3
)
if "%~1"=="" (
    echo Usage: windows\transcribe.cmd ^<file^> [more files] [--language ru^|multi] [--speakers [N]] [--check] [--summary] [--ai claude^|codex^|local] [--srt] [--terms FILE] [--out-dir DIR] [--cpu] [--force]
    echo        windows\transcribe.cmd ^<file^> --ask                  ask the questions, as drop-files-here.cmd does
    echo        windows\transcribe.cmd ^<transcript.txt^> --check --summary   check and summarize an existing transcript
    echo        windows\transcribe.cmd --live                          the live window
    echo Existing results are kept; --force overwrites them. All options: windows\transcribe.cmd --help
    echo For everyday use, the shortcuts in %ROOT% are simpler.
    exit /b 2
)

"%APP%venv\Scripts\python.exe" "%APP%transcribe.py" %*
exit /b %ERRORLEVEL%
