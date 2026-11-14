#!/usr/bin/env bash
# Live transcription on macOS records the selected microphone (or a virtual audio device).
MACOS="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"$MACOS/.internal/transcribe.sh" --live "$@"
status=$?
if [ "$status" -ne 0 ]; then
    printf '\nPress Return to close...'
    read -r _ || true
fi
"$MACOS/.internal/close-terminal-window.sh"
exit "$status"
