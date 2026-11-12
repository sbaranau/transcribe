#!/usr/bin/env bash
# (Re)creates everything the tool needs inside app/: a private Python 3.12, the virtual
# environment with the pinned packages, and the models (download_models.py); then, if you want,
# the entries with their icons in the applications menu (linux/menu.sh).
# Needs internet access, and uv (https://docs.astral.sh/uv/): installed after asking if missing.
# Safe to run again.
set -euo pipefail
LINUX="$(dirname "$(readlink -f "$0")")"
ROOT="$(cd "$LINUX/.." && pwd)"
APP="$ROOT/app"
export HF_HUB_DISABLE_SYMLINKS_WARNING=1

ask_yes() {  # ask_yes "question" -> 0 for yes; no answer (no terminal) counts as no
    local answer=""
    [ -t 0 ] && read -r -p "$1 [y/N] " answer || true
    [[ "$answer" =~ ^[YyДд] ]]
}

if [ -f "$APP/venv/pyvenv.cfg" ] && [ ! -x "$APP/venv/bin/python" ]; then
    echo "app/venv here belongs to a Windows installation of this folder. Use a separate copy of the" >&2
    echo "tool for Linux (git clone into a Linux folder), not the Windows folder through /mnt/c." >&2
    exit 1
fi

export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null; then
    echo "uv, the Python manager this tool is installed with, is missing."
    if ask_yes "Install it now from astral.sh into ~/.local/bin?"; then
        curl -LsSf https://astral.sh/uv/install.sh | sh
    fi
    command -v uv >/dev/null || {
        echo "Install uv yourself, see https://docs.astral.sh/uv/getting-started/installation/," >&2
        echo "then run linux/setup.sh again." >&2
        exit 1
    }
fi

# The live mode records through PulseAudio (PipeWire provides it too).
if ! ldconfig -p 2>/dev/null | grep -q 'libpulse\.so\.0'; then
    echo "Note: libpulse is missing; the live mode needs it (Ubuntu/Debian: sudo apt install libpulse0)."
fi

# Asked now, before the long downloads, and done at the end. Can be changed later with linux/menu.sh.
MENU=N
ask_yes "Add the tool to the applications menu (and to Open With for recordings)?" && MENU=Y

echo "[1/4] Python 3.12"
# --no-bin: do not put python3.12 into ~/.local/bin; the tool uses its own copy.
uv python install 3.12 --install-dir "$APP/python" --no-bin
PY="$(ls -d "$APP"/python/cpython-3.12*-linux-*/bin/python3.12 2>/dev/null | head -n 1 || true)"
[ -n "$PY" ] || { echo "Python 3.12 not found under $APP/python" >&2; exit 1; }

echo "[2/4] Virtual environment and packages"
uv venv "$APP/venv" --python "$PY" --clear
uv pip install --python "$APP/venv/bin/python" --only-binary ":all:" -r "$APP/requirements.txt"

echo "[3/4] Models: Whisper large-v3-turbo, about 1.6 GB, and voice separation, about 45 MB"
"$APP/venv/bin/python" "$APP/download_models.py"

echo "[4/4] Applications menu"
chmod +x "$LINUX"/*.sh
if [ "$MENU" = Y ]; then
    "$LINUX/menu.sh" add
else
    echo "Menu not changed. To add the entries later, run linux/menu.sh add."
fi

echo "Setup complete. Start with linux/drop-files-here.sh <recording> or linux/live-transcribe.sh."
