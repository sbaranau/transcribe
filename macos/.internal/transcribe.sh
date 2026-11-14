#!/usr/bin/env bash
# Internal macOS entry point. Whisper runs on the CPU because CUDA is unavailable on Macs.
set -euo pipefail
INTERNAL="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MACOS="$(cd "$INTERNAL/.." && pwd)"
ROOT="$(cd "$MACOS/.." && pwd)"
PY="$ROOT/app/venv/bin/python"
export PYTHONIOENCODING=utf-8 PYTHONUTF8=1 HF_HUB_DISABLE_SYMLINKS_WARNING=1

if [ ! -x "$PY" ]; then
    echo "The environment is missing. Run macos/setup.command in $ROOT first." >&2
    exit 3
fi
if [ $# -eq 0 ]; then
    echo "Usage: macos/Transcribe recording.command <recording> [options]" >&2
    echo "       macos/Live transcription.command" >&2
    exit 2
fi

exec "$PY" "$ROOT/app/transcribe.py" "$@" --cpu
