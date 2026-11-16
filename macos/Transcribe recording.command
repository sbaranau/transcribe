#!/usr/bin/env bash
# Double-click in Finder: opens the window to transcribe recordings made elsewhere; choose them
# there. The results go into a folder named after each recording, next to it.
MACOS="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"$MACOS/.internal/transcribe.sh" --files "$@"
status=$?
if [ "$status" -ne 0 ]; then
    printf '\nPress Return to close...'
    read -r _ || true
fi
"$MACOS/.internal/close-terminal-window.sh"
exit "$status"
