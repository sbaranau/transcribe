@echo off
rem Transcribe audio/video files to text. Run "transcribe.cmd --help" for all options.
setlocal
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "HF_HUB_DISABLE_SYMLINKS_WARNING=1"
set "TOOL_DIR=%~dp0"
set "APP=%~dp0app\"

if not exist "%APP%venv\Scripts\python.exe" (
    echo The environment is missing. Run setup.cmd in %TOOL_DIR% first.
    exit /b 3
)
if "%~1"=="" (
    echo Usage: transcribe.cmd ^<file^> [more files] [--language ru^|multi] [--speakers [N]] [--summary] [--ai claude^|codex^|local] [--srt] [--terms FILE] [--out-dir DIR] [--cpu] [--force]
    echo        transcribe.cmd ^<file^> --ask                  ask for language, speakers and summary
    echo        transcribe.cmd ^<transcript.txt^> --summary     summarize an existing transcript
    echo Existing results are kept; --force overwrites them. All options: transcribe.cmd --help
    echo Or drag files onto drop-files-here.cmd, which asks the questions.
    exit /b 2
)

"%APP%venv\Scripts\python.exe" "%APP%transcribe.py" %*
exit /b %ERRORLEVEL%
