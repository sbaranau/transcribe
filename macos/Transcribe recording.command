#!/usr/bin/env bash
# Double-click in Finder, then drag one or more recordings into this Terminal window.
MACOS="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ $# -eq 0 ]; then
    echo "Drag a recording into this window and press Return:"
    IFS= read -r file
    # Terminal shell-escapes a dragged path. shlex handles spaces, quotes and punctuation without
    # executing any part of the entered text.
    file="$(printf '%s\n' "$file" | "$MACOS/../app/venv/bin/python" -c \
        'import shlex, sys; values = shlex.split(sys.stdin.read()); print(values[0] if values else "")')"
    [ -n "$file" ] || { echo "No file was entered." >&2; exit 2; }
    set -- "$file"
fi
"$MACOS/.internal/transcribe.sh" "$@" --srt --ask
status=$?
printf '\nPress Return to close...'
read -r _ || true
"$MACOS/.internal/close-terminal-window.sh"
exit "$status"
