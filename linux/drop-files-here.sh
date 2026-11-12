#!/usr/bin/env bash
# Transcribes the given recordings, asking in the console for language, speakers, check and
# summary. Started from the "Расшифровать запись" menu entry (files can be opened with it from
# the file manager: Open With), or run with files as arguments. Without files it asks for them.
DIR="$(dirname "$(readlink -f "$0")")"
"$DIR/transcribe.sh" "$@" --srt --ask
status=$?
# Started from the menu, the terminal would close at once; keep the result readable.
if [ -t 0 ]; then
    read -r -p "Press Enter to close..." _
fi
exit $status
