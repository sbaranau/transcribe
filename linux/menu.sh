#!/usr/bin/env bash
# Optional: the tool's entries with their icons in the applications menu, or removes them.
#   linux/menu.sh add | remove | status
# The recording entry also appears under Open With for audio and video files in the file manager.
# The entries are named in the interface language and hold absolute paths; after moving the
# tool folder, run linux/menu.sh add again. The work is done by app/shortcuts.py.
set -euo pipefail
ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
PY="$ROOT/app/venv/bin/python"
if [ ! -x "$PY" ]; then
    echo "The environment is missing. Run linux/setup.sh in $ROOT first." >&2
    exit 3
fi
case "${1:-}" in
    add|remove|status) exec "$PY" "$ROOT/app/shortcuts.py" "menu-$1" ;;
    *) echo "Usage: linux/menu.sh add | remove | status" >&2; exit 2 ;;
esac
