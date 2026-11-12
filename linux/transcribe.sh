#!/usr/bin/env bash
# Command-line entry point, for options the questions of drop-files-here.sh do not cover.
# Run "linux/transcribe.sh --help" for all options.
set -euo pipefail
ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
APP="$ROOT/app"
PY="$APP/venv/bin/python"
export PYTHONIOENCODING=utf-8 PYTHONUTF8=1 HF_HUB_DISABLE_SYMLINKS_WARNING=1

if [ ! -x "$PY" ]; then
    echo "The environment is missing. Run linux/setup.sh in $ROOT first." >&2
    exit 3
fi
if [ $# -eq 0 ]; then
    cat <<EOF
Usage: linux/transcribe.sh <file> [more files] [--language ru|multi] [--speakers [N]] [--check] [--summary] [--ai claude|codex|local] [--srt] [--terms FILE] [--out-dir DIR] [--cpu] [--force]
       linux/transcribe.sh <file> --ask                  ask the questions, as drop-files-here.sh does
       linux/transcribe.sh <transcript.txt> --check --summary   check and summarize an existing transcript
       linux/transcribe.sh --live                          the live window
Existing results are kept; --force overwrites them. All options: linux/transcribe.sh --help
EOF
    exit 2
fi

# The NVIDIA libraries (cuBLAS, cuDNN) come as pip packages; the GPU code finds them only on
# LD_LIBRARY_PATH, which has to be set before Python starts. Without an NVIDIA GPU the tool
# runs on the CPU and they are not used.
for lib in "$APP"/venv/lib/python3*/site-packages/nvidia/*/lib; do
    [ -d "$lib" ] && LD_LIBRARY_PATH="$lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
done
export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}"

exec "$PY" "$APP/transcribe.py" "$@"
