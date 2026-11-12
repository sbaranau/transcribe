@echo off
rem (Re)creates everything the tool needs inside app\: a private Python 3.12, the virtual
rem environment with the pinned packages, and the models (download_models.py).
rem Needs internet access, and uv (https://docs.astral.sh/uv/): installed with winget if missing.
rem Safe to run again.
setlocal
set "TOOL_DIR=%~dp0"
set "APP=%~dp0app\"
set "HF_HUB_DISABLE_SYMLINKS_WARNING=1"

where uv >nul 2>nul || call :install_uv || exit /b 1

rem Asked now, before the long downloads, and done at the end. Optional; it can be changed
rem later with send-to-menu.cmd. No answer (no console) counts as No.
set "SEND_TO=N"
choice /c YN /m "Add the tool to the Explorer Send To menu (right-click a recording, Send To)"
if "%ERRORLEVEL%"=="1" set "SEND_TO=Y"

call :move_old_layout || exit /b 1

echo [1/3] Python 3.12
rem --no-bin: do not put python3.12.exe into the user's ~\.local\bin; the tool uses its own copy.
uv python install 3.12 --install-dir "%APP%python" --no-bin || exit /b 1
set "PY="
for /d %%D in ("%APP%python\cpython-3.12*") do set "PY=%%D\python.exe"
if not defined PY (echo Python 3.12 not found under %APP%python & exit /b 1)

echo [2/3] Virtual environment and packages
uv venv "%APP%venv" --python "%PY%" --clear || exit /b 1
uv pip install --python "%APP%venv\Scripts\python.exe" --only-binary ":all:" -r "%APP%requirements.txt" || exit /b 1

echo [3/3] Models: Whisper large-v3-turbo, about 1.6 GB, and voice separation, about 45 MB
"%APP%venv\Scripts\python.exe" "%APP%download_models.py" || exit /b 1

if "%SEND_TO%"=="Y" (
    call "%TOOL_DIR%send-to-menu.cmd" add || exit /b 1
) else (
    echo Send To menu not changed. To add it later, run send-to-menu.cmd.
)

echo Setup complete.
exit /b 0

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
rem Before 2026-11-12, python\, venv\ and models\ were next to this file. The models are moved
rem into app\, so nothing is downloaded again; the old Python and environment are bound to their
rem path and are removed, steps 1 and 2 make new ones in app\.
if not exist "%APP%models" mkdir "%APP%models"
for %%M in (large-v3-turbo diarization) do (
    if exist "%TOOL_DIR%models\%%M" if not exist "%APP%models\%%M" (
        echo Moving models\%%M into app\models ...
        move "%TOOL_DIR%models\%%M" "%APP%models\" >nul || exit /b 1
    )
)
rmdir "%TOOL_DIR%models" 2>nul
if exist "%TOOL_DIR%venv\pyvenv.cfg" (
    echo Removing the old environment venv\ ...
    rmdir /s /q "%TOOL_DIR%venv"
)
for /d %%D in ("%TOOL_DIR%python\cpython-3.12*") do (
    echo Removing the old Python in python\ ...
    rmdir /s /q "%TOOL_DIR%python"
    goto :eof
)
exit /b 0
