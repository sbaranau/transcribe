#!/usr/bin/env bash
# Opens the window to transcribe recordings made elsewhere (Teams, Zoom, phone, ...): the files
# given (from the application menu or a file manager), or, without any, a file dialog in the
# window. The results go into a folder named after each recording, next to it.
# drop-files-here.sh still asks the same questions in the terminal.
exec "$(dirname "$(readlink -f "$0")")/transcribe.sh" --files "$@"
