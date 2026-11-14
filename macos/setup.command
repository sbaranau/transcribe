#!/usr/bin/env bash
# Installs a private Python, packages and models for this copy of the application.
set -euo pipefail
MACOS="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$MACOS/.." && pwd)"
APP="$ROOT/app"
export HF_HUB_DISABLE_SYMLINKS_WARNING=1

pause_on_exit() {
    status=$?
    if [ -t 0 ]; then
        printf '\nPress Return to close...'
        read -r _ || true
    fi
    "$MACOS/.internal/close-terminal-window.sh"
    exit "$status"
}
trap pause_on_exit EXIT

if ! command -v uv >/dev/null 2>&1; then
    echo "uv, the Python manager used by this application, is missing."
    printf "Install it from astral.sh now? [y/N] "
    read -r answer
    case "$answer" in
        y|Y) curl -LsSf https://astral.sh/uv/install.sh | sh ;;
    esac
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi
command -v uv >/dev/null 2>&1 || {
    echo "Install uv from https://docs.astral.sh/uv/ and run this file again." >&2
    exit 1
}

echo "[1/3] Python 3.12"
uv python install 3.12 --install-dir "$APP/python" --no-bin
PY="$(find "$APP/python" -type f -path '*/bin/python3.12' -perm -111 | head -n 1)"
[ -n "$PY" ] || { echo "Python 3.12 was not found under $APP/python" >&2; exit 1; }

echo "[2/3] Virtual environment and packages"
uv venv "$APP/venv" --python "$PY" --clear
uv pip install --python "$APP/venv/bin/python" --only-binary ':all:' -r "$APP/requirements.txt"
"$APP/venv/bin/python" -c 'import tkinter' || {
    echo "This Python build has no tkinter support, which the live window needs." >&2
    exit 1
}

echo "[3/3] Speech models (about 1.7 GB)"
"$APP/venv/bin/python" "$APP/download_models.py"
chmod +x "$MACOS/.internal"/*.sh "$MACOS"/*.command
echo "Setup complete. Use the .command launchers in $MACOS."
