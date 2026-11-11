@echo off
rem (Re)creates everything the tool needs inside this folder: a private Python 3.12,
rem the virtual environment with the pinned packages, and the Whisper model.
rem Needs uv (https://docs.astral.sh/uv/) on PATH and internet access. Safe to run again.
setlocal
set "TOOL_DIR=%~dp0"
set "HF_HUB_DISABLE_SYMLINKS_WARNING=1"

where uv >nul 2>nul || (echo uv not found on PATH. & exit /b 1)

rem Asked now, before the long downloads, and done at the end. Optional; it can be changed
rem later with send-to-menu.cmd. No answer (no console) counts as No.
set "SEND_TO=N"
choice /c YN /m "Add the tool to the Explorer Send To menu (right-click a recording, Send To)"
if "%ERRORLEVEL%"=="1" set "SEND_TO=Y"

echo [1/3] Python 3.12
rem --no-bin: do not put python3.12.exe into the user's ~\.local\bin; the tool uses its own copy.
uv python install 3.12 --install-dir "%TOOL_DIR%python" --no-bin || exit /b 1
set "PY="
for /d %%D in ("%TOOL_DIR%python\cpython-3.12*") do set "PY=%%D\python.exe"
if not defined PY (echo Python 3.12 not found under %TOOL_DIR%python & exit /b 1)

echo [2/3] Virtual environment and packages
uv venv "%TOOL_DIR%venv" --python "%PY%" --clear || exit /b 1
uv pip install --python "%TOOL_DIR%venv\Scripts\python.exe" --only-binary ":all:" -r "%TOOL_DIR%requirements.txt" || exit /b 1

echo [3/3] Whisper model large-v3-turbo (about 1.6 GB)
if exist "%TOOL_DIR%models\large-v3-turbo\model.bin" (
    echo Model already present.
) else (
    "%TOOL_DIR%venv\Scripts\python.exe" -c "from huggingface_hub import snapshot_download; snapshot_download('mobiuslabsgmbh/faster-whisper-large-v3-turbo', local_dir=r'%TOOL_DIR%models\large-v3-turbo')" || exit /b 1
)

if "%SEND_TO%"=="Y" (
    call "%TOOL_DIR%send-to-menu.cmd" add || exit /b 1
) else (
    echo Send To menu not changed. To add it later, run send-to-menu.cmd.
)

echo Setup complete.
