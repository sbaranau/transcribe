@echo off
rem (Re)creates everything the tool needs inside app\: a private Python 3.12, the virtual
rem environment with the pinned packages, and the models (download_models.py); then the
rem shortcuts with their icons in the tool folder, and optionally the Send To menu entry.
rem Needs internet access, and uv (https://docs.astral.sh/uv/): installed with winget if missing.
rem Safe to run again.
setlocal
for %%T in ("%~dp0..") do set "ROOT=%%~fT\"
set "APP=%ROOT%app\"
set "HF_HUB_DISABLE_SYMLINKS_WARNING=1"

rem Started from the shortcut or by double-click, the window would close as soon as the script
rem ends, with the result or the error unread; then it waits for a key. From a terminal it does not.
set "WAIT_AT_END="
echo(%cmdcmdline%| findstr /i /l /c:"%~nx0" >nul && set "WAIT_AT_END=1"
call :main
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" echo Setup FAILED, see the messages above.
if defined WAIT_AT_END pause
exit /b %RC%

:main
call :check_not_running || exit /b 1
where uv >nul 2>nul || call :install_uv || exit /b 1

rem Asked now, before the long downloads, and done at the end. Optional; it can be changed
rem later with windows\send-to-menu.cmd. No answer (no console) counts as No.
set "SEND_TO=N"
choice /c YN /m "Add the tool to the Explorer Send To menu (right-click a recording, Send To)"
if "%ERRORLEVEL%"=="1" set "SEND_TO=Y"

call :move_old_layout || exit /b 1

echo [1/4] Python 3.12
rem --no-bin: do not put python3.12.exe into the user's ~\.local\bin; the tool uses its own copy.
uv python install 3.12 --install-dir "%APP%python" --no-bin || exit /b 1
set "PY="
for /d %%D in ("%APP%python\cpython-3.12*") do set "PY=%%D\python.exe"
if not defined PY (echo Python 3.12 not found under %APP%python & exit /b 1)

echo [2/4] Virtual environment and packages
uv venv "%APP%venv" --python "%PY%" --clear || exit /b 1
uv pip install --python "%APP%venv\Scripts\python.exe" --only-binary ":all:" -r "%APP%requirements.txt" || exit /b 1

echo [3/4] Models: Whisper large-v3-turbo, about 1.6 GB, and voice separation, about 45 MB
"%APP%venv\Scripts\python.exe" "%APP%download_models.py" || exit /b 1

echo [4/4] Shortcuts with icons in %ROOT%
"%APP%venv\Scripts\python.exe" "%APP%shortcuts.py" folder || exit /b 1
if "%SEND_TO%"=="Y" (
    call "%~dp0send-to-menu.cmd" add || exit /b 1
) else (
    echo Send To menu not changed. To add it later, run windows\send-to-menu.cmd.
)

echo Setup complete.
exit /b 0

:check_not_running
rem Rebuilding the environment while the tool runs would delete its packages and then fail on
rem the locked python.exe. Opening the file for appending writes nothing, but fails while it runs.
if not exist "%APP%venv\Scripts\python.exe" exit /b 0
((call ) >>"%APP%venv\Scripts\python.exe") 2>nul && exit /b 0
echo The tool is running (a transcription or the live window). Close it, then run setup again.
exit /b 1

:install_uv
echo uv, the Python manager this tool is installed with, is missing. Installing it with winget...
where winget >nul 2>nul || (
    echo winget is not available. Install uv yourself, see https://docs.astral.sh/uv/getting-started/installation/
    echo then run setup.cmd again.
    exit /b 1
)
rem No agreements are accepted here: winget asks you itself if it needs to.
call winget install --id astral-sh.uv --exact --source winget
rem winget puts uv on PATH for new windows only; look where it and uv's own installer put it.
set "PATH=%PATH%;%LOCALAPPDATA%\Microsoft\WinGet\Links;%USERPROFILE%\.local\bin"
where uv >nul 2>nul && exit /b 0
echo uv was not found after the installation. Open a new window and run setup.cmd again.
exit /b 1

:move_old_layout
rem Before 2026-11-12, python\, venv\ and models\ were in the tool folder itself. The models are
rem moved into app\, so nothing is downloaded again; the old Python and environment are bound to
rem their path and are removed, steps 1 and 2 make new ones in app\.
if not exist "%APP%models" mkdir "%APP%models"
for %%M in (large-v3-turbo diarization) do (
    if exist "%ROOT%models\%%M" if not exist "%APP%models\%%M" (
        echo Moving models\%%M into app\models ...
        move "%ROOT%models\%%M" "%APP%models\" >nul || exit /b 1
    )
)
rmdir "%ROOT%models" 2>nul
if exist "%ROOT%venv\pyvenv.cfg" (
    echo Removing the old environment venv\ ...
    rmdir /s /q "%ROOT%venv"
)
for /d %%D in ("%ROOT%python\cpython-3.12*") do (
    echo Removing the old Python in python\ ...
    rmdir /s /q "%ROOT%python"
    goto :eof
)
exit /b 0
